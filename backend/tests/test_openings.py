"""Door/window inventory: physical-occurrence counting, type marks, levels and numbered rows."""
import ezdxf
import pytest

from app.dxf import CannotVerify, Query as DxfQuery, parse_dxf
from app.openings import dxf_inventory, ifc_inventory
from app.query.parser import parse
from app.query.schema import Query


def rectangle(space, layer, x, y, w, h):
    space.add_lwpolyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True, dxfattribs={"layer": layer})


def leaf(space, hinge, latch, open_dir):
    """Swiss door leaf: open rectangle at the hinge, closed-position line, swing arc."""
    (hx, hy), (lx, ly) = hinge, latch
    w = abs(lx - hx)
    ox = 0.05 if lx > hx else -0.05
    rectangle(space, "DOOR", min(hx, hx + ox), hy, abs(ox), w * open_dir)
    space.add_lwpolyline([hinge, latch], dxfattribs={"layer": "DOOR"})
    space.add_arc(hinge, w, 0, 90, dxfattribs={"layer": "DOOR"})


@pytest.fixture
def plan(tmp_path):
    doc = ezdxf.new()
    doc.units = 6
    for layer in ("ROOM_OUTLINE", "UNIT_OUTLINE", "ROOM_TEXT", "WINDOW", "DOOR", "FIXTURE", "ANNOTATION"):
        doc.layers.new(layer)
    s = doc.modelspace()
    s.add_text("Source: Swiss Dwellings, CC BY 4.0", dxfattribs={"layer": "ANNOTATION"})
    for x, number, label in [(0, "1.01", "Zimmer"), (4.2, "1.02", "Korridor")]:
        rectangle(s, "ROOM_OUTLINE", x, 0, 4, 4)
        s.add_text(label, dxfattribs={"layer": "ROOM_TEXT", "insert": (x + 2, 3), "height": .18})
        s.add_text(number, dxfattribs={"layer": "ROOM_TEXT", "insert": (x + 2, 2), "height": .18})
    # Single door in the wall between the rooms, drawn twice (export duplicate).
    for _ in range(2):
        rectangle(s, "DOOR", 4.2, 1.0, 0.05, 0.8)
        s.add_lwpolyline([(4.2, 1.0), (4.0, 1.0)], dxfattribs={"layer": "DOOR"})
        s.add_arc((4.2, 1.0), 0.8, 0, 90, dxfattribs={"layer": "DOOR"})
    # Double door on the bottom wall of Zimmer: two leaves whose latches meet at x=2.
    leaf(s, (1.2, 0.0), (2.0, 0.0), 1)
    leaf(s, (2.8, 0.0), (2.0, 0.0), 1)
    rectangle(s, "WINDOW", 0.5, 3.9, 1.5, .2)
    rectangle(s, "WINDOW", 5.0, 3.9, 1.5, .2)
    path = tmp_path / "floor.dxf"
    doc.saveas(path)
    return parse_dxf(path)


def test_symbols_assemblies_and_leaves(plan):
    assert plan.query(DxfQuery("count", "door")).value == 4  # as drawn: duplicate + two leaves
    assert plan.query(DxfQuery("count", "door", count_basis="assemblies")).value == 2
    assert plan.query(DxfQuery("count", "door", count_basis="leaves")).value == 3
    assert plan.query(DxfQuery("count", "window", count_basis="assemblies")).value == 2


def test_inventory_rows_are_numbered_and_located(plan):
    r = plan.query(DxfQuery("count", "door", count_basis="assemblies"))
    rows, evidence, _ = dxf_inventory(plan, r.item_ids, lambda x, y: (x / 10, 1 - y / 10))
    assert [o.number for o in rows] == [1, 2]
    double = next(o for o in rows if o.leaves == 2)
    single = next(o for o in rows if o.leaves == 1)
    assert double.width_m == pytest.approx(1.6) and double.location == ["1.01 Zimmer"]
    assert set(single.location) == {"1.01 Zimmer", "1.02 Korridor"} and len(single.duplicates) == 1
    assert [o.evidence_index for o in rows] == [0, 1] and "#1" in evidence[0].label


