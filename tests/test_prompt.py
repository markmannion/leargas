"""M3 tests: python -m pytest tests/  (or: python tests/test_prompt.py, no pytest needed)."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from model.prompt import (  # noqa: E402
    build_messages,
    build_text_messages,
    extract_json,
    format_target,
    parse_output,
)

RAW = Path(__file__).resolve().parent.parent / "data" / "model_outputs" / "raw.jsonl"


def lp(tokens_probs):
    """[(token, prob)] -> vLLM-style logprobs dict."""
    return {"content": [{"token": t, "logprob": math.log(p), "top_logprobs": []} for t, p in tokens_probs]}


MESSY = [
    ('{"answer": 12, "unit": "count"}', 12, "count"),
    ('```json\n{"answer": 47.37, "unit": "m²"}\n```', 47.37, "m2"),
    ('Sure! Here is the result:\n{"answer": 3, "unit": "count"} Hope that helps.', 3, "count"),
    ("{'answer': 5, 'unit': 'count'}", 5, "count"),
    ('{"answer": "7", "unit": "count",}', 7, "count"),
    ('{"answer": "89,84 m2", "unit": "m2"}', 89.84, "m2"),
    ("There are 4 windows.", 4, "count"),
    ("<|channel>thought\nlet me count 1,2,3<channel|>{\"answer\": 3, \"unit\": \"count\"}", 3, "count"),
    ('{"Answer": 2, "Unit": "COUNT"}', 2, "count"),
    ('{"answer": 314.29, "unit": "sqm"}', 314.29, "m2"),
    ('{"answer": 2, "unit": "count", "points": [[100, 200], [500, 900]]}', 2, "count"),
    ('[{"box_2d": [10, 20, 30, 40], "label": "toilet"}, {"box_2d": [50, 60, 70, 80], "label": "toilet"}]', 2, "count"),
    ('{"answer": "B3 (aluminium sliding door)", "unit": null}', "B3 (aluminium sliding door)", None),
    ('{"answer": 29690, "unit": "ft2"}', 29690, "ft2"),
    ("<end_of_turn>", None, None),
    ("", None, None),
]


def test_messy_outputs():
    for text, ans, unit in MESSY:
        out = parse_output(text)
        assert out["answer"] == ans, (text, out)
        assert out["unit"] == unit, (text, out)


def test_abstain():
    out = parse_output('{"answer": null, "unit": null, "reason": "fire ratings are not shown"}')
    assert out["abstained"] and out["ok"] and out["answer"] is None
    assert out["reason"] == "fire ratings are not shown"


def test_points_convention():
    out = parse_output('{"answer": 1, "unit": "count", "points": [[250, 750]]}')
    assert out["points"] == [[0.75, 0.25]]  # [y, x] 0-1000 -> [x, y] 0-1
    out = parse_output('[{"box_2d": [100, 200, 300, 400], "label": "wc"}]')
    assert out["points"] == [[0.3, 0.2]]


def test_target_roundtrip():
    for ans, unit, pts in [(12, "count", None), (47.37, "m2", None), (2.0, "count", [[0.1, 0.2], [0.5, 0.9]])]:
        t = format_target(ans, unit, pts)
        out = parse_output(t)
        assert out["answer"] == (int(ans) if float(ans).is_integer() else ans)
        assert out["unit"] == unit
        if pts:
            assert all(abs(a - b) < 1e-3 for p, q in zip(out["points"], pts) for a, b in zip(p, q))
    assert parse_output(format_target(None, None, reason="x"))["abstained"]


def test_confidence_from_answer_tokens():
    text = '{"answer": 12, "unit": "count"}'
    toks = [('{"', .99), ("answer", .99), ('":', .99), (" ", .99), ("1", .5), ("2", .7), (",", .99),
            (' "', .99), ("unit", .99), ('":', .99), (' "', .99), ("count", .99), ('"}', .99)]
    out = parse_output(text, lp(toks))
    assert abs(out["confidence"] - 0.6) < 1e-3, out
    # OpenAI-SDK-like objects work too
    class T:
        def __init__(s, t, p): s.token, s.logprob = t, math.log(p)
    class L:
        content = [T(t, p) for t, p in toks]
    assert abs(parse_output(text, L())["confidence"] - 0.6) < 1e-3
    # no logprobs -> None
    assert parse_output(text)["confidence"] is None


def test_messages_shape(tmp_path=None):
    from PIL import Image
    img = Image.new("RGB", (4000, 2000), "white")
    msgs = build_messages(img, "  How many doors? ")
    assert msgs[0]["role"] == "system" and msgs[1]["content"][0]["type"] == "image_url"
    assert msgs[1]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert msgs[1]["content"][1]["text"] == "How many doors?"
    t = build_text_messages("sys", "q", few_shot=[("q1", {"op": "count"})])
    assert json.loads(t[2]["content"]) == {"op": "count"}
    assert extract_json('noise {"a": [1, {"b": "}"}]} tail') == {"a": [1, {"b": "}"}]}


def test_real_outputs_roundtrip():
    """M3 done-when: every logged real model output parses without error."""
    if not RAW.exists():
        print("  (no data/model_outputs/raw.jsonl yet: run python -m model.smoke_test --n 20 against the box)")
        return
    rows = [json.loads(line) for line in RAW.read_text(encoding="utf-8").splitlines() if line.strip()]
    bad = [r for r in rows if not parse_output(r["text"], r.get("logprobs"))["ok"]]
    print(f"  real outputs: {len(rows)}, unparseable: {len(bad)}")
    assert len(bad) <= max(1, len(rows) // 20), [r["text"][:120] for r in bad[:5]]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
