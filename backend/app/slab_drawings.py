"""Structural drawing profile: scaled slab zones + explicit schedule/detail links.

SLAB_OUTLINE closed polylines, SLAB_OPENING cutouts, SLAB_MARK text in each zone.
SLAB_SCHEDULE/SLAB_DETAIL text and text-based PDF sheets carry keyed schedule rows.
Only sheets in the same upload group (or same-stem twins) are linked.
"""
from collections import defaultdict
from dataclasses import dataclass
from math import fsum, isfinite
from pathlib import Path
import re

from .schema import Evidence, PolygonEvidence, SlabArea, Source, SpecificationReference
from .slabs import specification_key, specification_text


class CannotVerify(ValueError):
    pass


@dataclass
class ScheduleRow:
    mark: str
    values: dict
    reference: SpecificationReference


_FIELD = re.compile(r"\b(type|thickness|reinforcement|detail)\s*[:=]\s*(.*?)(?=\s*[|;]|$)", re.I)
_THICKNESS = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(mm|cm|m|in(?:ches)?|\")$", re.I)


def _thickness(value):
    m = _THICKNESS.fullmatch(value.strip())
    if m:
        v = float(m[1].replace(",", ".")) * {"mm": 1, "cm": 10, "m": 1000, "in": 25.4, "inches": 25.4, '"': 25.4}[m[2].lower()]
        return v if isfinite(v) and v > 0 else None
    return None


def parse_schedule(text: str, path: str, page: int = 0) -> list[ScheduleRow]:
    rows, headers, thickness_unit = [], None, None
    for line in text.splitlines():
        cells = [c.strip() for c in re.split(r"[|;]", line)]
        if len(cells) > 1 and cells[0].casefold() in ("mark", "slab mark", "slab", "detail mark"):
            headers = []
            thickness_unit = None
            for c in cells:
                header = c.casefold()
                if header in ("slab type",):
                    header = "type"
                if re.fullmatch(r"(?:thickness|thk)\s*\((mm|cm|m|in)\)", header):
                    thickness_unit = re.search(r"\((.*?)\)", header)[1]
                    header = "thickness"
                headers.append(header)
            continue
        first = re.sub(r"^(?:slab|detail)\s+", "", cells[0], flags=re.I).strip()
        if not re.fullmatch(r"[A-Za-z][\w.-]{0,39}", first):
            continue
        values = {k.lower(): v.strip() for k, v in _FIELD.findall(line)}
        if not values and headers and len(cells) == len(headers):
            values = {k: v for k, v in zip(headers[1:], cells[1:]) if k in ("type", "thickness", "reinforcement", "detail")}
        if not values:
            continue
        values = {k: v for k, v in values.items() if specification_text(v)}
        if "thickness" in values:
            value = values["thickness"]
            if thickness_unit and re.fullmatch(r"\d+(?:[.,]\d+)?", value):
                value += f" {thickness_unit}"
            values["thickness"] = _thickness(value)
        rows.append(ScheduleRow(first.casefold(), values, SpecificationReference(path=path, page=page, label=line.strip())))
    return rows


def _sheet_files(path: Path, root: Path):
    rel = path.relative_to(root)
    if len(rel.parts) >= 3 and rel.parts[0] == "uploads":
        files = path.parent.iterdir()
    else:
        files = [path.with_suffix(ext) for ext in (".dxf", ".pdf")]
    return sorted(p for p in files if p.is_file() and p.suffix.lower() in (".dxf", ".pdf")
                  and p.resolve().is_relative_to(root.resolve()))


def load_schedules(path: Path, root: Path) -> tuple[list[ScheduleRow], list[str]]:
    import ezdxf
    rows, warnings = [], []
    for sheet in _sheet_files(path, root):
        rel = sheet.relative_to(root).as_posix()
        try:
            if sheet.suffix.lower() == ".dxf":
                doc = ezdxf.readfile(sheet)
                texts = [_text(e) for e in doc.modelspace()
                         if e.dxftype() in ("TEXT", "MTEXT") and e.dxf.layer.upper() in ("SLAB_SCHEDULE", "SLAB_DETAIL")]
                rows += parse_schedule("\n".join(texts), rel)
            else:
                import pymupdf
                with pymupdf.open(sheet) as doc:
                    for n, page in enumerate(doc):
                        rows += parse_schedule(page.get_text(sort=True), rel, n)
                        # Native PDF table cells are often separate text blocks. Preserve their
                        # row/column association rather than joining unrelated nearby strings.
                        try:
                            for table in page.find_tables().tables:
                                text = "\n".join(" | ".join((cell or "").replace("\n", " ") for cell in row)
                                                 for row in table.extract())
                                rows += parse_schedule(text, rel, n)
                        except Exception:
                            pass  # text rows remain available when table detection cannot run
        except Exception:
            warnings.append(f"Could not inspect schedule/detail sheet {rel}; linked specifications may be unknown.")
    return rows, warnings


def _text(e):
    return e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text


