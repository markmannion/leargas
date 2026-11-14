"""Net geometry cases that cannot be verified from printed room m²."""
import pytest
from shapely.geometry import Polygon

from app.dxf import Drawing, Item, Query
from app.floor_areas import measure_rooms
from app.region import CannotScope
from app.schema import Region


def room(points, id="room", number="1.01", printed=100):
    return Item(id=id, kind="room", layer="ROOM_OUTLINE", points=points,
                room_id=number, label="Kitchen", printed_area_m2=printed,
                geometric_area_m2=Polygon(points).area)


def drawing(*items):
    return Drawing("plan.dxf", "swiss_dwellings", "metres", {}, list(items), [], [])


def norm(x, y):
    return x / 10, 1 - y / 10


def measure(d, bbox, mode="intersection"):
    q = Query("area", "room", area_source="geometry" if mode == "intersection" else "auto")
    return measure_rooms(d, q, d.query(q), norm, Region(bbox=bbox), mode)


def test_exact_area_excludes_holes_in_quantity_and_highlight():
    outer = room([(0, 0), (4, 0), (4, 4), (0, 4)])
    shaft = room([(1, 1), (3, 1), (3, 3), (1, 3)], id="shaft", number=None)
    outer.interior_outline_ids = [shaft.id]
    outer.geometric_area_m2 = 12
    value, rows, evidence, _ = measure(drawing(outer, shaft), (0, .6, .4, 1))
    assert value == 12 and rows[0].value == 12 and rows[0].complete
    assert len(evidence[0].shape.holes) == 1
    shape = evidence[0].shape
    assert Polygon(shape.points, shape.holes).area * 100 == pytest.approx(value)
    half, rows, evidence, _ = measure(drawing(outer, shaft), (0, .6, .2, 1))
    assert half == 6 and not rows[0].complete
    assert sum(Polygon(e.shape.points, e.shape.holes).area for e in evidence) * 100 == pytest.approx(half)


def test_concave_room_can_have_two_separate_selected_portions():
    # A U shape; the upper strip intersects its two legs.
    item = room([(0, 0), (4, 0), (4, 4), (3, 4), (3, 1), (1, 1), (1, 4), (0, 4)])
    value, rows, evidence, _ = measure(drawing(item), (0, .6, .4, .8))
    assert value == 4 and len(rows) == 1 and not rows[0].complete
    assert rows[0].evidence_indices == [0, 1]
    assert len(evidence) == 2 and sum(e.value for e in evidence) == pytest.approx(value)


def test_region_only_over_void_measures_zero():
    outer = room([(0, 0), (4, 0), (4, 4), (0, 4)])
    shaft = room([(1, 1), (3, 1), (3, 3), (1, 3)], id="shaft", number=None)
    outer.interior_outline_ids = [shaft.id]
    value, rows, evidence, _ = measure(drawing(outer, shaft), (.11, .71, .29, .89))
    assert value == 0 and rows == [] and evidence == []


def test_region_touching_only_a_room_edge_measures_zero():
    item = room([(0, 0), (4, 0), (4, 4), (0, 4)])
    # Selection merely touches a room edge: it must not count a room.
    value, rows, evidence, _ = measure(drawing(item), (.4, .6, .5, 1))
    assert value == 0 and rows == [] and evidence == []


def test_whole_room_printed_and_geometry_methods_can_be_mixed():
    first = room([(0, 0), (2, 0), (2, 2), (0, 2)], printed=3.5)
    second = room([(2, 0), (4, 0), (4, 2), (2, 2)], id="second", number="1.02", printed=None)
    value, rows, _, _ = measure(drawing(first, second), (0, .8, .4, 1), mode="whole_rooms")
    assert value == 7.5 and [r.method for r in rows] == ["printed", "geometry"]


def test_overlapping_floor_outlines_refuse_double_count():
    first = room([(0, 0), (3, 0), (3, 3), (0, 3)])
    second = room([(2, 0), (4, 0), (4, 3), (2, 3)], id="second", number="1.02")
    with pytest.raises(CannotScope, match="double counting"):
        measure(drawing(first, second), (0, .5, .5, 1))
