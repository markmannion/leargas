"""Slab specifications must preserve area, provenance, units, and unknowns end to end."""
from math import fsum
from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from app import drawings, main, router
from app.query.parser import parse
from app.query.schema import Query
from app.schema import AskRequest
from app.slab_drawings import CannotVerify, measure, parse_schedule, link_specification

QUESTION = "Show slab area grouped by thickness and reinforcement"


@pytest.mark.parametrize("question,level", [
    (QUESTION, None),
    ("Show slab areas by reinforcement and thickness?", None),
    ("What is the area of all slabs grouped by thickness and reinforcement on level 'Ground Floor'?", "Ground Floor"),
])
def test_parse_grouped_slabs(question, level):
    q = parse(question, use_llm=False).query
    assert q and q.op == "area" and q.target == "slab" and q.group_by == "thickness_reinforcement"
    assert q.level == level


@pytest.fixture
def ifc_file(tmp_path):
    ifc = pytest.importorskip("ifcopenshell")
    import ifcopenshell.api as api
    f = ifc.file(schema="IFC4")
    api.run("root.create_entity", f, ifc_class="IfcProject", name="Slab test")
    mm = api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT", prefix="MILLI")
    m2 = api.run("unit.add_si_unit", f, unit_type="AREAUNIT")
    m3 = api.run("unit.add_si_unit", f, unit_type="VOLUMEUNIT")
    api.run("unit.assign_unit", f, units=[mm, m2, m3])
    return f, tmp_path / "slabs.ifc"


def entity(f, cls, name=None):
    import ifcopenshell.api as api
    return api.run("root.create_entity", f, ifc_class=cls, name=name)


def pset(f, obj, name, **values):
    import ifcopenshell.api as api
    ps = api.run("pset.add_pset", f, product=obj, name=name)
    api.run("pset.edit_pset", f, pset=ps, properties=values)
    return ps


def slab(f, name, area):
    import ifcopenshell.api as api
    e = entity(f, "IfcSlab", name)
    q = api.run("pset.add_qto", f, product=e, name="Qto_SlabBaseQuantities")
    api.run("pset.edit_qto", f, qto=q, properties={"NetArea": area})
    return e


def layers(f, obj, *widths):
    material = f.create_entity("IfcMaterialLayerSet", MaterialLayers=[
        f.create_entity("IfcMaterialLayer", LayerThickness=width) for width in widths])
    f.create_entity("IfcRelAssociatesMaterial", GlobalId=__import__("ifcopenshell").guid.new(),
                    RelatedObjects=[obj], RelatingMaterial=material)
    return material


def takeoff(f, path):
    from app.ifc import Model
    f.write(str(path))
    return router.run_ifc(path, Query(op="area", target="slab", group_by="thickness_reinforcement"), None)


def test_ifc_type_properties_occurrence_overrides_and_unknown_area(ifc_file):
    import ifcopenshell.api as api
    f, path = ifc_file
    typ = entity(f, "IfcSlabType", "RC200")
    pset(f, typ, "SlabSpecification", Thickness=200.0, Reinforcement="T12 @ 200 EW")
    a, b, c = slab(f, "S1", 10.25), slab(f, "S2", 20.5), slab(f, "S3", 7.75)
    api.run("type.assign_type", f, related_objects=[a, b], relating_type=typ)
    pset(f, b, "SlabSpecification", Thickness=250.0, Reinforcement="T16 @ 200 EW")
    layers(f, c, 100.0, 100.0)
    out = takeoff(f, path)
    assert out.ok, out.reason
    assert out.value == 38.5 == fsum(g.value for g in out.slab_groups)
    assert [(r.thickness_mm, r.reinforcement) for r in out.slab_areas] == [
        (200, "Reinforcement: T12 @ 200 EW"), (250, "Reinforcement: T16 @ 200 EW"), (200, None)]
    assert out.slab_areas[0].slab_type == "RC200"
    unknown = next(g for g in out.slab_groups if g.specification_status == "unknown")
    assert unknown.value == 7.75 and unknown.thickness_mm == 200 and unknown.reinforcement is None
    fields = router.reconcile(AskRequest(path="slabs.ifc", question=QUESTION), Query(op="area", target="slab"), [out])
    assert fields["status"] == "partial" and fields["answer"] == 38.5
    assert "unknown specification" in fields["explanation"]


