"""Score predictions against questions.jsonl.

Rules (dataset README): counts exact; area / length / volume within a relative tolerance
(official: 2%, `--tol`); text answers are free-form and NOT in the headline number (a
normalized exact match is reported separately). `cannot_verify` / null answers and missing
predictions score as wrong, but are tracked separately as abstentions / missing.

Predictions are JSONL with at least {"path", "question", "answer"} and optionally "unit",
"status" — i.e. `Answer` objects from the API, one per line.

    python backend/score.py --gold questions.jsonl --pred preds.jsonl
    python backend/score.py --gold questions.jsonl --pred preds.jsonl --split heldout.txt --json out.json

`--split` is a file of drawing paths, one per line. Drawings are matched by
data/<source>/<stem> ignoring extension, so a held-out .pdf also holds out its .dxf/.png twin.
Only gold questions on held-out drawings are scored.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Tuple

OFFICIAL_TOL = 0.02
STRICT_TOL = 0.01
NUMERIC_TYPES = {"area", "length", "volume"}

# factor to convert a value in `unit` into SI
_TO_SI = {
    "m": 1.0, "m2": 1.0, "m3": 1.0,
    "ft": 0.3048, "ft2": 0.3048 ** 2, "ft3": 0.3048 ** 3,
}
_DIM = {"m": 1, "ft": 1, "m2": 2, "ft2": 2, "m3": 3, "ft3": 3}
_UNIT_ALIASES = {"m²": "m2", "m^2": "m2", "sqm": "m2", "m³": "m3", "m^3": "m3", "ft²": "ft2", "sqft": "ft2", "ft³": "ft3"}


def drawing_key(path: str) -> str:
    """Drawing identity regardless of format: data/<source>/<stem>."""
    p = PurePosixPath(path.strip())
    return str(p.with_suffix(""))


def _norm_unit(u: Optional[str]) -> Optional[str]:
    if u is None:
        return None
    u = str(u).strip().lower()
    return _UNIT_ALIASES.get(u, u)


def to_number(x: Any) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x) if math.isfinite(x) else None
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(x).replace(" ", "").replace(" ", ""))
    if not m:
        return None
    return float(m.group(0).replace(",", "."))


def _convert(value: float, from_unit: Optional[str], to_unit: Optional[str]) -> Optional[float]:
    f, t = _norm_unit(from_unit), _norm_unit(to_unit)
    if f is None or t is None or f == t:
        return value
    if f in _TO_SI and t in _TO_SI and _DIM[f] == _DIM[t]:
        return value * _TO_SI[f] / _TO_SI[t]
    return None  # incompatible units -> wrong


def _norm_text(s: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.]", " ", str(s).lower())).strip()


def score_one(gold: Dict[str, Any], pred: Optional[Dict[str, Any]], tol: float = OFFICIAL_TOL) -> Dict[str, Any]:
    """Score a single prediction. Returns {"correct": bool, "outcome": str, "rel_err": float|None}.

    outcome is one of: correct, wrong, abstain (cannot_verify / null), missing, unit_mismatch, unparseable.
    """
    if pred is None:
        return {"correct": False, "outcome": "missing", "rel_err": None}
    ans = pred.get("answer")
    if ans is None or pred.get("status") == "cannot_verify":
        return {"correct": False, "outcome": "abstain", "rel_err": None}

    gtype = gold["type"]
    if gtype == "text":
        ok = _norm_text(ans) == _norm_text(gold["answer"])
        return {"correct": ok, "outcome": "correct" if ok else "wrong", "rel_err": None}

    p = to_number(ans)
    if p is None:
        return {"correct": False, "outcome": "unparseable", "rel_err": None}
    g = float(gold["answer"])

    if gtype == "count":
        ok = p == g
        return {"correct": ok, "outcome": "correct" if ok else "wrong", "rel_err": (abs(p - g) / g) if g else None}

    p_conv = _convert(p, pred.get("unit"), gold.get("unit"))
    if p_conv is None:
        return {"correct": False, "outcome": "unit_mismatch", "rel_err": None}
    if g == 0:
        ok = abs(p_conv) < 1e-9
        rel = None
    else:
        rel = abs(p_conv - g) / abs(g)
        ok = rel <= tol + 1e-12
    return {"correct": ok, "outcome": "correct" if ok else "wrong", "rel_err": rel}


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _bucket() -> Dict[str, Any]:
    return {"n": 0, "correct": 0, "answered": 0, "answered_correct": 0, "strict_correct": 0, "outcomes": defaultdict(int)}


def _finish(b: Dict[str, Any]) -> Dict[str, Any]:
    n, a = b["n"], b["answered"]
    return {
        "n": n,
        "accuracy": b["correct"] / n if n else None,
        "accuracy_strict_1pct": b["strict_correct"] / n if n else None,
        "coverage": a / n if n else None,
        "precision": b["answered_correct"] / a if a else None,  # accuracy among answered
        "outcomes": dict(b["outcomes"]),
    }


def score(gold: Iterable[Dict[str, Any]], preds: Iterable[Dict[str, Any]], tol: float = OFFICIAL_TOL,
          split: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    pred_idx: Dict[Tuple[str, str], Dict[str, Any]] = {(p["path"], p["question"]): p for p in preds}
    keep = {drawing_key(s) for s in split} if split is not None else None

    buckets: Dict[str, Dict[str, Any]] = defaultdict(_bucket)
    text = _bucket()
    rel_errs: List[float] = []
    for g in gold:
        if keep is not None and drawing_key(g["path"]) not in keep:
            continue
        pred = pred_idx.get((g["path"], g["question"]))
        r = score_one(g, pred, tol)
        if g["type"] == "text":
            targets = [text]
        else:
            parts = PurePosixPath(g["path"]).parts
            src = parts[1] if len(parts) > 2 else "?"
            ext = PurePosixPath(g["path"]).suffix.lstrip(".")
            targets = [buckets["overall"], buckets[f"type/{g['type']}"], buckets[f"source/{src}"], buckets[f"ext/{ext}"]]
            if r["rel_err"] is not None and g["type"] in NUMERIC_TYPES:
                rel_errs.append(r["rel_err"])
        strict = r if tol <= STRICT_TOL else score_one(g, pred, STRICT_TOL)
        answered = r["outcome"] not in ("abstain", "missing")
        for b in targets:
            b["n"] += 1
            b["correct"] += r["correct"]
            b["strict_correct"] += strict["correct"]
            b["answered"] += answered
            b["answered_correct"] += answered and r["correct"]
            b["outcomes"][r["outcome"]] += 1

    rel_errs.sort()
    out = {k: _finish(v) for k, v in sorted(buckets.items(), key=lambda kv: (kv[0] != "overall", kv[0]))}
    out["text_exact_match(unscored)"] = _finish(text)
    out["_meta"] = {
        "tolerance": tol,
        "numeric_median_rel_err": rel_errs[len(rel_errs) // 2] if rel_errs else None,
        "n_predictions": len(pred_idx),
    }
    return out


def _fmt(x: Optional[float]) -> str:
    return "   -  " if x is None else f"{100 * x:5.1f}%"


def print_report(res: Dict[str, Any], file=sys.stdout) -> None:
    print(f"{'bucket':32} {'n':>7}  {'acc':>6}  {'acc@1%':>6}  {'cover':>6}  {'prec':>6}", file=file)
    for k, v in res.items():
        if k.startswith("_"):
            continue
        print(f"{k:32} {v['n']:7d}  {_fmt(v['accuracy'])}  {_fmt(v['accuracy_strict_1pct'])}  "
              f"{_fmt(v['coverage'])}  {_fmt(v['precision'])}", file=file)
    m = res["_meta"]
    med = m["numeric_median_rel_err"]
    med_s = "-" if med is None else format(med, ".2%")
    print(f"\ntolerance={m['tolerance']:.0%}  predictions={m['n_predictions']}  median numeric rel err={med_s}", file=file)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", required=True, help="questions.jsonl")
    ap.add_argument("--pred", required=True, help="predictions JSONL (Answer objects)")
    ap.add_argument("--split", help="file of held-out drawing paths, one per line")
    ap.add_argument("--tol", type=float, default=OFFICIAL_TOL, help="relative tolerance for area/length/volume (default 0.02)")
    ap.add_argument("--json", help="also write full results JSON here")
    a = ap.parse_args(argv)

    split = None
    if a.split:
        with open(a.split, encoding="utf-8") as f:
            split = [l for l in f if l.strip()]
    res = score(read_jsonl(a.gold), read_jsonl(a.pred), a.tol, split)
    print_report(res)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
