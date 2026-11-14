import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.schema import Answer


@pytest.fixture
def client(tmp_path, monkeypatch):
    q = tmp_path / "questions.jsonl"
    q.write_text(json.dumps({"path": "data/cubicasa5k/x.png", "question": "How many windows?",
                             "answer": 7, "unit": "count", "type": "count"}) + "\n")
    monkeypatch.setenv("LEARGAS_QUESTIONS", str(q))
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
