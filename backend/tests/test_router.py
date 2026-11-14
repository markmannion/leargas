"""Router: source selection, reconciliation and DXF evidence on a synthetic Swiss-style floor plan."""
import ezdxf
import pytest
from fastapi.testclient import TestClient

from app import drawings, main, router
from app.router import Outcome, agree, reconcile, route
from app.schema import Answer, AskRequest, Source, Region

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
    monkeypatch.setattr(router, "gemma_health", lambda: {"status": "unconfigured", "available": False, "models": {}})
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


def test_region_filters_geometry_and_evidence(root):
    full = ask()
    points = full.evidence[0].shape.points
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    selection = Region(bbox=(min(xs) - .01, min(ys) - .01, max(xs) + .01, max(ys) + .01))
    scoped = route(AskRequest(path=PLAN, question=WINDOWS_Q, engine="geometry", region=selection))
    assert scoped.answer == 1 and scoped.status == "verified"
    assert scoped.region == selection and len(scoped.evidence) == 1
    assert "centers" in scoped.explanation
    empty = route(AskRequest(path=PLAN, question=WINDOWS_Q, engine="geometry",
                             region=Region(bbox=(.01, .01, .02, .02))))
    assert empty.answer == 0 and empty.status == "verified" and empty.evidence == []


def test_region_area_requires_complete_rooms(root):
    question = "What is the net floor area of room 1.01 ('Zimmer') in m²?"
    full = ask(question)
    points = full.evidence[0].shape.points
    x0, x1 = min(p[0] for p in points), max(p[0] for p in points)
    y0, y1 = min(p[1] for p in points), max(p[1] for p in points)
    complete = route(AskRequest(path=PLAN, question=question, engine="geometry",
                                region=Region(bbox=(x0 - .001, y0 - .001, x1 + .001, y1 + .001))))
    assert complete.answer == 12.34 and complete.status == "verified"
    partial = route(AskRequest(path=PLAN, question=question, engine="geometry",
                               region=Region(bbox=(x0, y0, (x0 + x1) / 2, y1))))
    assert partial.answer is None and partial.status == "cannot_verify"
    assert "cuts through a room" in partial.explanation


def test_region_refuses_unaligned_geometry(root, monkeypatch):
    monkeypatch.setattr(router, "_dxf_normalizer", lambda *a: (_ for _ in ()).throw(router.CannotScope("Cannot align")))
    a = route(AskRequest(path=PLAN, question=WINDOWS_Q, engine="geometry", region=Region(bbox=(0, 0, .5, .5))))
    assert a.answer is None and "Cannot align" in a.explanation


def test_region_ifc_cannot_return_whole_model_answer(root):
    result = router.run_ifc(root / "absent.ifc", None, None, Region(bbox=(0, 0, .5, .5)))
    assert not result.ok and "not aligned" in result.reason


@pytest.mark.parametrize("question", ["How many windows inside the selected region?", "How many windows here?"])
def test_region_natural_question_uses_geometry(root, question):
    a = route(AskRequest(path=PLAN, question=question, engine="geometry", region=Region(bbox=(0, 0, 1, 1))))
    assert a.answer == 1 and a.status == "verified" and a.question == question


def test_region_model_sees_crop_and_points_return_to_sheet(root, monkeypatch):
    from PIL import Image
    from types import SimpleNamespace

    path = root / "data" / "crop.png"
    Image.new("RGB", (200, 100), "white").save(path)
    seen = {}

    def model_ask(image, question, **kwargs):
        seen.update(size=image.size, question=question)
        return {"ok": True, "answer": 1, "unit": "count", "confidence": .999, "points": [[.5, .5]]}

    monkeypatch.setenv("MODEL_BASE_URL", "http://unused.test")
    monkeypatch.setattr(router, "_import_model_pkg", lambda: SimpleNamespace(ask=model_ask))
    monkeypatch.setattr(router.gemma_status, "status", lambda name: {"available": True})
    result = router.run_gemma(Source.gemma_base, path, WINDOWS_Q,
                              Region(bbox=(.2, .1, .8, .7)), "data/crop.png")
    assert result.ok and seen["size"] == (120, 60)
    assert "only the user-selected region" in seen["question"]
    assert result.evidence[0].shape.point == pytest.approx((.5, .4))


