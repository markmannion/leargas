"""Model-level confidence calibration from cached predictions (results/preds/<label>__<set>.jsonl).

    python -m model.calibrate --label gemma-base            # -> results/calibration_gemma-base.json
    python -m model.calibrate --label gemma-ft --target 0.95

For each slice (ALL, and source/type) it reports:
  - accuracy per confidence bucket (the reliability curve, for the slide)
  - the lowest threshold t such that answers with confidence >= t are >= `target` correct
    (with at least `min_n` answers kept), and the coverage it leaves
  - the "error modes" that matter for the write-up: most common answers, and for areas the
    median ratio pred/gold (systematic under-reading shows up here)

model/gemma_engine.py reads `thresholds` from this file to decide verified / partial / cannot_verify.
This is the raster model alone; Harry's H7 calibration covers the routed end-to-end system.
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
from pathlib import Path

from .baseline_eval import load_set, score_rows
from .common import REPO_ROOT, load_jsonl, load_questions

RESULTS = REPO_ROOT / "results"
BUCKETS = [0.0, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0001]


def _threshold(items: list[tuple[float, bool]], target: float, min_n: int) -> dict:
    """Lowest t with precision(conf >= t) >= target, keeping >= min_n answers."""
    items = sorted(items, key=lambda x: -x[0])
    best = None
    correct = 0
    for i, (c, ok) in enumerate(items, 1):
        correct += ok
        # only cut between distinct confidence values
        if i < len(items) and items[i][0] == c:
            continue
        if i >= min_n and correct / i >= target:
            best = {"threshold": round(c, 4), "kept": i, "precision": round(correct / i, 4),
                    "coverage": round(i / len(items), 4)}
    return best or {"threshold": None, "kept": 0, "precision": None, "coverage": 0.0}


def _buckets(items: list[tuple[float, bool]]) -> list[dict]:
    out = []
    for lo, hi in zip(BUCKETS, BUCKETS[1:]):
        b = [ok for c, ok in items if lo <= c < hi]
        if b:
            out.append({"lo": lo, "hi": min(hi, 1.0), "n": len(b), "acc": round(sum(b) / len(b), 4)})
    return out


def calibrate(label: str, sets: list[str], target: float, min_n: int) -> dict:
    questions = load_questions()
    out: dict = {"label": label, "target_precision": target, "sets": {}, "thresholds": {}}
    pooled: dict[str, list[tuple[float, bool]]] = collections.defaultdict(list)
    for set_name in sets:
        cache = RESULTS / "preds" / f"{label}__{set_name}.jsonl"
        if not cache.exists():
            continue
        rows = load_set(set_name, questions)
        by_id = {p["id"]: p for p in load_jsonl(cache)}
        rows = [r for r in rows if r["id"] in by_id]
        preds = [by_id[r["id"]] for r in rows]
        scored = score_rows(rows, preds)

        slices: dict[str, list] = collections.defaultdict(list)
        for r, p, s in zip(rows, preds, scored):
            if s["outcome"] in ("abstained", "text") or p.get("confidence") is None:
                continue
            ok = s["outcome"] == "correct"
            for k in ("ALL", f"{s['source']}/{s['type']}"):
                slices[k].append((r, p, ok))

        rep = {}
        for k, trip in sorted(slices.items()):
            items = [(p["confidence"], ok) for _, p, ok in trip]
            pooled[k].extend(items)
            ans = collections.Counter(str(p.get("answer")) for _, p, _ in trip).most_common(5)
            gold = collections.Counter(str(r.get("answer")) for r, _, _ in trip).most_common(5)
            entry = {
                "n": len(items),
                "acc": round(sum(ok for _, ok in items) / len(items), 4),
                "mean_conf": round(statistics.fmean(c for c, _ in items), 4),
                "buckets": _buckets(items),
                "threshold": _threshold(items, target, min_n),
                "top_pred_answers": ans,
                "top_gold_answers": gold,
            }
            ratios = [p["answer"] / r["answer"] for r, p, _ in trip
                      if isinstance(p.get("answer"), (int, float)) and isinstance(r.get("answer"), (int, float))
                      and r["answer"] and r.get("type") != "count"]
            if ratios:
                entry["area_ratio_pred_over_gold_median"] = round(statistics.median(ratios), 3)
            diffs = [p["answer"] - r["answer"] for r, p, _ in trip
                     if isinstance(p.get("answer"), (int, float)) and isinstance(r.get("answer"), (int, float))
                     and r.get("type") == "count"]
            if diffs:
                entry["count_error_mean"] = round(statistics.fmean(diffs), 3)
                entry["count_error_hist"] = dict(sorted(collections.Counter(
                    max(-3, min(3, int(d))) for d in diffs).items()))
            rep[k] = entry
        out["sets"][set_name] = rep

    # Thresholds the engine uses: pooled over the sets present, per slice, with ALL as fallback.
    for k, items in pooled.items():
        t = _threshold(items, target, min_n)
        out["thresholds"][k] = t["threshold"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="gemma-base", help="prediction cache label, e.g. gemma-base, gemma-ft, gemma-ft-run2")
    ap.add_argument("--sets", default="heldout_raster,judge")
    ap.add_argument("--target", type=float, default=0.95, help="precision required of accepted answers")
    ap.add_argument("--min-n", type=int, default=20, help="min answers kept for a threshold to count")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    res = calibrate(a.label, a.sets.split(","), a.target, a.min_n)
    out = a.out or RESULTS / f"calibration_{a.label}.json"
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    for set_name, rep in res["sets"].items():
        print(f"\n{set_name}  (accept if conf >= t so precision >= {a.target:.0%})")
        print(f"  {'slice':32} {'n':>5} {'acc':>6} {'conf':>6} {'t':>7} {'cover':>6}")
        for k, e in rep.items():
            t = e["threshold"]
            ts = "-" if t["threshold"] is None else f"{t['threshold']:.3f}"
            print(f"  {k:32} {e['n']:5d} {e['acc']:6.1%} {e['mean_conf']:6.2f} {ts:>7} {t['coverage']:6.1%}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
