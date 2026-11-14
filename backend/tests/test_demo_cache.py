import json

import pytest
from fastapi.testclient import TestClient

import demo_cache as cli
from app import demo_cache, main
from app.schema import Answer

PATH = "data/swiss_dwellings/site1_bldg1_floor1.pdf"
Q = "How many windows are drawn on this floor plan?"


def _answer(path=PATH, question=Q, answer=12, status="verified", **kw):
    d = {"path": path, "question": question, "answer": answer, "unit": "count" if answer is not None else None,
         "type": "count", "status": status, "confidence": 0.95 if answer is not None else 0.0,
         "source": "geometry_dxf", "evidence": [{"shape": {"kind": "point", "point": [0.5, 0.5]}, "page": 0,
                                                 "label": "window", "value": None, "source": "geometry_dxf"}],
         "explanation": "12 windows.", "sources": [], "latency_ms": 42.0}
    d.update(kw)
    return Answer.model_validate(d).model_dump(mode="json")


def test_key_normalization():
    a = demo_cache.make_key(PATH, Q, None)
    assert a == demo_cache.make_key("./" + PATH, "  how many   WINDOWS are drawn on this floor plan? ", "auto")
    assert a == demo_cache.make_key("/abs/datasets/junction-dataset/" + PATH, Q, "AUTO")
    assert a == demo_cache.make_key(PATH.replace("/", "\\"), Q, "auto")
    assert a != demo_cache.make_key(PATH, Q, "geometry")
    assert a != demo_cache.make_key(PATH, "How many doors are drawn on this floor plan?", None)
    # NFKC: a compatibility superscript and a plain digit normalize the same way
    assert demo_cache.norm_question("area in m²") == demo_cache.norm_question("area in m2")


@pytest.fixture
def cache_file(tmp_path, monkeypatch):
    p = tmp_path / "demo_cache.json"
    ans = _answer()
    k = demo_cache.key_str(demo_cache.make_key(PATH, Q, "auto"))
    demo_cache.write(p, {"version": 1, "entries": {k: {"path": PATH, "question": Q, "engine": "auto", "answer": ans}}})
    monkeypatch.setenv("LEARGAS_DEMO_CACHE_PATH", str(p))
    monkeypatch.setenv("LEARGAS_MOCK", "1")  # misses go to the mock, so no engines are needed
    monkeypatch.setenv("LEARGAS_QUESTIONS", str(tmp_path / "none.jsonl"))
    main._gold.cache_clear()
    yield ans
    main._gold.cache_clear()


def test_hit_returns_cached_answer(cache_file, monkeypatch):
    monkeypatch.setenv("LEARGAS_DEMO_CACHE", "1")
    c = TestClient(main.app)
    r = c.post("/ask", json={"path": PATH, "question": Q})
    assert r.headers["x-leargas-cache"] == "hit"
    assert r.json() == cache_file
    r = c.post("/ask", json={"path": "./" + PATH, "question": Q.upper(), "engine": "auto"})
    assert r.headers["x-leargas-cache"] == "hit"
    assert r.json()["answer"] == 12 and r.json()["question"] == Q.upper()  # echoes the request
    assert c.get("/health").json()["demo_cache"]["entries"] == 1


def test_miss_falls_through(cache_file, monkeypatch):
    monkeypatch.setenv("LEARGAS_DEMO_CACHE", "1")
    c = TestClient(main.app)
    for body in ({"path": PATH, "question": "How many doors?"}, {"path": PATH, "question": Q, "engine": "gemma_ft"}):
        r = c.post("/ask", json=body)
        assert r.headers["x-leargas-cache"] == "miss"
        assert r.json()["source"] == "mock"


def test_disabled_ignores_cache(cache_file, monkeypatch):
    monkeypatch.delenv("LEARGAS_DEMO_CACHE", raising=False)
    r = TestClient(main.app).post("/ask", json={"path": PATH, "question": Q})
    assert "x-leargas-cache" not in r.headers and r.json()["source"] == "mock"
    assert "demo_cache" not in TestClient(main.app).get("/health").json()


def test_missing_cache_file_is_all_misses(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARGAS_DEMO_CACHE_PATH", str(tmp_path / "nope.json"))
    assert demo_cache.lookup(PATH, Q, None) is None


def test_build_stores_answers_and_skips_abstentions(tmp_path):
    out = tmp_path / "c.json"
    rows = [
        {"path": PATH, "question": Q, "answer": 12, "unit": "count", "type": "count"},
        {"path": PATH, "question": "How many doors?", "answer": 4, "unit": "count", "type": "count"},
        {"path": PATH, "question": "Fire rating?", "expected": "cannot_verify", "answer": None, "type": "unanswerable"},
    ]

    def ask(body):
        if body["question"] == Q:
            return _answer(question=Q)
        return _answer(question=body["question"], answer=None, status="cannot_verify", evidence=[])

    st = cli.build(rows, ask, out, ["auto", "geometry"])
    assert (st["asked"], st["stored"], st["skipped"], st["correct"], st["scored"]) == (6, 4, 2, 2, 4)
    entries = demo_cache.read(out)["entries"]
    assert demo_cache.key_str(demo_cache.make_key(PATH, Q, "geometry")) in entries
    assert demo_cache.key_str(demo_cache.make_key(PATH, "How many doors?", "auto")) not in entries
    assert entries[demo_cache.key_str(demo_cache.make_key(PATH, "Fire rating?", "auto"))]["answer"]["status"] == "cannot_verify"

    # a later cannot_verify never replaces a stored answer, even with --keep-cannot-verify
    st = cli.build(rows[:1], lambda b: _answer(answer=None, status="cannot_verify", evidence=[]), out, ["auto"],
                   keep_cannot_verify=True)
    assert st["stored"] == 0
    assert demo_cache.read(out)["entries"][demo_cache.key_str(demo_cache.make_key(PATH, Q, "auto"))]["answer"]["answer"] == 12


def test_build_row_engine_overrides_and_errors(tmp_path):
    out = tmp_path / "c.json"

    def ask(body):
        if body["engine"] == "gemma_ft":
            raise RuntimeError("endpoint down")
        return _answer()

    st = cli.build([{"path": PATH, "question": Q, "engine": "geometry"},
                    {"path": PATH, "question": "x", "engine": "gemma_ft"}], ask, out, ["auto"])
    assert st["errors"] == 1 and st["stored"] == 1
    assert list(demo_cache.read(out)["entries"]) == [demo_cache.key_str(demo_cache.make_key(PATH, Q, "geometry"))]


def test_load_questions_json_and_jsonl(tmp_path):
    j = tmp_path / "q.json"
    j.write_text(json.dumps([{"drawing": PATH, "question": Q, "engine": "geometry"}]))
    assert cli.load_questions(j)[0]["path"] == PATH
    jl = tmp_path / "q.jsonl"
    jl.write_text(json.dumps({"path": PATH, "question": Q}) + "\n\n")
    assert len(cli.load_questions(jl)) == 1
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"question": Q}) + "\n")
    with pytest.raises(SystemExit):
        cli.load_questions(bad)


def test_default_set_is_well_formed():
    assert len(cli.DEFAULT_SET) >= 8
    assert {r["type"] for r in cli.DEFAULT_SET} == {"count", "area"}
    assert any("swiss_dwellings" in r["path"] for r in cli.DEFAULT_SET)
    assert any("ifc_models" in r["path"] for r in cli.DEFAULT_SET)
