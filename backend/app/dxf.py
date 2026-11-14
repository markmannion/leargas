"""Deterministic extractor for the published Swiss Dwellings DXF convention.

Coordinates remain in DXF world space (metres, y up). They are deliberately not
advertised as image evidence: aligning the rendered twins is a separate task.
No question text or gold answers are used by this module.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from functools import cached_property
from pathlib import Path
import math
import re
import unicodedata
from typing import Literal

import ezdxf
from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree
from shapely.ops import unary_union


class CannotVerify(ValueError):
    """The drawing does not supply sufficient unambiguous evidence."""


def _normal(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


AREA = re.compile(r"^(\d+(?:[.,]\d+)?)\s*m(?:²|2|\^2)$", re.I)
NUMBER = re.compile(r"^(?:U|-)?\d+\.\d+$", re.I)
UNIT = re.compile(r"^(?:App\.|Whg\.)\s*([A-Z]+)$", re.I)
COMMERCIAL = re.compile(r"^Gewerbe\s+\d+$", re.I)
OUTDOOR = {"balkon", "balcon", "balcone", "loggia", "terrasse", "terrazza",
           "terrace", "aussenraum", "espace extérieur", "spazio esterno",
           "sitzplatz", "garten", "patio", "wintergarten", "jardin d'hiver",
           "giardino d'inverno", "arkade", "arcade", "arcades", "portico", "porticato",
           "laubengang", "coursive", "ballatoio", "pergola", "vordach"}
KINDS = {"room", "unit", "window", "door", "fixture", "toilet", "washbasin",
         "bathtub", "shower", "washing_machine", "kitchen", "stairs", "unknown_fixture"}
REQUIRED_LAYERS = {"ROOM_OUTLINE", "UNIT_OUTLINE", "ROOM_TEXT", "WINDOW", "DOOR", "FIXTURE"}


@dataclass
class Item:
    id: str
    kind: str
    layer: str
    points: list[tuple[float, float]]
    component_handles: list[str] = field(default_factory=list)
    # Fixture outlines: the strokes inside, e.g. {"P48": 1, "C": 1} (P<n> = n-point polyline, C = circle).
    strokes: dict[str, int] = field(default_factory=dict)
    room_id: str | None = None
    label: str | None = None
    printed_area_m2: float | None = None
    geometric_area_m2: float | None = None
    unit_id: str | None = None
    # None means unlabelled / insufficient semantic information.
    indoor: bool | None = None
    interior_outline_ids: list[str] = field(default_factory=list)

    @cached_property
    def polygon(self) -> Polygon:
        return Polygon(self.points)


@dataclass(frozen=True)
class Query:
    operation: Literal["count", "area"]
    kind: str
    room_id: str | None = None
    label: str | None = None
    unit_id: str | None = None
    indoor_only: bool = False
    area_source: Literal["auto", "printed", "geometry"] = "auto"


@dataclass
class Result:
    value: int | float
    unit: str
    item_ids: list[str]
    explanation: str


@dataclass
class Drawing:
    path: str
    profile: str
    coordinate_system: str
    layers: dict[str, dict[str, int]]
    items: list[Item]
    warnings: list[str]
    attribution: list[str]

    def to_dict(self) -> dict:
        return asdict(self)

    def query(self, query: Query) -> Result:
        if self.profile != "swiss_dwellings":
            raise CannotVerify("Unsupported DXF layer convention; inspect the layer inventory.")
        if query.kind not in KINDS or query.operation not in {"count", "area"}:
            raise CannotVerify("Unsupported structured query.")
        if query.area_source not in {"auto", "printed", "geometry"}:
            raise CannotVerify("Unsupported area source.")
        if query.operation == "area" and query.kind != "room":
            raise CannotVerify("Net areas are sums of room areas; use kind='room'.")
        if query.kind != "room" and any((query.room_id, query.label, query.unit_id, query.indoor_only)):
            raise CannotVerify("Scoped queries currently support rooms only.")
        rooms = [i for i in self.items if i.kind == "room"]
        if query.room_id and not any(i.room_id == query.room_id for i in rooms):
            raise CannotVerify(f"Room {query.room_id!r} is absent.")
        if query.unit_id and not any(i.kind == "unit" and i.unit_id == query.unit_id for i in self.items):
            raise CannotVerify(f"Unit {query.unit_id!r} is absent or ambiguous.")
        if query.unit_id and any(w.startswith("unit labels:") for w in self.warnings):
            raise CannotVerify("Residential unit labels are ambiguous.")
        if query.unit_id and any(i.kind == "unit" and i.unit_id is None and i.label is None
                                 for i in self.items):
            raise CannotVerify("Unlabelled unit fragments could belong to the requested apartment.")
        if query.kind in {"fixture", "toilet", "washbasin", "bathtub", "shower",
                          "washing_machine", "kitchen", "stairs"} and any(
            i.kind == "unknown_fixture" and _could_be(i, query.kind) for i in self.items
        ):
            raise CannotVerify("Unclassified fixture symbols could affect this count.")
        # Incomplete room labels must not silently become zero counts or smaller sums.
        if query.kind == "room" and any(w.startswith("room labels:") for w in self.warnings):
            raise CannotVerify("Some room labels could not be associated unambiguously.")
        selected = [i for i in self.items if (i.kind == query.kind or
                    query.kind == "fixture" and i.layer == "FIXTURE")]
        if query.kind == "room":
            selected = [i for i in selected if i.room_id is not None]
        if query.kind == "unit":
            # Disconnected unit islands and commercial spaces also have outlines.
            # Residential units are identified by App./Whg. labels.
            if any(w.startswith("unit labels:") for w in self.warnings):
                raise CannotVerify("Residential unit labels are ambiguous.")
            selected = [i for i in selected if i.unit_id is not None]
        if query.room_id:
            selected = [i for i in selected if i.room_id == query.room_id]
            if query.kind == "room" and len(selected) != 1:
                raise CannotVerify("Room identifier is ambiguous.")
        if query.label:
            selected = [i for i in selected if i.label and _normal(i.label) == _normal(query.label)]
        if query.unit_id:
            target_units = [i for i in self.items if i.kind == "unit" and i.unit_id == query.unit_id]
            if any(i.unit_id is None and any(
                i.polygon.intersection(u.polygon).area / i.polygon.area > 0.1 for u in target_units
            ) for i in selected):
                raise CannotVerify("Room-to-unit membership is incomplete.")
            selected = [i for i in selected if i.unit_id == query.unit_id]
        if query.indoor_only:
            if any(i.indoor is None for i in selected):
                raise CannotVerify("Indoor/outdoor classification is incomplete.")
            selected = [i for i in selected if i.indoor]
        if query.operation == "count":
            return Result(len(selected), "count", [i.id for i in selected],
                          f"Counted {len(selected)} {query.kind} objects from semantic DXF layers.")
        values = [(i.geometric_area_m2 if query.area_source == "geometry" else
                   i.printed_area_m2 if i.printed_area_m2 is not None or query.area_source == "printed"
                   else i.geometric_area_m2) for i in selected]
        if not values or any(v is None for v in values):
            raise CannotVerify("A selected room has no printed m² label, or no rooms matched.")
        basis = ("printed room m² labels" if query.area_source != "geometry" and
                 all(i.printed_area_m2 is not None for i in selected) else
                 "room areas in metres (printed m² where available, otherwise CAD polygons)"
                 if query.area_source == "auto" else "CAD room polygon areas in metres")
        return Result(round(math.fsum(values), 2), "m2", [i.id for i in selected], f"Summed {basis}.")


# The stroke each recognised symbol is drawn around: tub bowl, WC/basin oval, shower tray.
# An unclassified outline only blocks a count when it contains that stroke (it may be several
# fixtures merged into one outline). Unresolved strokes outside any outline block everything.
HALLMARK = {"bathtub": "P69", "toilet": "P48", "washbasin": "P48", "shower": "P5"}


def _could_be(item: Item, kind: str) -> bool:
    if item.id == "unresolved-fixtures" or kind not in HALLMARK:
        return True
    if kind in ("bathtub", "shower") and item.strokes == {"C": 1}:
        return True  # a bare drain: some exports draw small tubs / trays this way
    return item.strokes.get(HALLMARK[kind], 0) > 0


def _points(entity) -> list[tuple[float, float]]:
    # Swiss exports are straight, planar polylines. Reject curves instead of
    # silently replacing them with straight chords.
    if entity.dxftype() != "LWPOLYLINE" or entity.has_arc:
        return []
    if not entity.dxf.extrusion.isclose((0, 0, 1)) or entity.dxf.elevation != 0:
        return []
    return [(float(x), float(y)) for x, y in entity.get_points("xy")]


def _polygon(entity, explicit_close: bool = False) -> Polygon | None:
    pts = _points(entity)
    if len(pts) < 3 or not (entity.closed or explicit_close and math.dist(pts[0], pts[-1]) < 1e-7):
        return None
    poly = Polygon(pts)
    return poly if poly.is_valid and poly.area > 1e-10 else None


def _item(entity, kind: str, poly: Polygon) -> Item:
    return Item(entity.dxf.handle, kind, entity.dxf.layer,
                [(float(x), float(y)) for x, y in poly.exterior.coords],
                [entity.dxf.handle], geometric_area_m2=float(poly.area))


def _owner(point: Point, items: list[Item]) -> Item | None:
    owners = [i for i in items if i.polygon.covers(point)]
    # Stair outlines can enclose lift rooms. The innermost outline owns text.
    return min(owners, key=lambda i: i.polygon.area) if owners else None


def parse_dxf(path: str | Path) -> Drawing:
    """Read one DXF. Unknown conventions expose inventory but cannot answer queries."""
    path = Path(path)
    doc = ezdxf.readfile(path)
    entities = list(doc.modelspace())
    inventory = defaultdict(Counter)
    by_layer = defaultdict(list)
    for entity in entities:
        inventory[entity.dxf.layer][entity.dxftype()] += 1
        by_layer[entity.dxf.layer].append(entity)
    annotations = [e.plain_text() for e in entities if e.dxftype() in {"TEXT", "MTEXT"}
                   and e.dxf.layer == "ANNOTATION"]
    # The fixture motifs and object conventions are dataset-specific, so an
    # arbitrary CAD file with a WINDOW layer must not receive verified counts.
    supported = (REQUIRED_LAYERS.issubset({l.dxf.name for l in doc.layers})
                 and doc.units == 6 and any("Swiss Dwellings" in t for t in annotations))
    drawing = Drawing(str(path), "swiss_dwellings" if supported else "unsupported",
                      "DXF WCS, metres, x right / y up" if doc.units == 6 else "DXF WCS, native units",
                      {k: dict(v) for k, v in sorted(inventory.items())}, [], [],
                      [t for t in annotations if "Source:" in t])
    if not supported:
        drawing.warnings.append("Unsupported profile: requires Swiss Dwellings layers, attribution and metre units.")
        return drawing
    rooms, units = [], []
    for layer, kind, target in [("ROOM_OUTLINE", "room", rooms), ("UNIT_OUTLINE", "unit", units)]:
        for entity in by_layer[layer]:
            poly = _polygon(entity, explicit_close=True)
            if poly is not None:
                target.append(_item(entity, kind, poly))
            elif entity.dxftype() != "LWPOLYLINE" or len(_points(entity)) != 2:
                raise CannotVerify(f"Unsupported {layer} geometry: {entity.dxf.handle}.")
    drawing.items.extend(rooms + units)
    # DXFs retain only each room's exterior ring. Smaller enclosed room/shaft
    # outlines are islands, not additional net floor area in their enclosure.
    for room in rooms:
        outer = room.polygon.buffer(1e-8)
        inner = [other for other in rooms if other is not room
                 and other.polygon.area < room.polygon.area
                 and outer.covers(other.polygon)]
        if inner:
            room.interior_outline_ids = [other.id for other in inner]
            room.geometric_area_m2 = room.polygon.difference(unary_union([i.polygon for i in inner])).area
    texts = defaultdict(list)
    for entity in by_layer["ROOM_TEXT"]:
        if entity.dxftype() not in {"TEXT", "MTEXT"}:
            raise CannotVerify("Unsupported room text entity.")
        text = entity.plain_text().strip()
        pos = entity.dxf.insert
        if entity.dxftype() == "TEXT" and (entity.dxf.halign or entity.dxf.valign):
            pos = entity.dxf.align_point
        point = Point(pos.x, pos.y)
        if COMMERCIAL.fullmatch(text):
            continue
        unit_match = UNIT.fullmatch(text)
        if unit_match:
            owner = _owner(point, units)
            if owner is not None and owner.unit_id is None:
                owner.unit_id = unit_match[1].upper()
                owner.label = text
                owner.component_handles.append(entity.dxf.handle)
            else:
                drawing.warnings.append(f"unit labels: ambiguous label {text}.")
            continue
        owner = _owner(point, rooms)
        if owner is None:
            drawing.warnings.append(f"room labels: unassigned text {text!r}.")
        else:
            texts[owner.id].append((text, entity.dxf.handle))
    for room in rooms:
        ts = texts[room.id]
        numbers = [t for t, _ in ts if NUMBER.fullmatch(t)]
        areas = [float(AREA.fullmatch(t)[1].replace(",", ".")) for t, _ in ts if AREA.fullmatch(t)]
        labels = [t for t, _ in ts if not NUMBER.fullmatch(t) and not AREA.fullmatch(t)]
        if len(numbers) > 1 or len(areas) > 1 or len(labels) > 1:
            drawing.warnings.append(f"room labels: ambiguous texts in outline {room.id}.")
            continue
        room.room_id = numbers[0] if numbers else None
        room.printed_area_m2 = areas[0] if areas else None
        room.label = labels[0] if labels else None
        room.indoor = _normal(room.label) not in OUTDOOR if room.label else None
        room.component_handles += [h for _, h in ts]
        overlaps = sorted([(room.polygon.intersection(u.polygon).area / room.polygon.area, u)
                           for u in units], key=lambda pair: pair[0], reverse=True)
        if overlaps and overlaps[0][0] > 0.5 and (len(overlaps) == 1 or overlaps[1][0] < 0.1):
            room.unit_id = overlaps[0][1].unit_id
    _enclosed_rooms_indoor(rooms)
    for layer, kind in [("WINDOW", "window"), ("DOOR", "door")]:
        for entity in by_layer[layer]:
            poly = _polygon(entity, explicit_close=True)
            if poly is not None:
                drawing.items.append(_item(entity, kind, poly))
            elif entity.dxftype() == "LWPOLYLINE" and len(_points(entity)) == 2:
                pass  # glazing lines and door leaves
            elif layer == "DOOR" and entity.dxftype() == "ARC":
                pass  # swing arcs are not extra doors
            else:
                raise CannotVerify(f"Unsupported {layer} symbol: {entity.dxf.handle}.")
    _fixtures(by_layer["FIXTURE"], drawing)
    return drawing


ENCLOSED = 0.97  # share of perimeter that must border other rooms (within a wall's width)
WALL = 0.6


def _enclosed_rooms_indoor(rooms: list[Item]) -> None:
    """Numbered rooms without a name are indoor when other rooms surround them on (nearly) every side.

    Balconies, loggias and terraces sit on the facade, so much of their outline borders no room.
    Anything less enclosed stays unclassified and indoor-only queries keep refusing.
    """
    todo = [r for r in rooms if r.room_id and r.indoor is None]
    if not todo:
        return
    for r in todo:
        others = [o.polygon for o in rooms if o is not r
                  and not r.polygon.buffer(1e-6).covers(o.polygon)
                  and not o.polygon.buffer(1e-6).covers(r.polygon)]
        if not others:
            continue
        ring = r.polygon.exterior
        near = ring.intersection(unary_union(others).buffer(WALL)).length
        if near / ring.length >= ENCLOSED:
            r.indoor = True


def _fixtures(entities: list, drawing: Drawing) -> None:
    outlines = [(e, _polygon(e)) for e in entities]
    outlines = [(e, p) for e, p in outlines if p is not None]
    records = []
    for entity in entities:
        pts = _points(entity)
        shape = (LineString(pts) if len(pts) >= 2 else
                 Point(entity.dxf.center.x, entity.dxf.center.y)
                 if entity.dxftype() == "CIRCLE" else None)
        if shape is not None:
            records.append((entity, shape))
    tree = STRtree([shape for _, shape in records])
    consumed = set()
    for entity, poly in outlines:
        components = [records[index][0] for index in tree.query(poly.buffer(1e-7), predicate="covers")
                      if records[index][0] is not entity]
        polylines = [c for c in components if c.dxftype() == "LWPOLYLINE"]
        circles = [c for c in components if c.dxftype() == "CIRCLE"]
        long_paths = [c for c in polylines if len(c) > 5]
        lines = [c for c in polylines if len(c) == 2]
        # Swiss symbol construction: tub = rounded bowl + drain; WC = oval +
        # cistern line; basin = oval + drain; washing machine = corner diagonals.
        kind = "unknown_fixture"
        if len(long_paths) == 1 and len(long_paths[0]) == 69 and len(circles) == 1 and not lines:
            kind = "bathtub"
        elif len(long_paths) == 1 and len(long_paths[0]) == 48:
            if len(lines) == 1 and not circles:
                kind = "toilet"
            elif len(circles) == 1 and not lines:
                kind = "washbasin"
        elif len(polylines) == 1 and len(polylines[0]) == 5 and len(circles) == 1:
            tray = _polygon(polylines[0], explicit_close=True)
            if tray is not None and tray.contains(Point(circles[0].dxf.center.x, circles[0].dxf.center.y)):
                kind = "shower"
        elif len(lines) == 2 and not long_paths and not circles:
            boundary = poly.boundary
            if all(all(boundary.distance(Point(p)) < 1e-7 for p in _points(c)) for c in lines):
                kind = "washing_machine"
        elif len(circles) == 4 and not polylines:
            kind = "kitchen"
        elif lines and not long_paths and not circles and all(
            abs(LineString(_points(c)).length - LineString(_points(lines[0])).length) < 1e-7 for c in lines
        ):
            kind = "stairs"
        item = _item(entity, kind, poly)
        item.component_handles += [c.dxf.handle for c in components]
        item.strokes = dict(Counter("C" if c.dxftype() == "CIRCLE" else f"P{len(c)}" for c in components))
        drawing.items.append(item)
        consumed.update(item.component_handles)
    leftovers = [e.dxf.handle for e in entities if e.dxf.handle not in consumed]
    if leftovers:
        # Keep unresolved symbols visible and prevent incomplete fixture counts.
        drawing.items.append(Item("unresolved-fixtures", "unknown_fixture", "FIXTURE", [], leftovers))
        drawing.warnings.append(f"Unassigned fixture components: {', '.join(leftovers)}")


def resolve_twin(path: str | Path, dataset_root: str | Path) -> Path:
    """Resolve a dataset-relative PDF/PNG/etc. path to its same-stem DXF safely."""
    root = Path(dataset_root).resolve()
    candidate = (root / Path(path).with_suffix(".dxf")).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Drawing path must remain inside dataset_root.")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate
