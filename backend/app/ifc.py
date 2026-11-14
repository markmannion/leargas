"""IFC engine: execute a parsed `Query` against an IFC model with ifcopenshell.

- Counts are element occurrences by IFC class, optionally restricted to a building storey.
- Quantities come from the element's base quantity set (BaseQuantities / Qto_*BaseQuantities),
  scaled by that quantity type's own project unit (length, area and volume units can differ).
  When an element has no stored quantity, it falls back to geometry (space footprint area,
  element volume). If neither is available the whole query is `CannotVerify`, never a partial sum.
- A floor-plan rendering `<model>_plan-NN-<level>.pdf/png/svg` resolves to `<model>.ifc`.

No question text or gold answers are used here.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import ifcopenshell
import ifcopenshell.util.element as E
import ifcopenshell.util.unit as U

from .query.schema import Query
from .schema import SlabArea


class CannotVerify(ValueError):
    """The model doesn't hold enough unambiguous information to answer."""


@dataclass
class Item:
    guid: str
    ifc_class: str
    name: Optional[str]
    storey: Optional[str]
    value: Optional[float] = None  # this element's contribution for area/length/volume
    method: Optional[str] = None  # "qto" or "geometry"
    room_id: Optional[str] = None
    # doors / windows
    mark: Optional[str] = None  # the occurrence's own number, e.g. Revit "Mark"
    type_mark: Optional[str] = None
    type_name: Optional[str] = None
    leaves: Optional[int] = None
    width_m: Optional[float] = None
    location: List[str] = field(default_factory=list)  # adjoining spaces


@dataclass
class Result:
    value: float
    unit: str
    items: List[Item]
    explanation: str
    model_path: str
    warnings: List[str] = field(default_factory=list)
    slab_areas: List[SlabArea] = field(default_factory=list)


# ---------------------------------------------------------------- model resolution / loading

_PLAN = re.compile(r"_plan-\d+.*$")


def resolve_model(path: str | Path) -> Path:
    """The IFC model behind a dataset path: the .ifc itself, or the model a plan was rendered from."""
    p = Path(path)
    if p.suffix.lower() == ".ifc":
        if not p.exists():
            raise CannotVerify(f"IFC model not found: {p}")
        return p
    stem = _PLAN.sub("", p.stem)
    cand = p.with_name(stem + ".ifc")
    if cand.exists():
        return cand
    # fallback: the longest existing <model>.ifc whose stem prefixes this file's stem
    best = None
    for f in p.parent.glob("*.ifc"):
        if p.stem.startswith(f.stem + "_") and (best is None or len(f.stem) > len(best.stem)):
            best = f
    if best is None:
        raise CannotVerify(f"No IFC model found for {p.name}")
    return best


@lru_cache(maxsize=8)
def open_model(path: str) -> "Model":
    return Model(path)


def _projected_area(g) -> Optional[float]:
    try:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
    except ImportError:
        return None
    v, f = g.verts, g.faces
    tris = []
    for i in range(0, len(f), 3):
        a, b, c = (f[i + k] * 3 for k in range(3))
        p = Polygon([(v[a], v[a + 1]), (v[b], v[b + 1]), (v[c], v[c + 1])])
        if p.area > 1e-9:
            tris.append(p)
    return unary_union(tris).area if tris else None


def _norm(s: Optional[str]) -> str:
    return " ".join(unicodedata.normalize("NFKC", s or "").casefold().split())


# ---------------------------------------------------------------- query targets

def _typed(cls: str, type_cls: str) -> Callable[[ifcopenshell.file], list]:
    """Occurrences of an IFC4 class, or (IFC2X3) IfcFlowTerminal occurrences typed as `type_cls`."""
    def get(m: ifcopenshell.file) -> list:
        out = []
        try:
            out = list(m.by_type(cls))
        except RuntimeError:  # class not in this schema
            pass
        seen = {e.id() for e in out}
        for e in m.by_type("IfcFlowTerminal"):
            t = E.get_type(e)
            if e.id() not in seen and t is not None and t.is_a(type_cls):
                out.append(e)
        return out
    return get


