import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.api as api  # noqa: E402

from app.ifc import CannotVerify, Model, resolve_model  # noqa: E402
from app.query.schema import Query  # noqa: E402


def _build(path):
    f = ifcopenshell.file(schema="IFC4")
    project = api.run("root.create_entity", f, ifc_class="IfcProject", name="Test House")
    # millimetre lengths, square metre areas, cubic metre volumes (like many real exports)
    mm = api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT", prefix="MILLI")
    m2 = api.run("unit.add_si_unit", f, unit_type="AREAUNIT")
    m3 = api.run("unit.add_si_unit", f, unit_type="VOLUMEUNIT")
    api.run("unit.assign_unit", f, units=[mm, m2, m3])
    site = api.run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    bldg = api.run("root.create_entity", f, ifc_class="IfcBuilding", name="Building")
    api.run("aggregate.assign_object", f, products=[site], relating_object=project)
    api.run("aggregate.assign_object", f, products=[bldg], relating_object=site)
    storeys = {}
    for name in ("Ground Floor", "First Floor"):
        s = api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name=name)
        api.run("aggregate.assign_object", f, products=[s], relating_object=bldg)
        storeys[name] = s

    def add(cls, storey, name=None, qto=None, qvals=None, **kw):
        e = api.run("root.create_entity", f, ifc_class=cls, name=name)
        for k, v in kw.items():
            setattr(e, k, v)
        if cls == "IfcSpace":
            api.run("aggregate.assign_object", f, products=[e], relating_object=storeys[storey])
        else:
            api.run("spatial.assign_container", f, products=[e], relating_structure=storeys[storey])
        if qto:
            q = api.run("pset.add_qto", f, product=e, name=qto)
            api.run("pset.edit_qto", f, qto=q, properties=qvals)
        return e

    add("IfcSpace", "Ground Floor", "G01", "Qto_SpaceBaseQuantities", {"NetFloorArea": 20.5}, LongName="Kitchen")
    add("IfcSpace", "Ground Floor", "G02", "Qto_SpaceBaseQuantities", {"NetFloorArea": 12.25}, LongName="Bath")
    add("IfcSpace", "First Floor", "F01", "Qto_SpaceBaseQuantities", {"NetFloorArea": 30.0}, LongName="Bedroom")
    add("IfcSpace", "First Floor", "F02", "Qto_SpaceBaseQuantities", {"NetFloorArea": 9.0}, LongName="Bath")
    for i in range(3):
        add("IfcWall", "Ground Floor", f"W{i}", "Qto_WallBaseQuantities",
            {"Length": 4000.0, "NetSideArea": 10.0, "NetVolume": 2.0})
    add("IfcWall", "First Floor", "W9", "Qto_WallBaseQuantities", {"Length": 2500.0, "NetSideArea": 6.0, "NetVolume": 1.5})
    add("IfcSlab", "Ground Floor", "S1", "Qto_SlabBaseQuantities", {"NetVolume": 12.5})
    add("IfcSlab", "Ground Floor", "S2")  # no quantities, no geometry
    for i in range(4):
        add("IfcDoor", "Ground Floor" if i < 3 else "First Floor", f"D{i}")
    add("IfcSanitaryTerminal", "First Floor", "WC")
    f.write(str(path))
    return path


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    return Model(str(_build(tmp_path_factory.mktemp("ifc") / "test-house.ifc")))


def Q(**kw):
    return Query(**kw)


@pytest.mark.parametrize("q,value,unit", [
    (Q(op="count", target="door", scope="model", model="Test House"), 4, "count"),
    (Q(op="count", target="door", scope="level", level="Ground Floor"), 3, "count"),
    (Q(op="count", target="room", scope="level", level="first floor"), 2, "count"),  # case-insensitive level
    (Q(op="count", target="sanitary_fixture", scope="model"), 1, "count"),
    (Q(op="count", target="wall", scope="level", level="Ground Floor"), 3, "count"),
    (Q(op="area", target="room", scope="level", level="Ground Floor", name="Kitchen (G01)"), 20.5, "m2"),
    (Q(op="area", target="room", scope="level", level="First Floor", name="F02"), 9.0, "m2"),
    (Q(op="area", target="room", scope="level", level="Ground Floor"), 32.75, "m2"),
    (Q(op="length", target="wall", scope="level", level="Ground Floor"), 12.0, "m"),  # mm -> m
    (Q(op="area", target="wall", scope="level", level="Ground Floor", side_area=True), 30.0, "m2"),
    (Q(op="volume", target="wall", scope="model"), 7.5, "m3"),
])
def test_queries(model, q, value, unit):
    r = model.query(q)
    assert r.value == pytest.approx(value) and r.unit == unit
    if unit != "count":
        assert all(i.method == "qto" for i in r.items)


@pytest.mark.parametrize("q,msg", [
    (Q(op="count", target="door", scope="level", level="Basement"), "No storey"),
    (Q(op="area", target="room", scope="model", name="Bath"), "ambiguous"),
    (Q(op="area", target="room", scope="level", level="Ground Floor", name="Garage"), "not found"),
    (Q(op="volume", target="slab", scope="level", level="Ground Floor"), "no NetVolume"),  # never a partial sum
    (Q(op="count", target="room", room_type="bedroom"), "not IFC concepts"),
    (Q(op="count", target="shower_or_bathtub"), "not supported"),
])
def test_cannot_verify(model, q, msg):
    with pytest.raises(CannotVerify, match=msg):
        model.query(q)


def test_items_carry_evidence(model):
    r = model.query(Q(op="count", target="door", scope="level", level="Ground Floor"))
    assert {i.storey for i in r.items} == {"Ground Floor"} and all(i.guid for i in r.items)


def test_resolve_model(tmp_path):
    (tmp_path / "acme_tower.ifc").write_text("")
    (tmp_path / "acme_tower-mep.ifc").write_text("")
    assert resolve_model(tmp_path / "acme_tower_plan-02-level-1.pdf").name == "acme_tower.ifc"
    assert resolve_model(tmp_path / "acme_tower-mep_plan-01-ground.png").name == "acme_tower-mep.ifc"
    assert resolve_model(tmp_path / "acme_tower.ifc").name == "acme_tower.ifc"
    with pytest.raises(CannotVerify):
        resolve_model(tmp_path / "other_plan-01-x.pdf")
