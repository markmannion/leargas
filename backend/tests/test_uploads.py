"""Uploads: stored under the data root, listed in /drawings, twins paired by stem, and answerable."""
import ezdxf
import pytest
from fastapi.testclient import TestClient

from app import drawings, main, router, uploads
from app.router import Outcome, gemma_calibrated, reconcile
from app.schema import AskRequest, Source

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARGAS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("LEARGAS_MOCK", raising=False)
    monkeypatch.delenv("LEARGAS_DEMO_CACHE", raising=False)
    monkeypatch.setattr(drawings, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(router, "gemma_available", lambda: False)
    drawings._catalogue.cache_clear()
    router._dxf_drawing.cache_clear()
    yield TestClient(main.app)
    drawings._catalogue.cache_clear()
    router._dxf_drawing.cache_clear()


def up(client, name, body, group=None):
    params = {"name": name, **({"group": group} if group else {})}
    return client.post("/upload", params=params, content=body)


def dxf_bytes(tmp_path):
    doc = ezdxf.new()
    doc.layers.new("WINDOW")
    doc.modelspace().add_lwpolyline([(0, 0), (2, 0), (2, .3), (0, .3)], close=True, dxfattribs={"layer": "WINDOW"})
    p = tmp_path / "src.dxf"
    doc.saveas(p)
    return p.read_bytes()


def test_png_upload_is_listed_first(client, tmp_path):
    r = up(client, "My Plan (v2).png", PNG)
    assert r.status_code == 200
    d = r.json()["drawing"]
    assert d["path"] == f"uploads/{r.json()['group']}/My_Plan_v2.png"
    assert (d["collection"], d["render"], d["questions"]) == ("uploads", "image", [])
    assert (tmp_path / d["path"]).read_bytes() == PNG
    listed = client.get("/drawings").json()["drawings"]
    assert listed[0]["path"] == d["path"]
    assert client.get("/drawing", params={"path": d["path"]}).status_code == 200


def test_same_content_same_group(client):
    a, b = up(client, "a.png", PNG).json(), up(client, "a.png", PNG).json()
    assert a["group"] == b["group"]


@pytest.mark.parametrize("name,body,code", [
    ("plan.exe", b"MZ", 415),
    ("plan.png", b"%PDF-1.7", 415),  # content doesn't match the extension
    ("plan.png", b"", 400),
    ("plan.dxf", b"not a dxf", 415),
])
def test_rejects_bad_files(client, name, body, code):
    assert up(client, name, body).status_code == code


def test_rejects_bad_group(client):
    assert up(client, "a.png", PNG, group="../../etc").status_code == 400


def test_twins_pair_by_stem_and_dxf_answers(client, tmp_path):
    g = up(client, "floor.png", PNG).json()["group"]
    r = up(client, "floor.dxf", dxf_bytes(tmp_path), group=g).json()
    d = r["drawing"]
    assert d["path"].endswith("/floor.png") and d["files"] == ["dxf", "png"]  # the sheet stays primary
    assert len([x for x in client.get("/drawings").json()["drawings"] if x["collection"] == "uploads"]) == 1
    a = client.post("/ask", json={"path": d["path"], "question": "How many windows are drawn on this floor plan?"})
    assert a.status_code == 200
    assert a.json()["source"] == "geometry_dxf"


def test_gemma_not_verified_on_uploads(client):
    req = AskRequest(path="uploads/0123456789ab/plan.png", question="How many windows are drawn on this floor plan?")
    assert gemma_calibrated(req) is False
    gem = Outcome(Source.gemma_ft, value=4, unit="count", confidence=0.999, explanation="model")
    assert reconcile(req, None, [gem], calibrated=False)["status"] == "partial"
    assert reconcile(req, None, [gem], calibrated=True)["status"] == "verified"


def test_gemma_calibrated_needs_dataset_template(monkeypatch):
    from app.query.schema import ParseResult

    path = "data/cubicasa5k/x/F1_original.png"
    monkeypatch.setattr(router, "parse", lambda q, use_llm=True: ParseResult(query=None, parser="template", confidence=.99))
    assert gemma_calibrated(AskRequest(path=path, question="q")) is True
    monkeypatch.setattr(router, "parse", lambda q, use_llm=True: ParseResult(query=None, parser="rules", confidence=.85))
    assert gemma_calibrated(AskRequest(path=path, question="q")) is False
    monkeypatch.setattr(router, "GEMMA_CALIBRATED_ONLY", False)
    assert gemma_calibrated(AskRequest(path="uploads/0123456789ab/p.png", question="q")) is True
