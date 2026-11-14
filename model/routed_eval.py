"""Score a routed pair of models from cached predictions: the specialist answers the questions that
match --re (the router's LEARGAS_GEMMA_SPECIALIST_RE), the generalist answers the rest. No server
calls: both models must already have results/preds/<label>__<set>.jsonl from baseline_eval.

  python -m model.routed_eval                                    # gemma-ft + gemma-ft-cc -> results/gemma-ft-routed.json
  python -m model.routed_eval --re "\\bdoors?\\b|\\bovea?\\b"        # route only doors

Also prints the per-template comparison on the routed questions, to pick which ones to route.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import time

from .baseline_eval import RESULTS, load_set, score_rows
from .common import load_jsonl, load_questions, template_of
from .scoring import summarize

# Same default as backend/app/router.py GEMMA_SPECIALIST_RE (kept in sync by hand).
DEFAULT_RE = (r"\bwindows?\b|ikkun|\bdoors?\b|\bovea?\b|\bsinks?\b|wash ?basins?|pesu- ja tiskial|\bshowers?\b"
              r"|bathtubs?|suihku")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--general", default="gemma-ft")
    ap.add_argument("--specialist", default="gemma-ft-cc")
    ap.add_argument("--re", default=DEFAULT_RE, help="questions the specialist answers")
    ap.add_argument("--sources", default="cubicasa5k", help="only route questions on these sources ('' = any)")
    ap.add_argument("--out-label", default="gemma-ft-routed")
    a = ap.parse_args()
    rx = re.compile(a.re, re.I)
    srcs = set(filter(None, a.sources.split(",")))
    questions = load_questions()
    report = {}
    for set_name in ("heldout_raster", "judge"):
        rows = load_set(set_name, questions)
        preds = {}
        for m in (a.general, a.specialist):
            p = RESULTS / "preds" / f"{m}__{set_name}.jsonl"
            if not p.exists():
                raise SystemExit(f"missing {p}: run baseline_eval for {m} first")
            preds[m] = {r["id"]: r for r in load_jsonl(p)}
        routed = [bool(rx.search(r["question"])) and (not srcs or r.get("source") in srcs) for r in rows]
        chosen = [preds[a.specialist if s else a.general][r["id"]] for r, s in zip(rows, routed)]
        scored = score_rows(rows, chosen)
        report[set_name] = {"n": len(rows), "routed": sum(routed), "by_source_type": summarize(scored),
                            "by_lang": summarize(scored, key=lambda r: f"lang/{r['lang']}")}
        # per-template comparison on the routed questions
        sub = [r for r, s in zip(rows, routed) if s]
        g = {r["id"]: r for r in score_rows(sub, [preds[a.general][r["id"]] for r in sub])}
        sp = {r["id"]: r for r in score_rows(sub, [preds[a.specialist][r["id"]] for r in sub])}
        by_t = collections.defaultdict(lambda: [0, 0, 0])
        for r in sub:
            k = template_of(r["question"])[:64] if r.get("source") == "cubicasa5k" else f"{r.get('source')}: {r['question'][:50]}"
            by_t[k][0] += 1
            by_t[k][1] += g[r["id"]]["outcome"] == "correct"
            by_t[k][2] += sp[r["id"]]["outcome"] == "correct"
        gen_all = summarize(score_rows(rows, [preds[a.general][r["id"]] for r in rows]))["ALL"]["acc"]
        print(f"\n== {set_name}: {sum(routed)}/{len(rows)} routed to {a.specialist}; "
              f"ALL {a.general} {gen_all:.1%} -> routed {report[set_name]['by_source_type']['ALL']['acc']:.1%}")
        for k, (n, cg, cs) in sorted(by_t.items()):
            print(f"  n={n:3d}  {a.general} {cg / n:6.1%}  {a.specialist} {cs / n:6.1%}  {k}")
    out = RESULTS / f"{a.out_label}.json"
    out.write_text(json.dumps({a.out_label: report, "_meta": {
        "generated": time.strftime("%Y-%m-%d %H:%M"), "general": a.general, "specialist": a.specialist,
        "re": a.re, "sources": a.sources}}, indent=1), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