def test_ifc_type_layers_explicit_units_and_quantity_units(ifc_file):
    import ifcopenshell.api as api
    f, path = ifc_file
    typ = entity(f, "IfcSlabType", "Layered")
    layers(f, typ, 120., 80.)
    a = slab(f, "S1", 1_000_000.)
    api.run("type.assign_type", f, related_objects=[a], relating_type=typ)
    # Explicit mm² quantity overrides the project's square metres.
    q = f.by_type("IfcQuantityArea")[0]
    q.Unit = api.run("unit.add_si_unit", f, unit_type="AREAUNIT", prefix="MILLI")
    b = slab(f, "S2", 2.)
    ps = pset(f, b, "SlabSpecification", Thickness=0.25)
    prop = ps.HasProperties[0]
    prop.Unit = api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT")
    out = takeoff(f, path)
    assert out.ok, out.reason
    assert out.value == 3 and [r.thickness_mm for r in out.slab_areas] == [200, 250]


def test_ifc_reinforcement_relationships_not_nearby_bars(ifc_file):
    import ifcopenshell.api as api
    f, path = ifc_file
    a, b, c = slab(f, "S1", 4.), slab(f, "S2", 5.), slab(f, "S3", 6.)
    for obj in (a, b, c):
        layers(f, obj, 200.)
    mesh = entity(f, "IfcReinforcingMesh", "Mesh")
    mesh.LongitudinalBarNominalDiameter = 12.
    mesh.TransverseBarNominalDiameter = 10.
    mesh.LongitudinalBarSpacing = 200.
    mesh.TransverseBarSpacing = 150.
    api.run("aggregate.assign_object", f, products=[mesh], relating_object=a)
    bar = entity(f, "IfcReinforcingBar", "Explicitly assigned")
    bar.NominalDiameter = 16.
    f.create_entity("IfcRelAssignsToProduct", GlobalId=__import__("ifcopenshell").guid.new(),
                    RelatedObjects=[bar], RelatingProduct=b)
    nearby = entity(f, "IfcReinforcingBar", "Unrelated")
    nearby.NominalDiameter = 32.
    out = takeoff(f, path)
    assert out.ok, out.reason
    assert "LongitudinalBarSpacing=200 mm" in out.slab_areas[0].reinforcement
    assert "NominalDiameter=16 mm" in out.slab_areas[1].reinforcement
    assert out.slab_areas[2].reinforcement is None
    assert all("32 mm" not in (r.reinforcement or "") for r in out.slab_areas)


def test_ifc_missing_area_never_becomes_partial_sum(ifc_file):
    f, path = ifc_file
    slab(f, "S1", 10.)
    entity(f, "IfcSlab", "No area")
    out = takeoff(f, path)
    assert not out.ok and "no NetArea" in out.reason and not out.slab_areas


def test_ifc_conflicting_thickness_keeps_area(ifc_file):
    f, path = ifc_file
    a = slab(f, "S1", 10.)
    pset(f, a, "SlabSpecification", Thickness=200., NominalThickness=250., Reinforcement="Unknown")
    out = takeoff(f, path)
    assert out.ok and out.value == 10
    assert out.slab_areas[0].thickness_mm is None and out.slab_areas[0].reinforcement is None
    assert "Conflicting" in out.slab_areas[0].warnings[0]


