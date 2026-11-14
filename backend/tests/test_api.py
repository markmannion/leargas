import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main, drawings
from app.schema import Answer


@pytest.fixture
def client(tmp_path, monkeypatch):
    q = tmp_path / "questions.jsonl"
    q.write_text(json.dumps({"path": "data/cubicasa5k/x.png", "question": "How many windows?",
                             "answer": 7, "unit": "count", "type": "count"}) + "\n")
    monkeypatch.setenv("LEARGAS_QUESTIONS", str(q))
    monkeypatch.setenv("LEARGAS_MOCK", "1")
    main._gold.cache_clear()
    yield TestClient(main.app)
    main._gold.cache_clear()


def test_health(client):
    assert client.get("/health").json()["gold_questions_loaded"] == 1


def test_ask_known(client):
    r = client.post("/ask", json={"path": "data/cubicasa5k/x.png", "question": "How many windows?"}).json()
    a = Answer.model_validate(r)
    assert a.answer == 7 and a.status == "verified" and len(a.evidence) == 7
    for e in r["evidence"]:
        x, y = e["shape"]["point"]
        assert 0 <= x <= 1 and 0 <= y <= 1


def test_ask_unknown_is_cannot_verify(client):
    r = client.post("/ask", json={"path": "data/cubicasa5k/x.png", "question": "What is the kitchen area in m²?"}).json()
    assert r["status"] == "cannot_verify" and r["answer"] is None and r["type"] == "area"


def test_schema_endpoint(client):
    assert "properties" in client.get("/schema").json()["answer"]


@pytest.mark.parametrize("bbox", [[.5, .1, .4, .8], [.1, .1, .1, .8], [-.1, 0, .5, .5], [0, 0, 1.1, 1]])
def test_region_rejects_invalid_bounds(client, bbox):
    response = client.post("/ask", json={"path": "data/cubicasa5k/x.png", "question": "How many windows?",
                                         "region": {"bbox": bbox}})
    assert response.status_code == 422


def test_region_mock_does_not_reuse_whole_sheet_gold(client):
    response = client.post("/ask", json={"path": "data/cubicasa5k/x.png", "question": "How many windows?",
                                         "region": {"bbox": [.1, .1, .5, .5]}})
    assert response.json()["answer"] is None
    assert response.json()["region"]["bbox"] == [.1, .1, .5, .5]


def test_drawing_catalogue_pagination_reaches_last_plan(client, monkeypatch):
    catalogue = [{"path": f"data/plan-{index}.png"} for index in range(7)]
    monkeypatch.setattr(drawings, "_catalogue", lambda: catalogue)
    result = client.get("/drawings?limit=3&offset=6").json()
    assert result["total"] == 7 and result["drawings"] == [catalogue[-1]]
    assert client.get("/drawings?offset=7").json()["drawings"] == []
    assert client.get("/drawings?offset=-1").status_code == 422


def _base(**kw):
    d = {"path": "p", "question": "q", "answer": 3, "unit": "count", "type": "count",
         "status": "verified", "confidence": 0.9, "source": "geometry_dxf"}
    d.update(kw)
    return d


@pytest.mark.parametrize("bad", [
    {"status": "cannot_verify"},                      # answer must be null
    {"answer": None},                                 # null answer needs cannot_verify
    {"answer": 2.5},                                  # count must be integer
    {"evidence": [{"shape": {"kind": "point", "point": [1.2, 0.5]}}]},           # out of [0,1]
    {"evidence": [{"shape": {"kind": "bbox", "bbox": [0.5, 0.5, 0.4, 0.6]}}]},   # x1 < x0
    {"evidence": [{"shape": {"kind": "polygon", "points": [[0, 0], [1, 1]]}}]},  # < 3 points
])
def test_schema_rejects(bad):
    with pytest.raises(ValidationError):
        Answer.model_validate(_base(**bad))
