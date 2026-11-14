"""Synthetic CAD fixtures exercise object grouping and conservative failure paths."""
import math

import ezdxf
import pytest

from app.dxf import CannotVerify, Query, parse_dxf, resolve_twin
from dxf_engine import main


def rectangle(space, layer, x, y, w, h, *, close=True):
    points = [(x, y), (x+w, y), (x+w, y+h), (x, y+h)]
    if not close:
        points += points[:1]
    return space.add_lwpolyline(points, close=close, dxfattribs={"layer": layer})


@pytest.fixture
def cad(tmp_path):
    doc = ezdxf.new()
    doc.units = 6
    for layer in ("ROOM_OUTLINE", "UNIT_OUTLINE", "ROOM_TEXT", "WINDOW", "DOOR", "FIXTURE", "ANNOTATION"):
        doc.layers.new(layer)
    space = doc.modelspace()
    space.add_text("Source: Swiss Dwellings, CC BY 4.0", dxfattribs={"layer": "ANNOTATION"})
    for x, number, label, area in [(0, "1.01", "Zimmer", "12.34 m²"), (4, "1.02", "Balkon", "3,21 m²")]:
        rectangle(space, "ROOM_OUTLINE", x, 0, 4, 4)
        for y, text in [(3, label), (2, number), (1, area)]:
            space.add_text(text, dxfattribs={"layer": "ROOM_TEXT", "insert": (x+2, y), "height": .18})
    rectangle(space, "UNIT_OUTLINE", -.1, -.1, 8.2, 4.2, close=False)
    space.add_text("Whg. A", dxfattribs={"layer": "ROOM_TEXT", "insert": (1, 1)})
    # One window with two glazing lines, one door with leaf and arc.
    rectangle(space, "WINDOW", 0, 0, 2, .3)
    for y in (.1, .2):
        space.add_lwpolyline([(0, y), (2, y)], dxfattribs={"layer": "WINDOW"})
    rectangle(space, "DOOR", 0, 0, 1, .2, close=False)
    space.add_lwpolyline([(0, 0), (0, 1)], dxfattribs={"layer": "DOOR"})
    space.add_arc((0, 0), 1, 0, 90, dxfattribs={"layer": "DOOR"})
    path = tmp_path / "floor.dxf"
    return doc, space, path


def save_parse(cad):
    doc, _, path = cad
    doc.saveas(path)
    return parse_dxf(path)


def test_objects_are_counted_once_and_areas_use_printed_labels(cad):
    drawing = save_parse(cad)
    assert drawing.query(Query("count", "window")).value == 1
    assert drawing.query(Query("count", "door")).value == 1
    assert drawing.query(Query("count", "unit")).value == 1
    assert drawing.query(Query("count", "room", label="zimmer")).value == 1
    assert drawing.query(Query("area", "room", room_id="1.01")).value == 12.34
    assert drawing.query(Query("area", "room", unit_id="A", indoor_only=True)).value == 12.34
    assert drawing.query(Query("area", "room")).value == 15.55
    assert drawing.query(Query("count", "shower")).value == 0
    assert drawing.attribution


def test_inner_room_owns_its_labels(cad):
    _, space, _ = cad
    rectangle(space, "ROOM_OUTLINE", 0, 0, 1, 1)
    for y, text in [(.8, "Lift"), (.5, "1.03"), (.2, "0.72 m²")]:
        space.add_text(text, dxfattribs={"layer": "ROOM_TEXT", "insert": (.5, y)})
    drawing = save_parse(cad)
    assert drawing.query(Query("area", "room", room_id="1.03")).value == .72
    assert drawing.query(Query("area", "room", room_id="1.01")).value == 12.34
    assert drawing.query(Query("area", "room", room_id="1.01", area_source="geometry")).value == 15


def test_unlabelled_unit_islands_and_commercial_spaces_are_not_apartments(cad):
    _, space, _ = cad
    rectangle(space, "UNIT_OUTLINE", 20, 20, 2, 2)
    space.add_text("Gewerbe 1", dxfattribs={"layer": "ROOM_TEXT", "insert": (21, 21)})
    drawing = save_parse(cad)
    assert drawing.query(Query("count", "unit")).value == 1
    assert drawing.query(Query("count", "room", label="Zimmer")).value == 1
    # The fragment holds no numbered room, so apartment A's sum is unaffected.
    assert drawing.query(Query("area", "room", unit_id="A", indoor_only=True)).value == 12.34