def test_auto_returns_geometry_while_model_stalls(root, monkeypatch):
    from threading import Event

    release = Event()
    finished = Event()

    def stalled(source, image, question):
        try:
            release.wait(2)
            return Outcome(source, value=99, unit="count", confidence=1)
        finally:
            finished.set()

    monkeypatch.setattr(router, "gemma_available", lambda: True)
    monkeypatch.setattr(router, "run_gemma", stalled)
    monkeypatch.setattr(router, "GEMMA_COMPARE_WAIT", 0.01)
    try:
        a = ask()
        assert not release.is_set() and not finished.is_set()
        assert (a.answer, a.status, a.source) == (1, "verified", "geometry_dxf")
        assert a.evidence
        assert "without model confirmation" in a.explanation
        assert next(s for s in a.sources if s.source == "gemma_ft").answer is None
    finally:
        release.set()
        assert finished.wait(2)


def test_raster_timeout_refuses_and_starts_cooldown(root, monkeypatch):
    from threading import Event

    release, finished = Event(), Event()
    failures = []

    def stalled(source, image, question):
        try:
            release.wait(2)
            return Outcome(source, value=99, unit="count", confidence=1)
        finally:
            finished.set()

    monkeypatch.setattr(router, "run_gemma", stalled)
    monkeypatch.setattr(router, "GEMMA_TIMEOUT", 0.01)
    monkeypatch.setattr(router.gemma_status, "failed", failures.append)
    try:
        a = ask(path="data/cubicasa5k/x.png", engine="gemma_base")
        assert a.answer is None and a.status == "cannot_verify"
        assert "did not respond in time" in a.explanation
        assert failures == ["gemma-base"]
    finally:
        release.set()
        assert finished.wait(2)


def test_auto_degrades_when_gemma_is_down(root, monkeypatch):
    from types import SimpleNamespace

    def unexpected(*args, **kwargs):
        pytest.fail("Unavailable Gemma must not receive an inference request")

    monkeypatch.setenv("MODEL_BASE_URL", "http://gemma.test/v1")
    monkeypatch.setattr(router, "gemma_available", lambda: True)
    monkeypatch.setattr(router, "raster_image", lambda _: root / "floor.png")
    monkeypatch.setattr(router, "_import_model_pkg", lambda: SimpleNamespace(ask=unexpected))
    monkeypatch.setattr(router.gemma_status, "status", lambda _: {"status": "unavailable", "available": False})
    a = ask()
    assert (a.answer, a.status) == (1, "verified")
    assert a.evidence and "temporarily unavailable" in a.explanation
    a = ask(path="data/cubicasa5k/x.png", engine="gemma_ft")
    assert a.answer is None and a.status == "cannot_verify"
    assert "temporarily unavailable" in a.explanation


def test_gemma_inference_failure_is_sanitized_and_cooled_down(root, monkeypatch):
    from types import SimpleNamespace

    def failed(*args, **kwargs):
        raise RuntimeError("http://private-host:8000 secret upstream body")

    failures = []
    monkeypatch.setenv("MODEL_BASE_URL", "http://gemma.test/v1")
    monkeypatch.setattr(router, "_import_model_pkg", lambda: SimpleNamespace(ask=failed))
    monkeypatch.setattr(router.gemma_status, "status", lambda _: {"status": "available", "available": True})
    monkeypatch.setattr(router.gemma_status, "failed", failures.append)
    out = router.run_gemma(Source.gemma_ft, root / "floor.png", WINDOWS_Q)
    assert not out.ok and "temporarily unavailable" in out.reason
    assert "private-host" not in out.reason and "secret" not in out.reason
    assert failures == ["gemma-ft"]


def test_full_gemma_pool_does_not_queue_or_block_geometry(root, monkeypatch):
    from threading import BoundedSemaphore

    monkeypatch.setattr(router, "gemma_available", lambda: True)
    monkeypatch.setattr(router, "_gemma_slots", BoundedSemaphore(0))
    a = ask()
    assert (a.answer, a.status) == (1, "verified")
    assert "Gemma is busy" in a.explanation