_CLASSES: Dict[str, Callable[[ifcopenshell.file], list]] = {
    "door": lambda m: m.by_type("IfcDoor"),
    "window": lambda m: m.by_type("IfcWindow"),
    "wall": lambda m: m.by_type("IfcWall"),
    "slab": lambda m: m.by_type("IfcSlab"),
    "column": lambda m: m.by_type("IfcColumn"),
    "beam": lambda m: m.by_type("IfcBeam"),
    "stair": lambda m: m.by_type("IfcStair"),
    "room": lambda m: m.by_type("IfcSpace"),
    "storey": lambda m: m.by_type("IfcBuildingStorey"),
    "sanitary_fixture": _typed("IfcSanitaryTerminal", "IfcSanitaryTerminalType"),
    "light_fixture": _typed("IfcLightFixture", "IfcLightFixtureType"),
}

# (target, op, side_area) -> base quantity names to try, in order, and the quantity's unit type
_QTO: Dict[Tuple[str, str, bool], Tuple[Tuple[str, ...], str]] = {
    ("room", "area", False): (("NetFloorArea",), "AREAUNIT"),
    ("wall", "length", False): (("Length",), "LENGTHUNIT"),
    ("wall", "area", True): (("NetSideArea",), "AREAUNIT"),
    ("wall", "volume", False): (("NetVolume",), "VOLUMEUNIT"),
    ("slab", "volume", False): (("NetVolume",), "VOLUMEUNIT"),
    ("column", "volume", False): (("NetVolume",), "VOLUMEUNIT"),
    ("beam", "volume", False): (("NetVolume",), "VOLUMEUNIT"),
    ("slab", "area", False): (("NetArea",), "AREAUNIT"),
}
_SI_UNIT = {"length": "m", "area": "m2", "volume": "m3"}


# ---------------------------------------------------------------- model