def test_symbol_count_explains_duplicates(plan):
    r = plan.query(DxfQuery("count", "door"))
    rows, _, note = dxf_inventory(plan, r.item_ids, None)
    assert len(rows) == 2 and "1 of these symbols are exact duplicates" in note


def test_leaves_refused_for_windows(plan):
    with pytest.raises(CannotVerify):
        plan.query(DxfQuery("count", "window", count_basis="leaves"))


@pytest.mark.parametrize("question,expected", [
    ("Count D01 doors on Level 1",
     {"op": "count", "target": "door", "scope": "level", "level": "Level 1", "type_mark": "D01", "unit": "count"}),
    ("How many doors of type 'T30' are there on level 'EG'?",
     {"op": "count", "target": "door", "scope": "level", "level": "EG", "type_mark": "T30", "unit": "count"}),
    ("List the windows", {"op": "count", "target": "window", "unit": "count"}),
    ("Count door leaves", {"op": "count", "target": "door", "unit": "count", "count_basis": "leaves"}),
    ("How many windows are drawn on this floor plan?",
     {"op": "count", "target": "window", "unit": "count", "count_basis": "symbols"}),
])
def test_parse_opening_questions(question, expected):
    r = parse(question, use_llm=False)
    assert r.query is not None and r.query.model_dump(exclude_defaults=True) == expected


def test_type_mark_only_on_door_window_counts():
    with pytest.raises(ValueError):
        Query(op="count", target="room", type_mark="D01")


ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.api as api  # noqa: E402

from app.ifc import CannotVerify as IfcCannotVerify, Model  # noqa: E402


def _model(path):
    f = ifcopenshell.file(schema="IFC4")
    project = api.run("root.create_entity", f, ifc_class="IfcProject", name="P")
    api.run("unit.assign_unit", f, units=[api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT")])
    bldg = api.run("root.create_entity", f, ifc_class="IfcBuilding", name="B")
    api.run("aggregate.assign_object", f, products=[bldg], relating_object=project)
    storeys = {}
    for name in ("Level 1", "Level 2"):
        storeys[name] = api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name=name)
        api.run("aggregate.assign_object", f, products=[storeys[name]], relating_object=bldg)
    types = {}
    for mark, op in (("D01", "SINGLE_SWING_LEFT"), ("D02", "DOUBLE_DOOR_SINGLE_SWING")):
        t = api.run("root.create_entity", f, ifc_class="IfcDoorType", name=f"{mark}_900x2100")
        t.OperationType = op
        types[mark] = t
    for storey, mark in [("Level 1", "D01"), ("Level 1", "D01"), ("Level 1", "D02"), ("Level 2", "D01")]:
        d = api.run("root.create_entity", f, ifc_class="IfcDoor", name=mark)
        d.OverallWidth = 0.9
        api.run("spatial.assign_container", f, products=[d], relating_structure=storeys[storey])
        api.run("type.assign_type", f, related_objects=[d], relating_type=types[mark])
    f.write(str(path))
    return Model(str(path))


def test_ifc_type_mark_and_level(tmp_path):
    m = _model(tmp_path / "m.ifc")
    r = m.query(Query(op="count", target="door", scope="level", level="Level 1", type_mark="D01", unit="count"))
    assert r.value == 2 and "type D01 door" in r.explanation
    rows = ifc_inventory(r.items, "door")
    assert [o.number for o in rows] == [1, 2] and {o.level for o in rows} == {"Level 1"}
    assert all(o.type_mark == "D01_900x2100" and o.leaves == 1 and o.width_m == 0.9 for o in rows)


def test_ifc_double_door_is_one_item_two_leaves(tmp_path):
    m = _model(tmp_path / "m.ifc")
    assert m.query(Query(op="count", target="door", unit="count")).value == 4
    assert m.query(Query(op="count", target="door", unit="count", count_basis="leaves")).value == 5
    with pytest.raises(IfcCannotVerify):
        m.query(Query(op="count", target="door", unit="count", type_mark="D99"))
