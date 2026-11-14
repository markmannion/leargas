"""Check the parser against questions.jsonl (no LLM).

For every question it reports coverage (a Query came out) and two consistency checks that need no
hand labels:
  - type/unit: the Query's op and unit agree with the gold `type` and `unit`
  - translation: a translated question parses to exactly the same Query as its English original

    cd backend && python -m app.query.eval_parse --questions ../datasets/junction-dataset/questions.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict

from .parser import parse, templates

MEASURED = {"count", "area", "length", "volume"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=os.environ.get("LEARGAS_QUESTIONS"), required=not os.environ.get("LEARGAS_QUESTIONS"))
    ap.add_argument("--show", type=int, default=5, help="examples of each failure to print")
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.questions, encoding="utf-8") if l.strip()]
    by = defaultdict(Counter)
    fails = defaultdict(list)
    prev = None  # (row, query) of the last question that parsed via an English template
    for r in rows:
        res = parse(r["question"], use_llm=False)
        q = res.query
        typ, src = r["type"], r["path"].split("/")[1]
        for key in ("all", f"type/{typ}", f"source/{src}"):
            by[key]["n"] += 1
            by[key]["parsed"] += q is not None
        by["parser"][res.parser] += 1

        if q is None:
            if typ in MEASURED:
                fails["unparsed"].append(r["question"])
            continue
        if typ in MEASURED and (q.op != typ or (q.unit or None) != r["unit"]):
            fails["type_unit_mismatch"].append(f"{r['question']}  gold={typ}/{r['unit']} got={q.op}/{q.unit}")
        if typ == "text":
            by["all"]["text_parsed"] += 1

        entry = templates().get(res.template)
        is_translation = bool(entry and entry["perm"] is not None and prev
                              and prev[0]["path"] == r["path"] and prev[0]["answer"] == r["answer"])
        if is_translation and q != prev[1]:
            fails["translation_mismatch"].append(f"{r['question']}\n      got {q.model_dump(exclude_defaults=True)}\n      en  {prev[1].model_dump(exclude_defaults=True)}")
        if not is_translation:
            prev = (r, q, res.template)

    print(f"{'bucket':28} {'n':>7} {'parsed':>8}")
    for k in sorted(k for k in by if k != "parser"):
        v = by[k]
        print(f"{k:28} {v['n']:7d} {v['parsed'] / v['n']:8.1%}")
    print("by parser:", dict(by["parser"]))
    print("text questions that parsed to a query (expected few):", by["all"]["text_parsed"])
    for k in ("unparsed", "type_unit_mismatch", "translation_mismatch"):
        print(f"\n{k}: {len(fails[k])}")
        for s in Counter(fails[k]).most_common(a.show):
            print("   ", s[1], "x", s[0][:300])


if __name__ == "__main__":
    main()
