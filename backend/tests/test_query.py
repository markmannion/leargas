import json

import httpx
import pytest

from app.query import llm, parser
from app.query.build_templates import build
from app.query.normalize import normalize
from app.query.rules import parse_english


def d(q):
    return None if q is None else q.model_dump(exclude_defaults=True)


# ---------- normalize ----------

@pytest.mark.parametrize("q,tmpl,args", [
    ("Rooms labelled 'Küche' here?", "Rooms labelled <S> here?", [("S", "Küche")]),
    ("Räume «Bad» und „Flur“?", "Räume <S> und <S>?", [("S", "Bad"), ("S", "Flur")]),
    ("Room 7.01 ('Balkon') area", "Room <N> (<S>) area", [("N", "7.01"), ("S", "Balkon")]),
    ("Room U1.03 area", "Room <N> area", [("N", "U1.03")]),
    ("Area of apartment B in m²", "Area of apartment <L> in m²", [("L", "B")]),
    ("rooms labelled 'l'escalier' here", "rooms labelled <S> here", [("S", "l'escalier")]),
    ("Combien d'appartements ?", "Combien d'appartements ?", []),
    ("walls on 'Level 1'", "walls on <S>", [("S", "Level 1")]),  # number inside quotes stays in the arg
])
def test_normalize(q, tmpl, args):
    assert normalize(q) == (tmpl, args)


# ---------- English rules ----------

@pytest.mark.parametrize("q,expected", [
    ("How many windows are there?", {"op": "count", "target": "window", "unit": "count"}),
    ("How many doors does this plan have?", {"op": "count", "target": "door", "unit": "count"}),
    ("How many showers and bathtubs are there in total?", {"op": "count", "target": "shower_or_bathtub", "unit": "count"}),
    ("How many sinks and wash basins (kitchen included) are drawn?", {"op": "count", "target": "sink_or_washbasin", "unit": "count"}),
    ("How many toilet bowls are drawn?", {"op": "count", "target": "toilet", "unit": "count"}),
    ("How many separate WC rooms are there?", {"op": "count", "target": "room", "room_type": "wc", "unit": "count"}),
    ("How many bedrooms are on this floor plan?", {"op": "count", "target": "room", "room_type": "bedroom", "unit": "count"}),
    ("How many floors does this plan show?", {"op": "count", "target": "storey", "unit": "count"}),
    ("How many rooms labelled 'Zimmer' are on this floor?",
     {"op": "count", "target": "room", "label": "Zimmer", "unit": "count"}),
    ("What is the net floor area of room 3.02 ('Bad') in m²?",
     {"op": "area", "target": "room", "room_id": "3.02", "label": "Bad", "unit": "m2"}),
    ("What is the net floor area of apartment C in m², excluding balconies?",
     {"op": "area", "target": "apartment", "apartment": "C", "exclude_outdoor": True, "unit": "m2"}),
    ("What is the total net floor area in m² of all numbered indoor rooms on this floor?",
     {"op": "area", "target": "room", "numbered_only": True, "unit": "m2"}),
    ("What is the net floor area of the room 'Office (101)' on 'Ground Floor', in m²?",
     {"op": "area", "target": "room", "scope": "level", "name": "Office (101)", "level": "Ground Floor", "unit": "m2"}),
    ("How many columns are shown on the floor plan of 'Level 2'?",
     {"op": "count", "target": "column", "scope": "level", "level": "Level 2", "unit": "count"}),
    ("How many beams are there in the model 'Tower'?",
     {"op": "count", "target": "beam", "scope": "model", "model": "Tower", "unit": "count"}),
    ("What is the total length of all walls on 'Plan 1', in metres?",
     {"op": "length", "target": "wall", "scope": "level", "level": "Plan 1", "unit": "m"}),
    ("What is the total net side area of all walls on 'Plan 1', in m²?",
     {"op": "area", "target": "wall", "scope": "level", "level": "Plan 1", "side_area": True, "unit": "m2"}),
    ("What is the total net volume of all slabs on 'Basement', in m³?",
     {"op": "volume", "target": "slab", "scope": "level", "level": "Basement", "unit": "m3"}),
    ("What is the total area of all rooms on this plan in square feet?",
     {"op": "area", "target": "room", "unit": "ft2"}),
])
def test_rules(q, expected):
    assert d(parse_english(q)) == expected


@pytest.mark.parametrize("q", [
    "Which materials are used in the exterior walls?",
    "What is the total length of exterior walls?",
    "Which room is the largest?",
    "What are all the spaces on level 2, with their areas?",
    "Who designed this building?",
    "How many numbered indoor things are there?",  # 'indoor' must not match 'door'
])
def test_rules_refuse(q):
    assert parse_english(q) is None


# ---------- translation table ----------

QUESTIONS = [
    {"path": "data/x/a.pdf", "question": "How many windows are drawn on this floor plan?", "answer": 4, "unit": "count", "type": "count"},
    {"path": "data/x/a.pdf", "question": "Wie viele Fenster sind auf diesem Grundriss?", "answer": 4, "unit": "count", "type": "count"},
    {"path": "data/x/a.pdf", "question": "What is the net floor area of the room 'Kitchen' on 'Level 1', in m²?", "answer": 9.5, "unit": "m2", "type": "area"},
    # translation with the quoted args in the opposite order
    {"path": "data/x/a.pdf", "question": "Auf «Level 1»: wie gross ist der Raum «Kitchen» in m²?", "answer": 9.5, "unit": "m2", "type": "area"},
    {"path": "data/x/a.pdf", "question": "Which software was used?", "answer": "Revit", "unit": None, "type": "text"},
]