def test_unit_fragment_holding_a_numbered_room_blocks_apartment_area(cad):
    _, space, _ = cad
    rectangle(space, "UNIT_OUTLINE", 20, 20, 3, 3)
    rectangle(space, "ROOM_OUTLINE", 20.5, 20.5, 2, 2)
    for y, text in [(22, "Zimmer"), (21.5, "1.05"), (21, "4.00 m²")]:
        space.add_text(text, dxfattribs={"layer": "ROOM_TEXT", "insert": (21.5, y)})
    drawing = save_parse(cad)
    with pytest.raises(CannotVerify, match="fragments"):
        drawing.query(Query("area", "room", unit_id="A", indoor_only=True))


def test_communal_room_does_not_block_apartment_area(cad):
    _, space, _ = cad
    rectangle(space, "ROOM_OUTLINE", 20, 20, 2, 2)
    for y, text in [(21.5, "Treppenhaus"), (21, "1.03"), (20.5, "4.00 m²")]:
        space.add_text(text, dxfattribs={"layer": "ROOM_TEXT", "insert": (21, y)})
    drawing = save_parse(cad)
    assert drawing.query(Query("area", "room", unit_id="A", indoor_only=True)).value == 12.34


def test_duplicate_room_labels_refuse_instead_of_undercounting(cad):
    _, space, _ = cad
    space.add_text("1.99", dxfattribs={"layer": "ROOM_TEXT", "insert": (1, 2)})
    with pytest.raises(CannotVerify, match="unambiguously"):
        save_parse(cad).query(Query("count", "room", label="Zimmer"))


def test_missing_printed_area_has_explicit_geometry_fallback(cad):
    _, space, _ = cad
    for entity in list(space.query('TEXT[layer=="ROOM_TEXT"]')):
        if entity.dxf.text == "12.34 m²":
            space.delete_entity(entity)
    drawing = save_parse(cad)
    with pytest.raises(CannotVerify, match="no printed"):
        drawing.query(Query("area", "room", room_id="1.01", area_source="printed"))
    assert drawing.query(Query("area", "room", room_id="1.01")).value == 16


def test_swiss_outdoor_and_conservatory_labels_are_excluded_from_net_area(cad):
    _, space, _ = cad
    balcony = next(e for e in space.query('TEXT[layer=="ROOM_TEXT"]') if e.dxf.text == "Balkon")
    for label in ("Sitzplatz", "Garten", "Patio", "Wintergarten", "Jardin d'hiver", "Giardino d'inverno"):
        balcony.dxf.text = label
        assert save_parse(cad).query(Query("area", "room", unit_id="A", indoor_only=True)).value == 12.34


def test_unknown_profile_and_queries_refuse(cad):
    doc, _, _ = cad
    doc.units = 4  # millimetres: never assume metres
    drawing = save_parse(cad)
    assert drawing.profile == "unsupported"
    with pytest.raises(CannotVerify):
        drawing.query(Query("count", "window"))


def test_missing_filters_and_unsupported_operation_refuse(cad):
    drawing = save_parse(cad)
    for query in [Query("count", "beam"), Query("area", "window"),
                  Query("count", "room", room_id="9.99"), Query("count", "room", unit_id="Z"),
                  Query("count", "window", room_id="1.01")]:
        with pytest.raises(CannotVerify):
            drawing.query(query)


def test_rotated_fixture_components_are_grouped(cad):
    _, space, _ = cad
    rect = rectangle(space, "FIXTURE", 10, 10, .5, .8)
    # WC: oval bowl and cistern line, independent of world-space orientation.
    oval = space.add_lwpolyline([(10.25+.2*math.cos(t*2*math.pi/47),
                                 10.4+.28*math.sin(t*2*math.pi/47)) for t in range(48)],
                               dxfattribs={"layer": "FIXTURE"})
    line = space.add_lwpolyline([(10.03, 10.7), (10.47, 10.7)], dxfattribs={"layer": "FIXTURE"})
    from ezdxf.math import Matrix44
    for e in (rect, oval, line):
        e.transform(Matrix44.z_rotate(.7))
    drawing = save_parse(cad)
    assert drawing.query(Query("count", "toilet")).value == 1
    assert drawing.query(Query("count", "fixture")).value == 1
    toilet = next(i for i in drawing.items if i.kind == "toilet")
    assert len(toilet.component_handles) == 3


def test_unknown_fixture_prevents_partial_count(cad):
    _, space, _ = cad
    rectangle(space, "FIXTURE", 10, 10, .4, .4)
    drawing = save_parse(cad)
    for kind in ("fixture", "washing_machine"):
        with pytest.raises(CannotVerify, match="Unclassified"):
            drawing.query(Query("count", kind))
    # An empty outline has no WC oval, so it can't hide a toilet.
    assert drawing.query(Query("count", "toilet")).value == 0


