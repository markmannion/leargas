"""Router: source selection, reconciliation and DXF evidence on a synthetic Swiss-style floor plan."""
import ezdxf
import pytest
from fastapi.testclient import TestClient

from app import drawings, main, router
from app.router import Outcome, agree, reconcile, route
from app.schema import Answer, AskRequest, Source

PLAN = "data/swiss_dwellings/floor.pdf"
WINDOWS_Q = "How many windows are drawn on this floor plan?"


def rectangle(space, layer, x, y, w, h):
    space.add_lwpolyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True, dxfattribs={"layer": layer})


@pytest.fixture
def root(tmp_path, monkeypatch):
    doc = ezdxf.new()
    doc.units = 6
    for layer in ("ROOM_OUTLINE", "UNIT_OUTLINE", "ROOM_TEXT", "WINDOW", "DOOR", "FIXTURE", "ANNOTATION"):
        doc.layers.new(layer)
    space = doc.modelspace()
    space.add_text("Source: Swiss Dwellings, CC BY 4.0", dxfattribs={"layer": "ANNOTATION"})
    for x, number, label, area in [(0, "1.01", "Zimmer", "12.34 m²"), (4, "1.02", "Balkon", "3,21 m²")]:
        rectangle(space, "ROOM_OUTLINE", x, 0, 4, 4)
        for y, text in [(3, label), (2, number), (1, area)]:
            space.add_text(text, dxfattribs={"layer": "ROOM_TEXT", "insert": (x + 2, y), "height": .18})
    rectangle(space, "UNIT_OUTLINE", -.1, -.1, 8.2, 4.2)
    space.add_text("Whg. A", dxfattribs={"layer": "ROOM_TEXT", "insert": (1, 1)})
    rectangle(space, "WINDOW", 0, 0, 2, .3)
    rectangle(space, "DOOR", 6, 0, 1, .2)
    d = tmp_path / "data" / "swiss_dwellings"
    d.mkdir(parents=True)
    doc.saveas(d / "floor.dxf")

    monkeypatch.setenv("LEARGAS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("LEARGAS_MOCK", raising=False)
    monkeypatch.setattr(drawings, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(router, "gemma_available", lambda: False)
    router._dxf_drawing.cache_clear()
    yield tmp_path
    router._dxf_drawing.cache_clear()


def ask(question=WINDOWS_Q, path=PLAN, engine="auto"):
    return route(AskRequest(path=path, question=question, engine=engine))


def test_geometry_count_with_evidence_on_rendered_sheet(root):
    a = ask()
    assert (a.answer, a.unit, a.status, a.source) == (1, "count", "verified", "geometry_dxf")
    assert len(a.evidence) == 1
    fr = drawings.dxf_frame(root / "data/swiss_dwellings/floor.dxf")
    (x0, _), (_, y1), m = fr["extmin"], fr["extmax"], fr["margin"]
    w = fr["extmax"][0] - x0 + 2 * m
    h = y1 - fr["extmin"][1] + 2 * m
    xs = [p[0] for p in a.evidence[0].shape.points]
    ys = [p[1] for p in a.evidence[0].shape.points]
    # the window spans x 0..2 m and y 0..0.3 m in DXF space; y is flipped in image space
    assert min(xs) == pytest.approx((0 - x0 + m) / w, abs=1e-6)
    assert max(xs) == pytest.approx((2 - x0 + m) / w, abs=1e-6)
    assert max(ys) == pytest.approx((y1 - 0 + m) / h, abs=1e-6)


def test_geometry_area(root):
    a = ask("What is the net floor area of room 1.01 ('Zimmer') in m²?")
    assert (a.answer, a.unit, a.type, a.status) == (12.34, "m2", "area", "verified")
    assert a.evidence and "12.34 m²" in a.evidence[0].label


def test_unparseable_question_cannot_verify(root):
    a = ask("Is this a nice flat?", engine="geometry")
    assert a.status == "cannot_verify" and a.answer is None and a.explanation


def test_no_twin_and_no_model(root):
    a = ask(path="data/cubicasa5k/missing.png")
    assert a.status == "cannot_verify"
    assert "MODEL_BASE_URL" in a.explanation and "twin" in a.explanation


def _fake_gemma(value, confidence=0.9):
    def run(source, image, question):
        return Outcome(source, value=value, unit="count", confidence=confidence, explanation="model")
    return run


def test_auto_agreement(root, monkeypatch):
    monkeypatch.setattr(router, "gemma_available", lambda: True)
    monkeypatch.setattr(router, "run_gemma", _fake_gemma(1))
    a = ask()
    assert a.status == "verified" and a.answer == 1
    assert [s.source for s in a.sources] == ["geometry_dxf", "gemma_ft"]


def test_auto_disagreement_reports_geometry(root, monkeypatch):
    monkeypatch.setattr(router, "gemma_available", lambda: True)
    monkeypatch.setattr(router, "run_gemma", _fake_gemma(3))
    a = ask()
    assert (a.status, a.answer, a.source) == ("disagreement", 1, "geometry_dxf")
    assert {s.answer for s in a.sources} == {1, 3}


def test_gemma_skips_area_on_sheet_without_printed_m2(root, monkeypatch):
    router._import_model_pkg()  # puts the repo root (and so model/) on sys.path
    from model import common

    q = "What is the total area of the apartment in m²?"
    monkeypatch.setattr(router, "run_gemma", _fake_gemma(40.0, confidence=0.999))
    monkeypatch.setattr(common, "prints_areas", lambda path: False)
    a = ask(question=q, engine="gemma_base")
    assert a.status == "cannot_verify" and a.answer is None
    assert "prints no room areas" in a.explanation

    monkeypatch.setattr(common, "prints_areas", lambda path: True)
    assert ask(question=q, engine="gemma_base").answer == 40.0


def test_gemma_only_engine(root, monkeypatch):
    monkeypatch.setattr(router, "run_gemma", _fake_gemma(4, confidence=0.6))
    a = ask(engine="gemma_base")
    assert (a.status, a.answer, a.source) == ("partial", 4, "gemma_base")


def test_reconcile_low_confidence_model_alone():
    req = AskRequest(path="data/cubicasa5k/x.png", question=WINDOWS_Q)
    out = reconcile(req, None, [Outcome(Source.gemma_ft, value=5, unit="count", confidence=0.2)])
    assert out["status"] == "cannot_verify" and out["answer"] is None


def test_agree_tolerance():
    a = Outcome(Source.geometry_dxf, value=100.0, unit="m2")
    assert agree(a, Outcome(Source.gemma_ft, value=101.5, unit="m2"))
    assert not agree(a, Outcome(Source.gemma_ft, value=103.0, unit="m2"))
    assert not agree(Outcome(Source.geometry_dxf, value=4, unit="count"), Outcome(Source.gemma_ft, value=5, unit="count"))


def test_api_live_mode(root):
    c = TestClient(main.app)
    assert c.get("/health").json()["mode"] == "live"
    r = c.post("/ask", json={"path": PLAN, "question": WINDOWS_Q}).json()
    assert Answer.model_validate(r).answer == 1