@pytest.fixture
def table(tmp_path, monkeypatch):
    qf = tmp_path / "q.jsonl"
    qf.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in QUESTIONS), encoding="utf-8")
    tbl, stats = build(str(qf))
    out = tmp_path / "t.json"
    out.write_text(json.dumps({"stats": stats, "templates": tbl}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("LEARGAS_QUERY_TEMPLATES", str(out))
    monkeypatch.delenv("LEARGAS_LLM_BASE_URL", raising=False)
    parser.templates.cache_clear()
    yield stats
    parser.templates.cache_clear()


def test_build_stats(table):
    assert table["templates_en"] == 2 and table["templates_translated"] == 2 and table["covered"] == 4


def test_translated_template(table):
    r = parser.parse("Wie viele Fenster sind auf diesem Grundriss?")
    assert r.parser == "template" and d(r.query) == {"op": "count", "target": "window", "unit": "count"}


def test_translated_args_reordered(table):
    r = parser.parse("Auf «Ground»: wie gross ist der Raum «Bath» in m²?")
    assert r.parser == "template"
    assert d(r.query) == {"op": "area", "target": "room", "scope": "level", "name": "Bath", "level": "Ground", "unit": "m2"}


def test_unseen_english_uses_rules(table):
    r = parser.parse("How many bathtubs are there?")
    assert r.parser == "rules" and r.query.target == "bathtub"


def test_unparseable_without_llm(table):
    r = parser.parse("Wie viele Badewannen gibt es?")
    assert r.query is None and r.parser == "none" and "not configured" in r.reason


# ---------- LLM fallback ----------

def _client(reply: str, seen: list):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_llm_parse_output():
    q = llm.parse_output('Sure:\n{"query": {"op": "count", "target": "bathtub", "unit": "count"}}')
    assert q.target == "bathtub"
    assert llm.parse_output('{"query": null}') is None
    with pytest.raises(ValueError):
        llm.parse_output('{"query": {"op": "count", "target": "spaceship"}}')
    with pytest.raises(ValueError):
        llm.parse_output("no json here")


def test_llm_request(monkeypatch):
    monkeypatch.setenv("LEARGAS_LLM_BASE_URL", "http://llm.test/v1")
    seen = []
    q = llm.parse_with_llm("Wie viele Badewannen gibt es?",
                           client=_client('{"query": {"op": "count", "target": "bathtub", "unit": "count"}}', seen))
    assert q.target == "bathtub"
    assert seen[0]["model"] == "gemma-base" and seen[0]["messages"][-1]["content"] == "Wie viele Badewannen gibt es?"


def test_parser_falls_back_to_llm(table, monkeypatch):
    monkeypatch.setenv("LEARGAS_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setattr(llm, "parse_with_llm", lambda q: llm.parse_output('{"query": {"op": "count", "target": "bathtub"}}'))
    r = parser.parse("Wie viele Badewannen gibt es?")
    assert r.parser == "llm" and r.confidence == parser.CONF_LLM and r.query.target == "bathtub"


def test_parser_llm_error_degrades(table, monkeypatch):
    monkeypatch.setenv("LEARGAS_LLM_BASE_URL", "http://llm.test/v1")

    def boom(q):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(llm, "parse_with_llm", boom)
    r = parser.parse("Wie viele Badewannen gibt es?")
    assert r.query is None and r.parser == "none" and "LLM parse failed" in r.reason


def test_llm_outage_skips_inference_but_local_rules_work(table, monkeypatch):
    monkeypatch.setenv("LEARGAS_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setattr(llm.gemma_status, "status", lambda *args, **kw: {"status": "unavailable", "available": False})

    def unexpected(*args, **kwargs):
        pytest.fail("Offline parser must not make an inference request")

    monkeypatch.setattr(llm.httpx, "Client", unexpected)
    r = parser.parse("How many windows are there?")
    assert r.query.target == "window" and r.parser == "rules"
    r = parser.parse("Wie viele Badewannen gibt es?")
    assert r.query is None and "temporarily unavailable" in r.reason


def test_llm_inference_timeout_starts_cooldown(monkeypatch):
    monkeypatch.setenv("LEARGAS_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LEARGAS_LLM_API_KEY", "parser-key")
    monkeypatch.setattr(llm.gemma_status, "status", lambda *args, **kw: {"available": True})
    failures = []
    monkeypatch.setattr(llm.gemma_status, "failed", lambda *args, **kw: failures.append((args, kw)))
    client_class = httpx.Client

    def timeout(req):
        raise httpx.ReadTimeout("private upstream details")

    monkeypatch.setattr(llm.httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(timeout)))
    with pytest.raises(RuntimeError, match="temporarily unavailable") as exc:
        llm.parse_with_llm("Wie viele Badewannen gibt es?")
    assert "private" not in str(exc.value)
    assert failures == [(("gemma-base",), {"url": "http://llm.test/v1", "key": "parser-key"})]