def test_ifc_structured_reinforcement_definition(ifc_file):
    import ifcopenshell
    f, path = ifc_file
    a = slab(f, "S1", 10.)
    layers(f, a, 200.)
    bar = f.create_entity("IfcReinforcementBarProperties", TotalCrossSectionArea=452.4,
                          SteelGrade="B500", NominalBarDiameter=12., BarCount=4.)
    section = f.create_entity("IfcSectionReinforcementProperties", LongitudinalStartPosition=0.,
                              LongitudinalEndPosition=5000., ReinforcementRole="MAIN",
                              CrossSectionReinforcementDefinitions=[bar])
    definition = f.create_entity("IfcReinforcementDefinitionProperties", GlobalId=ifcopenshell.guid.new(),
                                 ReinforcementSectionDefinitions=[section])
    f.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(), RelatedObjects=[a],
                    RelatingPropertyDefinition=definition)
    out = takeoff(f, path)
    assert out.ok, out.reason
    assert out.slab_areas[0].specification_status == "known"
    assert "NominalBarDiameter=12 mm" in out.slab_areas[0].reinforcement
    assert "TotalCrossSectionArea=452.4 mm²" in out.slab_areas[0].reinforcement
    assert any("IfcReinforcementDefinitionProperties" in r.label for r in out.slab_areas[0].references)


def test_ifc2x3_type_properties_and_missing_reinforcement(tmp_path):
    ifc = pytest.importorskip("ifcopenshell")
    f = ifc.file(schema="IFC2X3")
    uid = ifc.guid.new
    units = f.create_entity("IfcUnitAssignment", Units=[
        f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE"),
        f.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE"),
        f.create_entity("IfcSIUnit", UnitType="VOLUMEUNIT", Name="CUBIC_METRE"),
    ])
    f.create_entity("IfcProject", GlobalId=uid(), UnitsInContext=units)
    a = f.create_entity("IfcSlab", GlobalId=uid(), Name="S1")
    prop = f.create_entity("IfcPropertySingleValue", Name="Thickness", NominalValue=f.create_entity("IfcLengthMeasure", 200.))
    ps = f.create_entity("IfcPropertySet", GlobalId=uid(), Name="SlabSpecification", HasProperties=[prop])
    typ = f.create_entity("IfcSlabType", GlobalId=uid(), Name="RC200", HasPropertySets=[ps], PredefinedType="FLOOR")
    f.create_entity("IfcRelDefinesByType", GlobalId=uid(), RelatedObjects=[a], RelatingType=typ)
    quantity = f.create_entity("IfcQuantityArea", Name="NetArea", AreaValue=12.)
    qs = f.create_entity("IfcElementQuantity", GlobalId=uid(), Name="BaseQuantities", Quantities=[quantity])
    f.create_entity("IfcRelDefinesByProperties", GlobalId=uid(), RelatedObjects=[a], RelatingPropertyDefinition=qs)
    out = takeoff(f, tmp_path / "old-schema.ifc")
    assert out.ok, out.reason
    row = out.slab_areas[0]
    assert row.thickness_mm == 200 and row.slab_type == "RC200" and row.value == 12
    assert row.reinforcement is None and row.specification_status == "unknown"


def test_ifc_geometric_area_fallback_and_level_scope(ifc_file, monkeypatch):
    import ifcopenshell.api as api
    from app.ifc import Model
    f, path = ifc_file
    ground = entity(f, "IfcBuildingStorey", "Ground Floor")
    upper = entity(f, "IfcBuildingStorey", "Upper Floor")
    a = entity(f, "IfcSlab", "S1")
    b = slab(f, "S2", 100.)
    api.run("spatial.assign_container", f, products=[a], relating_structure=ground)
    api.run("spatial.assign_container", f, products=[b], relating_structure=upper)
    f.write(str(path))
    model = Model(str(path))
    monkeypatch.setattr(model, "geometry", lambda e, what: 12.5 if e.Name == "S1" and what == "area" else None)
    monkeypatch.setattr("app.ifc.open_model", lambda _: model)
    q = parse(QUESTION + " on level 'Ground Floor'", use_llm=False).query
    out = router.run_ifc(path, q, None)
    assert out.ok and out.value == 12.5 and len(out.slab_areas) == 1
    assert out.slab_areas[0].method == "geometry" and out.slab_areas[0].level == "Ground Floor"
    assert "Ground Floor" in out.explanation


