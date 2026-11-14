"""model.gemma_engine returns dicts that validate as Harry's backend/app/schema.py Answer.

Runs with or without pydantic: the schema check is skipped when backend deps aren't installed.
    python -m pytest tests/test_gemma_engine.py -q      (or: python tests/test_gemma_engine.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from model import gemma_engine as ge  # noqa: E402

try:
    from app.schema import Answer  # type: ignore  # noqa: E402
except Exception:  # noqa: BLE001
    Answer = None


def fake(reply: dict):
    def ask(image, question, model, with_points=False, timeout=60):
        assert not isinstance(image, str) or image.endswith(".png"), image
        return {"ok": True, "abstained": False, "latency_ms": 321, "reason": None, "points": None, **reply}
    return ask


def check(a: dict) -> dict:
    if Answer is not None:
        Answer(**a)
    assert a["status"] in ("verified", "partial", "disagreement", "cannot_verify")
    assert (a["answer"] is None) == (a["status"] == "cannot_verify")
    return a


CC = "data/cubicasa5k/colorful-10052.png"
SW_PDF = "data/swiss_dwellings/site2297_bldg3392_floor15123.pdf"


def test_verified_count_with_points():
    a = check(ge.answer(CC, "How many windows?", engine="gemma_ft", label="none",
                        ask_fn=fake({"answer": 3, "unit": "count", "confidence": 0.999,
                                     "points": [[0.1, 0.2], [0.5, 0.5], [1.2, -0.1]]})))
    assert a["status"] == "verified" and a["answer"] == 3 and a["source"] == "gemma_ft"
    assert [e["shape"]["point"] for e in a["evidence"]] == [[0.1, 0.2], [0.5, 0.5], [1.0, 0.0]]


def test_partial_and_floor():
    a = check(ge.answer(CC, "How many doors?", engine="gemma_base", label="none",
                        ask_fn=fake({"answer": 2, "unit": "count", "confidence": 0.7})))
    assert a["status"] == "partial" and a["source"] == "gemma_base"
    a = check(ge.answer(CC, "How many doors?", engine="gemma_base", label="none",
                        ask_fn=fake({"answer": 2, "unit": "count", "confidence": 0.2})))
    assert a["status"] == "cannot_verify" and a["sources"][0]["answer"] == 2


def test_swiss_pdf_uses_png_twin_and_area_unit():
    a = check(ge.answer(SW_PDF, "What is the total area in m²?", engine="gemma_ft", label="none",
                        ask_fn=fake({"answer": 314.29, "unit": "m2", "confidence": 0.995})))
    assert a["type"] == "area" and a["unit"] == "m2" and a["answer"] == 314.29


def test_no_raster_and_errors():
    a = check(ge.answer("data/ifc_models/foo.ifc", "How many doors?", ask_fn=fake({})))
    assert a["status"] == "cannot_verify"

    def boom(*_a, **_k):
        raise ConnectionError("tunnel down")
    a = check(ge.answer(CC, "How many doors?", ask_fn=boom))
    assert "tunnel down" in a["explanation"]
    a = check(ge.answer(CC, "How many doors?", label="none",
                        ask_fn=fake({"ok": False, "answer": None, "confidence": None})))
    assert a["status"] == "cannot_verify"
    a = check(ge.answer(CC, "How many doors?", label="none",
                        ask_fn=fake({"answer": 2.5, "unit": "count", "confidence": 0.99})))
    assert a["status"] == "cannot_verify"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("schema check:", "on" if Answer else "SKIPPED (no pydantic)")