def link_specification(mark: str | None, schedule: list[ScheduleRow]):
    by_mark = defaultdict(list)
    for row in schedule:
        by_mark[row.mark].append(row)
    values = defaultdict(list)
    refs, warnings, visited, unresolved = [], [], set(), False

    def visit(key):
        nonlocal unresolved
        if key in visited:
            return
        visited.add(key)
        hits = by_mark.get(key, [])
        if not hits:
            unresolved = True
            warnings.append(f"No schedule/detail entry for {key}.")
        for row in hits:
            refs.append(row.reference)
            for field, value in row.values.items():
                if field != "detail" and value is not None:
                    values[field].append(value)
            detail = row.values.get("detail")
            if detail:
                visit(re.sub(r"^detail\s+", "", detail.strip(), flags=re.I).casefold())

    if mark:
        visit(mark.casefold())
    else:
        warnings.append("Slab mark is absent or ambiguous; specification is unknown.")
    result = {}
    for field, candidates in values.items():
        unique = {specification_key(str(v)): v for v in candidates}
        if len(unique) == 1:
            result[field] = next(iter(unique.values()))
        else:
            warnings.append(f"Conflicting {field} entries for slab mark {mark}; {field} is unknown.")
    if unresolved:
        # An unresolved linked detail may qualify a schedule's reinforcement (e.g. extra top bars).
        result.pop("reinforcement", None)
    return result, refs, warnings


def measure(path: Path, root: Path, normalizer=None):
    import ezdxf
    from ezdxf import units
    from ezdxf.path import make_path
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union

    doc = ezdxf.readfile(path)
    if not doc.units:
        raise CannotVerify("Slab polygons need explicit DXF drawing units ($INSUNITS).")
    scale = units.conversion_factor(doc.units, units.M)
    outlines, holes, marks = [], [], []
    for e in doc.modelspace():
        layer = e.dxf.layer.upper()
        if layer in ("SLAB_OUTLINE", "SLAB_OPENING"):
            if e.dxftype() not in ("LWPOLYLINE", "POLYLINE") or not e.is_closed:
                raise CannotVerify("Every slab outline/opening must be a closed polyline.")
            points = [(v.x, v.y) for v in make_path(e).flattening(distance=0.001 / scale)]
            polygon = Polygon(points)
            if not polygon.is_valid or polygon.area <= 0:
                raise CannotVerify("Invalid slab outline/opening; area cannot be verified.")
            (outlines if layer == "SLAB_OUTLINE" else holes).append((e.dxf.handle, polygon))
        elif layer == "SLAB_MARK" and e.dxftype() in ("TEXT", "MTEXT"):
            text = _text(e).strip()
            marks.append((text, Point(e.dxf.insert.x, e.dxf.insert.y)))
    if not outlines:
        raise CannotVerify("No SLAB_OUTLINE geometry. Slab areas require scaled, marked slab zones; room polygons are not slab geometry.")
    cutouts = defaultdict(list)
    for _, hole in holes:
        owners = [handle for handle, polygon in outlines if polygon.covers(hole)]
        if len(owners) != 1:
            raise CannotVerify("A slab opening has no unique enclosing zone.")
        cutouts[owners[0]].append(hole)
    zones = [(handle, polygon.difference(unary_union(cutouts[handle]))) for handle, polygon in outlines]
    for i, (_, polygon) in enumerate(zones):
        if polygon.is_empty or polygon.geom_type != "Polygon":
            raise CannotVerify("Slab openings leave an empty or disconnected zone.")
        if any(polygon.intersection(other).area * scale ** 2 > 1e-8 for _, other in zones[:i]):
            raise CannotVerify("Slab zones overlap; area cannot be summed without double counting.")
    schedule, sheet_warnings = load_schedules(path, root)
    rows, evidence = [], []
    rel = path.relative_to(root).as_posix()
    for handle, polygon in zones:
        hits = {text for text, point in marks if polygon.covers(point)}
        mark = next(iter(hits)) if len(hits) == 1 else None
        spec, refs, warnings = link_specification(mark, schedule)
        value = polygon.area * scale ** 2
        indices = []
        if normalizer:
            def ring(coords):
                # Unregistered coordinates are never used as image evidence.
                pts = [normalizer(x, y) for x, y in coords]
                if any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in pts):
                    raise CannotVerify("Slab evidence falls outside the registered sheet.")
                return pts
            indices = [len(evidence)]
            evidence.append(Evidence(shape=PolygonEvidence(points=ring(polygon.exterior.coords),
                holes=[ring(r.coords) for r in polygon.interiors]), label=mark or "Slab zone",
                value=value, source=Source.geometry_dxf))
        rows.append(SlabArea(id=f"{rel}#{handle}", mark=mark, slab_type=spec.get("type"),
            value=value, method="geometry", thickness_mm=spec.get("thickness"),
            reinforcement=spec.get("reinforcement"), references=[
                SpecificationReference(path=rel, label=f"SLAB_OUTLINE #{handle}"), *refs],
            warnings=warnings + sheet_warnings, evidence_indices=indices))
    return fsum(row.value for row in rows), rows, evidence