def test_unknown_outline_with_hallmark_blocks_that_kind(cad):
    _, space, _ = cad
    rectangle(space, "FIXTURE", 10, 10, 1, 1)
    oval = [(10.5 + .3 * math.cos(2 * math.pi * k / 47), 10.5 + .2 * math.sin(2 * math.pi * k / 47)) for k in range(48)]
    space.add_lwpolyline(oval, dxfattribs={"layer": "FIXTURE"})  # 48-point WC/basin oval...
    for y in (10.1, 10.2, 10.3):  # ...merged with strokes no known symbol has
        space.add_lwpolyline([(10.1, y), (10.9, y)], dxfattribs={"layer": "FIXTURE"})
    drawing = save_parse(cad)
    for kind in ("toilet", "washbasin"):
        with pytest.raises(CannotVerify, match="Unclassified"):
            drawing.query(Query("count", kind))
    assert drawing.query(Query("count", "bathtub")).value == 0


def test_shower_tray_and_washing_machine_are_distinct(cad):
    _, space, _ = cad
    rectangle(space, "FIXTURE", 10, 10, 1, 1)
    rectangle(space, "FIXTURE", 10.05, 10.05, .9, .9, close=False)
    space.add_circle((10.5, 10.5), .025, dxfattribs={"layer": "FIXTURE"})
    rectangle(space, "FIXTURE", 12, 10, .6, .6)
    for a, b in [((12, 10), (12.6, 10.6)), ((12.6, 10), (12, 10.6))]:
        space.add_lwpolyline([a, b], dxfattribs={"layer": "FIXTURE"})
    drawing = save_parse(cad)
    assert drawing.query(Query("count", "shower")).value == 1
    assert drawing.query(Query("count", "washing_machine")).value == 1


def test_curved_semantic_outline_is_not_silently_linearized(cad):
    _, space, _ = cad
    space.add_lwpolyline([(10, 10, 1), (11, 10, 0), (11, 11, 0)], format="xyb",
                         close=True, dxfattribs={"layer": "WINDOW"})
    with pytest.raises(CannotVerify, match="WINDOW"):
        save_parse(cad)


def test_twin_resolution_rejects_escape_and_missing_paths(cad):
    save_parse(cad)
    path = cad[2]
    assert resolve_twin("floor.pdf", path.parent) == path
    with pytest.raises(ValueError):
        resolve_twin("../floor.pdf", path.parent)
    with pytest.raises(FileNotFoundError):
        resolve_twin("missing.png", path.parent)


def test_batch_reports_broken_files_and_checks_inventory(cad, capsys):
    save_parse(cad)
    root = cad[2].parent
    (root / "broken.dxf").write_text("not a DXF")
    output, report = root / "out.jsonl", root / "report.json"
    args = ["batch", str(root), "--output", str(output), "--report", str(report)]
    assert main(args + ["--expected-count", "1040"]) == 2
    assert not output.exists()
    assert main(args + ["--expected-count", "2"]) == 1
    import json
    result = json.loads(report.read_text())
    assert result["parsed"] == result["supported"] == 1
    assert len(result["errors"]) == 1
    assert main(["parse", str(root / "broken.dxf")]) == 1


def test_unlabelled_numbered_room_on_the_facade_stays_unclassified(cad):
    _, space, _ = cad
    rectangle(space, "ROOM_OUTLINE", 8, 0, 1.5, 4)  # borders only the balcony, open on three sides
    space.add_text("1.03", dxfattribs={"layer": "ROOM_TEXT", "insert": (8.7, 2)})
    drawing = save_parse(cad)
    room = next(i for i in drawing.items if i.room_id == "1.03")
    assert room.indoor is None
    with pytest.raises(CannotVerify, match="Indoor/outdoor"):
        drawing.query(Query("area", "room", indoor_only=True))


def test_enclosed_unlabelled_numbered_room_is_indoor(cad):
    _, space, _ = cad
    # a store right of the balcony, with rooms 20 cm away on its other three sides
    rectangle(space, "ROOM_OUTLINE", 8.2, .5, 1, 3)
    space.add_text("1.03", dxfattribs={"layer": "ROOM_TEXT", "insert": (8.7, 2)})
    rectangle(space, "ROOM_OUTLINE", 9.4, -1, 3, 6)
    rectangle(space, "ROOM_OUTLINE", 8, 3.7, 1.4, 1)
    rectangle(space, "ROOM_OUTLINE", 8, -.7, 1.4, 1)
    drawing = save_parse(cad)
    room = next(i for i in drawing.items if i.room_id == "1.03")
    assert room.indoor is True