class Model:
    def __init__(self, path: str):
        self.path = path
        self.f = ifcopenshell.open(path)
        self._scale = {
            ut: U.calculate_unit_scale(self.f, ut) for ut in ("LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT")
        }
        self._storey_cache: Dict[int, Optional[object]] = {}

    # --- spatial structure
    @property
    def project_name(self) -> Optional[str]:
        p = self.f.by_type("IfcProject")
        return (p[0].LongName or p[0].Name) if p else None

    def storeys(self) -> list:
        return list(self.f.by_type("IfcBuildingStorey"))

    def storey_of(self, e) -> Optional[object]:
        k = e.id()
        if k not in self._storey_cache:
            c, hops = e, 0
            while c is not None and not c.is_a("IfcBuildingStorey") and hops < 10:
                c = E.get_container(c) or E.get_aggregate(c)
                hops += 1
            self._storey_cache[k] = c if c is not None and c.is_a("IfcBuildingStorey") else None
        return self._storey_cache[k]

    def find_storey(self, name: str):
        exact = [s for s in self.storeys() if s.Name == name]
        if len(exact) == 1:
            return exact[0]
        loose = [s for s in self.storeys() if _norm(s.Name) == _norm(name) or _norm(s.LongName) == _norm(name)]
        if len(loose) == 1:
            return loose[0]
        if not exact and not loose:
            raise CannotVerify(f"No storey named {name!r} (have: {', '.join(s.Name or '?' for s in self.storeys())})")
        raise CannotVerify(f"Storey name {name!r} is ambiguous")

    # --- quantities
    def qto(self, e, names: Tuple[str, ...], unit_type: str) -> Optional[float]:
        qsets = E.get_psets(e, qtos_only=True)
        ordered = sorted(qsets.items(), key=lambda kv: (not kv[0].startswith(("Qto_", "BaseQuantities")), kv[0]))
        for qname, qs in ordered:
            if not (qname.startswith("Qto_") or qname == "BaseQuantities"):
                continue
            for n in names:
                v = qs.get(n)
                if isinstance(v, (int, float)) and v > 0:
                    # A quantity may override the project unit (e.g. an mm² QTO in an m² project).
                    qset = self.f.by_id(qs["id"])
                    quantity = next((q for q in qset.Quantities if q.Name == n), None)
                    unit = getattr(quantity, "Unit", None)
                    if unit is not None:
                        from .slab_ifc import unit_scale
                        if getattr(unit, "UnitType", None) != unit_type:
                            continue
                        return float(v) * unit_scale(unit)
                    return float(v) * self._scale[unit_type]
        return None

    def geometry(self, e, what: str) -> Optional[float]:
        try:
            import ifcopenshell.geom as G
            import ifcopenshell.util.shape as S
            st = G.settings()
            st.set(st.USE_WORLD_COORDS, True)
            g = G.create_shape(st, e).geometry
        except Exception:
            return None
        # geometry is produced in metres by ifcopenshell.geom
        if what == "volume":
            v = S.get_volume(g)
        elif what == "area":
            v = S.get_footprint_area(g)
            if not v:  # e.g. open SurfaceModel bodies: union of faces projected onto the floor plane
                v = _projected_area(g)
        else:
            v = None
        return float(v) if v and v > 0 else None

    # --- doors / windows
    def type_marks(self, e) -> Tuple[Optional[str], List[str]]:
        """(the type mark to show, every value a type mark query may match) for a door/window.

        Looked up in order: an explicit "Type Mark" (Revit), Pset_*Common.Reference, the type's
        name. A query matches a whole value or its leading code ("ED05" in "ED05_100x210_w").
        """
        t = E.get_type(e)
        marks: List[str] = []
        refs: List[str] = []
        for scope in (t, e):
            if scope is None:
                continue
            for pset, props in E.get_psets(scope).items():
                for k, v in props.items():
                    if not isinstance(v, str) or not v.strip():
                        continue
                    if k.casefold() == "type mark":
                        marks.append(v.strip())
                    elif k == "Reference" and pset.startswith("Pset_") and pset.endswith("Common"):
                        refs.append(v.strip())
        names = [x.strip() for x in ((t.Name if t is not None else None), getattr(e, "ObjectType", None)) if x and x.strip()]
        values = marks + refs + names
        return (values[0] if values else None), values

    @staticmethod
    def _mark_matches(want: str, values: List[str]) -> bool:
        w = _norm(want)
        for v in values:
            n = _norm(v)
            if n == w or re.split(r"[\s_:\-/]+", n)[0] == w:
                return True
        return False

    def leaves(self, e) -> Optional[int]:
        t = E.get_type(e)
        names = [getattr(x, attr, None) for x in (e, t) if x is not None
                 for attr in ("OperationType", "PartitioningType")]
        names = [str(n) for n in names if n and str(n) not in ("NOTDEFINED", "USERDEFINED")]
        text = " ".join(names + [str(getattr(x, "Name", "") or "") for x in (e, t) if x is not None]).upper()
        if not names and not text.strip():
            return None
        if "TRIPLE" in text:
            return 3
        if "DOUBLE" in text or "DOPPEL" in text or "TWO_PANEL" in text:
            return 2
        if "REVOLVING" in text:
            return None
        if names and any(("SINGLE" in n or "SLIDING_TO" in n or "FOLDING_TO" in n) for n in names):
            return 1
        return None

    def adjoining_spaces(self, e) -> List[str]:
        out: List[str] = []
        for rel in getattr(e, "ProvidesBoundaries", None) or []:
            sp = rel.RelatingSpace
            if sp is not None and sp.is_a("IfcSpace"):
                name = (self.space_names(sp) or [None])[0]
                if name and name not in out:
                    out.append(name)
        return out

    # --- names
    @staticmethod
    def space_names(sp) -> List[str]:
        n, ln = sp.Name, getattr(sp, "LongName", None)
        out = [x for x in (f"{ln} ({n})" if ln and n else None, n, ln) if x]
        return out

    # --- execute
    def query(self, q: Query) -> Result:
        if q.target not in _CLASSES:
            raise CannotVerify(f"Target {q.target!r} is not supported for IFC models")
        if q.room_type or q.label or q.room_id or q.apartment or q.exclude_outdoor or q.numbered_only:
            raise CannotVerify("Room categories, printed labels and apartments are not IFC concepts here")

        elems = list(_CLASSES[q.target](self.f))
        # Some exporters (e.g. ArchiCAD) nest risers/landings as IfcStair parts of an IfcStair.
        # Count only top-level occurrences: drop elements that are parts of another selected element.
        ids = {e.id() for e in elems}
        elems = [e for e in elems if not ((p := E.get_aggregate(e)) is not None and p.id() in ids)]
        scope_txt = "the model"
        storey = None
        if q.scope == "level" or q.level:
            if not q.level:
                raise CannotVerify("Level scope without a level name")
            storey = self.find_storey(q.level)
            elems = [e for e in elems if self.storey_of(e) == storey]
            scope_txt = f"storey {storey.Name!r}"

        if q.name:
            if q.target != "room":
                raise CannotVerify("Named lookups are only supported for spaces")
            hits = [e for e in elems if q.name in self.space_names(e)]
            if not hits:
                hits = [e for e in elems if _norm(q.name) in map(_norm, self.space_names(e))]
            if len(hits) != 1:
                raise CannotVerify(f"Space {q.name!r} {'not found' if not hits else 'is ambiguous'} on {scope_txt}")
            elems = hits

        notes: List[str] = []
        kind_txt = q.target
        if q.target in ("door", "window"):
            # One occurrence per physical door/window: types, styles and schedule tags are separate
            # entities and never selected; a GlobalId exported twice is counted once.
            seen, unique = set(), []
            for e in elems:
                if e.GlobalId not in seen:
                    seen.add(e.GlobalId)
                    unique.append(e)
            if len(unique) < len(elems):
                notes.append(f"{len(elems) - len(unique)} repeated occurrence(s) dropped")
            elems = unique
            if q.type_mark:
                elems = [e for e in elems if self._mark_matches(q.type_mark, self.type_marks(e)[1])]
                if not elems:
                    raise CannotVerify(f"No {q.target} with type mark {q.type_mark!r} on {scope_txt}")
                kind_txt = f"type {q.type_mark} {q.target}"

        def item(e, value=None, method=None) -> Item:
            st = self.storey_of(e)
            name = getattr(e, "Name", None)
            room_id = name if q.target == "room" else None
            if q.target == "room":
                name = getattr(e, "LongName", None) or name
            it = Item(e.GlobalId, e.is_a(), name, st.Name if st else None, value, method, room_id)
            if q.target in ("door", "window"):
                t = E.get_type(e)
                shown, _ = self.type_marks(e)
                it.type_mark = shown
                it.type_name = t.Name if t is not None and t.Name else getattr(e, "ObjectType", None)
                it.leaves = self.leaves(e)
                width = getattr(e, "OverallWidth", None)
                it.width_m = round(float(width) * self._scale["LENGTHUNIT"], 3) if width else None
                it.location = self.adjoining_spaces(e)
                marks = [v for ps in E.get_psets(e).values() for k, v in ps.items()
                         if k == "Mark" and isinstance(v, str) and v.strip()]
                it.mark = marks[0] if marks else None  # IFC Tag is usually a CAD element id, not a door number
            return it

        if q.op == "count":
            items = [item(e) for e in elems]
            note = f" ({'; '.join(notes)})" if notes else ""
            if q.target == "door" and q.count_basis == "leaves":
                if any(i.leaves is None for i in items):
                    raise CannotVerify("Some doors don't state an operation type, so their leaves can't be counted")
                n = sum(i.leaves for i in items)
                return Result(n, "count", items, f"{n} door leaves in {len(items)} {kind_txt}(s) on {scope_txt}{note}", self.path)
            return Result(len(elems), "count", items,
                          f"{len(elems)} {kind_txt} element(s) on {scope_txt}{note}", self.path)

        key = (q.target, q.op, bool(q.side_area))
        if key not in _QTO:
            raise CannotVerify(f"{q.op} of {q.target} is not supported")
        names, unit_type = _QTO[key]
        if not elems:
            raise CannotVerify(f"No {q.target} elements on {scope_txt}")

        items, total, methods = [], 0.0, set()
        for e in elems:
            v, method = self.qto(e, names, unit_type), "qto"
            if v is None and not q.side_area and q.op in ("area", "volume") and q.target in ("room", "slab", "wall", "column", "beam"):
                v, method = self.geometry(e, q.op), "geometry"
            if v is None:
                raise CannotVerify(f"{e.is_a()} {e.GlobalId} has no {'/'.join(names)} quantity or usable geometry")
            items.append(item(e, v if q.target == "slab" else round(v, 6), method))
            methods.add(method)
            total += v

        unit = _SI_UNIT[q.op]
        result = Result(round(total, 4), unit, items,
                      f"Sum of {'/'.join(names)} over {len(items)} {q.target} element(s) on {scope_txt} "
                      f"(from {', '.join(sorted(methods))})", self.path)
        if q.target == "slab" and q.op == "area":
            from .slab_ifc import slab_area
            result.slab_areas = [slab_area(self, e, i) for e, i in zip(elems, items)]
        return result


def answer(path: str | Path, q: Query) -> Result:
    """Resolve the model for `path` (a .ifc or a plan rendered from one) and run `q`."""
    return open_model(str(resolve_model(path))).query(q)