def test_ifc_conflicting_reinforcement_does_not_fall_back_to_type(ifc_file):
    import ifcopenshell.api as api
    f, path = ifc_file
    a = slab(f, "S1", 10.)
    typ = entity(f, "IfcSlabType", "RC")
    layers(f, a, 200.)
    pset(f, typ, "SlabSpecification", Reinforcement="T10 @ 200")
    api.run("type.assign_type", f, related_objects=[a], relating_type=typ)
    pset(f, a, "SlabSpecA", Reinforcement="T12 @ 200")
    pset(f, a, "SlabSpecB", Reinforcement="T16 @ 200")
    out = takeoff(f, path)
    assert out.ok and out.value == 10
    assert out.slab_areas[0].reinforcement is None
    assert any("Conflicting exported reinforcement" in w for w in out.slab_areas[0].warnings)


def drawing(path, *, overlapping=False, units=4):
    doc = ezdxf.new()
    doc.units = units  # mm
    for layer in ("SLAB_OUTLINE", "SLAB_OPENING", "SLAB_MARK", "SLAB_SCHEDULE", "SLAB_DETAIL"):
        doc.layers.new(layer)
    m = doc.modelspace()
    for i in range(3):
        x = i * (2000 if overlapping else 5000)
        m.add_lwpolyline([(x, 0), (x+4000, 0), (x+4000, 5000), (x, 5000)], close=True,
                         dxfattribs={"layer": "SLAB_OUTLINE"})
        m.add_text(f"S{i+1}", dxfattribs={"insert": (x+2000, 2500), "layer": "SLAB_MARK"})
    m.add_lwpolyline([(100, 100), (1100, 100), (1100, 1100), (100, 1100)], close=True,
                     dxfattribs={"layer": "SLAB_OPENING"})
    doc.saveas(path)
    return path


def schedule_pdf(path):
    import pymupdf
    with pymupdf.open() as doc:
        p = doc.new_page()
        p.insert_text((30, 30), "Mark | Type | Thickness | Reinforcement | Detail\nS1 | RC | 200 mm | - | D1\nS2 | RC | 200 mm | - | D1\nS3 | RC | 250 mm | - | -", fontsize=9)
        p = doc.new_page()
        p.insert_text((30, 30), "Detail D1 | Reinforcement: T12 @ 200 EW", fontsize=9)
        doc.save(path)


