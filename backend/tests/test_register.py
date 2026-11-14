"""DXF -> sheet image registration on synthetic Swiss-style sheets (frame, plan, legend strip)."""
import ezdxf
import pytest
from PIL import Image, ImageDraw

from app import register as reg
from app.register import dxf_to_image

W, H, DPI = 2480, 1753, 150
K100 = DPI / 25.4 * 1000 / 100  # pixels per metre at 1:100


def plan_dxf(path, w=10.0, h=6.0):
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], close=True, dxfattribs={"layer": "WALL"})
    msp.add_lwpolyline([(w / 2, 0), (w / 2, h)], dxfattribs={"layer": "WALL"})
    msp.add_lwpolyline([(1, h - .1), (3, h - .1), (3, h + .1), (1, h + .1)], close=True,
                       dxfattribs={"layer": "WINDOW"})
    doc.saveas(path)
    return doc


def sheet(path, dxf_doc, k=K100, origin=(700.0, 1100.0), stretch_y=1.0):
    """Draw the DXF polylines at k px/m (y up) inside a frame + legend separator, like the dataset."""
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    for y in (60, 1440, 1690):
        d.line([(60, y), (2420, y)], fill="black", width=2)
    for x in (60, 2420):
        d.line([(x, 60), (x, 1690)], fill="black", width=2)
    for e in dxf_doc.modelspace().query("LWPOLYLINE"):
        pts = [(origin[0] + k * x, origin[1] - k * stretch_y * y) for x, y in e.get_points("xy")]
        if e.closed:
            pts.append(pts[0])
        d.line(pts, fill="black", width=2)
    img.save(path, dpi=(DPI, DPI))


@pytest.fixture(autouse=True)
def _clear():
    reg._cached.cache_clear()
    yield
    reg._cached.cache_clear()


def test_fit_recovers_scale_and_offset(tmp_path):
    doc = plan_dxf(tmp_path / "a.dxf")
    sheet(tmp_path / "a.png", doc)
    t = dxf_to_image(tmp_path / "a.pdf")  # a PDF path fits on its PNG twin
    assert t is not None and t.scale == 100 and t.hit_rate >= 0.99
    for x, y in [(0, 0), (10, 6), (5, 3)]:
        px, py = t.to_pixels(x, y)
        assert abs(px - (700 + K100 * x)) <= 1.5 and abs(py - (1100 - K100 * y)) <= 1.5
    u, v = t(0, 0)
    assert 0 < u < 1 and 0 < v < 1


def test_refuses_when_aspect_disagrees(tmp_path):
    doc = plan_dxf(tmp_path / "b.dxf")
    sheet(tmp_path / "b.png", doc, stretch_y=1.3)
    assert dxf_to_image(tmp_path / "b.png") is None


def test_refuses_when_geometry_is_elsewhere(tmp_path):
    doc = plan_dxf(tmp_path / "c.dxf")
    sheet(tmp_path / "c.png", plan_dxf(tmp_path / "other.dxf", w=6.0, h=10.0))
    assert dxf_to_image(tmp_path / "c.png") is None


def test_no_raster_or_no_dxf(tmp_path):
    plan_dxf(tmp_path / "d.dxf")
    assert dxf_to_image(tmp_path / "d.pdf") is None  # no PNG twin to measure on
    assert dxf_to_image(tmp_path / "missing.png") is None


def test_router_evidence_lands_on_png_sheet(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app import drawings, router

    d = tmp_path / "data" / "swiss_dwellings"
    d.mkdir(parents=True)
    sheet(d / "floor.png", plan_dxf(d / "floor.dxf"))
    monkeypatch.setenv("LEARGAS_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(drawings, "CACHE", tmp_path / "cache")
    window = SimpleNamespace(id="w1", kind="window", points=[(1, 5.9), (3, 5.9), (3, 6.1), (1, 6.1)],
                             room_id=None, label=None, printed_area_m2=None, geometric_area_m2=None)
    ev = router._dxf_evidence("data/swiss_dwellings/floor.png", d / "floor.dxf",
                              SimpleNamespace(items=[window]), ["w1"])
    assert len(ev) == 1
    u, v = ev[0].shape.points[0]
    assert abs(u * W - (700 + K100)) <= 1.5 and abs(v * H - (1100 - K100 * 5.9)) <= 1.5
