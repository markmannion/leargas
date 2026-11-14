"""Run every IFC-backed question (ifc_models / ifc_bench) through parser -> IFC engine -> scorer.

    cd backend && ../.venv/bin/python eval_ifc.py [--questions ...] [--data-root ...] [--show 15]
"""
import argparse
import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

from app.ifc import CannotVerify, answer
from app.query import parse
from score import score_one

ROOT = Path(__file__).resolve().parent.parent / "datasets" / "junction-dataset"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default=os.environ.get("LEARGAS_DATA_ROOT", str(ROOT)))
    ap.add_argument("--questions", default=None)
    ap.add_argument("--show", type=int, default=15)
    ap.add_argument("--preds", help="write predictions JSONL here")
    a = ap.parse_args()
    root = Path(a.data_root)
    rows = [json.loads(l) for l in open(a.questions or root / "questions.jsonl", encoding="utf-8")]
    rows = [r for r in rows if r["path"].split("/")[1] in ("ifc_models", "ifc_bench") and r["type"] != "text"]
    rows.sort(key=lambda r: r["path"])

    stats = defaultdict(Counter)
    fails = []
    preds = []
    t0 = time.time()
    for r in rows:
        pr = parse(r["question"], use_llm=False)
        key = "?"
        if pr.query is None:
            outcome, pred = "unparsed", None
        else:
            q = pr.query
            key = f"{q.op}/{q.target}/{q.scope}" + ("/name" if q.name else "") + ("/side" if q.side_area else "")
            try:
                res = answer(root / r["path"], q)
                pred = {"answer": res.value, "unit": res.unit}
                outcome = score_one(r, pred)["outcome"]
            except CannotVerify as e:
                pred, outcome = None, "cannot_verify"
                fails.append((r, f"CV: {e}"))
            except Exception as e:  # engine bug: surface it
                pred, outcome = None, "error"
                fails.append((r, f"ERR {type(e).__name__}: {e}"))
            if outcome == "wrong":
                fails.append((r, f"got {pred['answer']}"))
        preds.append({"path": r["path"], "question": r["question"], **(pred or {"answer": None, "status": "cannot_verify"})})
        for k in ("all", key, "src/" + r["path"].split("/")[1]):
            stats[k]["n"] += 1
            stats[k][outcome] += 1

    print(f"{'bucket':40} {'n':>5} {'correct':>8}  outcomes")
    for k in sorted(stats, key=lambda k: (k != "all", k)):
        v = stats[k]
        print(f"{k:40} {v['n']:5d} {v['correct'] / v['n']:8.1%}  {dict((o, c) for o, c in v.items() if o != 'n')}")
    print(f"\n{time.time() - t0:.0f}s")
    for r, why in fails[: a.show]:
        print(f"- {r['path'].split('/')[-1][:45]} | {r['question'][:90]} | gold {r['answer']} | {why[:150]}")
    if a.preds:
        with open(a.preds, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(p, ensure_ascii=False) + "\n" for p in preds)


if __name__ == "__main__":
    main()