@pytest.fixture
def drawing_group(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARGAS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("LEARGAS_MOCK", raising=False)
    monkeypatch.setattr(drawings, "CACHE", tmp_path / "cache")
    folder = tmp_path / "uploads" / "0123456789ab"
    folder.mkdir(parents=True)
    path = drawing(folder / "plan.dxf")
    schedule_pdf(folder / "structure.pdf")
    return tmp_path, path


def test_drawing_cross_sheet_detail_link_area_holes_and_unknown(drawing_group):
    root, path = drawing_group
    value, rows, evidence = measure(path, root, lambda x, y: (x / 15000, 1 - y / 5000))
    assert value == 59 and [r.value for r in rows] == [19, 20, 20]
    assert [r.reinforcement for r in rows] == ["T12 @ 200 EW", "T12 @ 200 EW", None]
    assert [r.thickness_mm for r in rows] == [200, 200, 250]
    assert any(ref.path.endswith("structure.pdf") and ref.page == 1 for ref in rows[0].references)
    assert len(evidence) == 3 and len(evidence[0].shape.holes) == 1
    # Another project's matching slab mark must never supply a missing specification.
    other = root / "uploads" / "fedcba987654"
    other.mkdir()
    schedule_pdf(other / "other.pdf")
    assert rows[2].reinforcement is None


def test_drawing_conflicts_and_missing_detail_preserve_unknown():
    schedule = parse_schedule("S1 | Thickness: 200 mm | Reinforcement: T12\nS1 | Thickness: 250 mm | Reinforcement: T16\nS2 | Thickness: 200 mm | Detail: D404", "structure.pdf")
    spec, refs, warnings = link_specification("S1", schedule)
    assert "thickness" not in spec and "reinforcement" not in spec and len(refs) == 2
    assert len(warnings) == 2
    spec, _, warnings = link_specification("S2", schedule)
    assert spec["thickness"] == 200 and "reinforcement" not in spec and "d404" in warnings[0]


def test_schedule_thickness_header_units_and_incomplete_details():
    schedule = parse_schedule("Mark | Type | Thickness (mm) | Reinforcement | Detail\nS1 | RC | 200 | T12 | D404", "schedule.pdf")
    spec, _, warnings = link_specification("S1", schedule)
    assert spec["thickness"] == 200 and "reinforcement" not in spec
    assert "d404" in warnings[0]


def test_native_pdf_table_keeps_columns_associated(tmp_path):
    import pymupdf
    path = drawing(tmp_path / "plan.dxf")
    with pymupdf.open() as doc:
        page = doc.new_page()
        xs, ys = [30, 90, 170, 280, 440, 550], [30, 60, 90]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for j, row in enumerate([
            ["Mark", "Type", "Thickness (mm)", "Reinforcement", "Detail"],
            ["S1", "RC", "200", "T12 @ 200 EW", "-"],
        ]):
            for i, value in enumerate(row):
                page.insert_text((xs[i] + 3, ys[j] + 18), value, fontsize=9)
        doc.save(tmp_path / "plan.pdf")
    value, rows, _ = measure(path, tmp_path)
    assert value == 59 and rows[0].thickness_mm == 200
    assert rows[0].reinforcement == "T12 @ 200 EW" and rows[0].slab_type == "RC"
    assert rows[1].reinforcement is None


@pytest.mark.parametrize("units,overlap,message", [(0, False, "units"), (4, True, "overlap")])
def test_drawing_refuses_unmeasurable_or_overlapping_zones(tmp_path, units, overlap, message):
    path = drawing(tmp_path / "plan.dxf", overlapping=overlap, units=units)
    with pytest.raises(CannotVerify, match=message):
        measure(path, tmp_path)


def test_api_slab_grouping_bypasses_models_and_scalar_cache(drawing_group, monkeypatch):
    root, path = drawing_group
    def forbidden(*a, **kw):
        pytest.fail("Slab takeoff must not use a scalar cache/model")
    monkeypatch.setenv("LEARGAS_DEMO_CACHE", "1")
    monkeypatch.setattr(main.demo_cache, "enabled", lambda: True)
    monkeypatch.setattr(main.demo_cache, "lookup", forbidden)
    monkeypatch.setattr(router, "run_gemma", forbidden)
    monkeypatch.setattr(router, "gemma_available", forbidden)
    client = TestClient(main.app)
    r = client.post("/ask", json={"path": path.relative_to(root).as_posix(), "question": QUESTION})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["answer"] == 59 and a["status"] == "partial"
    assert [(g["thickness_mm"], g["value"]) for g in a["slab_groups"]] == [(200, 39), (250, 20)]
    assert a["slab_groups"][1]["reinforcement"] is None
    assert a["slab_groups"][1]["specification_status"] == "unknown"
    assert len(a["evidence"]) == 3


@pytest.mark.parametrize("extra", [
    {"engine": "gemma_ft"}, {"region": {"bbox": [0, 0, 1, 1]}}, {"room_breakdown": True, "engine": "gemma_base"},
])
def test_slab_takeoffs_refuse_unsupported_modes(drawing_group, extra):
    root, path = drawing_group
    r = router.route(AskRequest(path=path.relative_to(root).as_posix(), question=QUESTION, **extra))
    assert r.status == "cannot_verify" and not r.slab_groups


def test_raster_only_slabs_do_not_invent_area_or_reinforcement(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARGAS_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(router, "gemma_available", lambda: pytest.fail("No scalar model for slabs"))
    out = router.route(AskRequest(path="raster.png", question=QUESTION))
    assert out.status == "cannot_verify" and out.answer is None
