"""Scoring adapter. Uses Harry's eval/score.py (contract C2) when it exists, else a local copy
of the same rules so baselines can run before 10:00:

- counts: exact match
- area / length / volume: within 2% relative error (|pred - gold| <= 0.02 * |gold|)
- unit must match exactly (after normalising m² -> m2 etc.)
- text answers: reported separately (normalised exact match here is only a rough signal)
- abstained (answer None / cannot_verify): "abstained", not wrong

score(pred, gold) -> "correct" | "wrong" | "abstained" | "text"
"""
from __future__ import annotations

import collections
import re
from typing import Any

from .prompt import normalize_unit

REL_TOL = 0.02

try:  # Harry's scorer wins when it lands (C2, Sat 10:00)
    from eval import score as _harry  # type: ignore

    _HARRY = getattr(_harry, "score_one", None) or getattr(_harry, "score_answer", None)
except Exception:  # noqa: BLE001
    _HARRY = None


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(x))
    return float(m.group(0).replace(",", ".")) if m else None


def local_score(pred_answer: Any, pred_unit: Any, gold: dict, abstained: bool = False) -> str:
    if abstained or pred_answer is None:
        return "abstained"
    gtype = gold.get("type")
    if gtype == "text":
        a = re.sub(r"\W+", " ", str(pred_answer)).strip().lower()
        b = re.sub(r"\W+", " ", str(gold["answer"])).strip().lower()
        return "text" if a != b else "correct"
    if normalize_unit(pred_unit) != normalize_unit(gold.get("unit")):
        return "wrong"
    p, g = _num(pred_answer), _num(gold["answer"])
    if p is None or g is None:
        return "wrong"
    if gtype == "count":
        return "correct" if p == g else "wrong"
    return "correct" if abs(p - g) <= REL_TOL * abs(g) + 1e-9 else "wrong"


def score(pred_answer: Any, pred_unit: Any, gold: dict, abstained: bool = False) -> str:
    if _HARRY is not None:
        try:
            r = _HARRY({"answer": pred_answer, "unit": pred_unit, "cannot_verify": abstained}, gold)
            if isinstance(r, bool):
                return "correct" if r else ("abstained" if abstained or pred_answer is None else "wrong")
            if isinstance(r, str):
                return r
        except Exception:  # noqa: BLE001  fall back rather than crash a 1,000-question run
            pass
    return local_score(pred_answer, pred_unit, gold, abstained)


def summarize(rows: list[dict], key=lambda r: f"{r['source']}/{r['type']}") -> dict:
    """rows: dicts with 'source', 'type', 'outcome'. -> {group: {n, correct, wrong, abstained, acc, acc_answered, abstain_rate}}"""
    groups: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in rows:
        for k in (key(r), "ALL"):
            groups[k][r["outcome"]] += 1
            groups[k]["n"] += 1
    out = {}
    for k, c in sorted(groups.items()):
        answered = c["correct"] + c["wrong"]
        out[k] = {
            "n": c["n"], "correct": c["correct"], "wrong": c["wrong"], "abstained": c["abstained"], "text": c["text"],
            "acc": round(c["correct"] / c["n"], 4) if c["n"] else None,
            "acc_answered": round(c["correct"] / answered, 4) if answered else None,
            "abstain_rate": round(c["abstained"] / c["n"], 4) if c["n"] else None,
        }
    return out
