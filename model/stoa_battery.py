"""Judge-style wordings on Stoa's 4 example sheets, through the hosted app, to find the phrasings
the sheet reader misses. Stoa scores accuracy on specific blueprints through our UI, and judges word
questions their own way.

  - "keyed": facts checked by hand on Saturday (HANDOFF.md), each asked 4-6 ways (terse, wordy,
    other units, other terms, a typo).
  - "open": the kinds of question Stoa listed (room areas, skirting, doors/windows, slabs, piping),
    with no answer key: the report shows what came back, for a person to judge.

    python -m model.stoa_battery --base https://<host>       # writes results/battery/stoa_wording.{jsonl,md}
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json

from .hosted_battery import OUT, _ask, _stoa_ok

SHEETS = {
    "dorm": "data/uploads/6b8b7dad831e460ebff2f842d754c37b/us_daf_dorm_plan.png",
    "piping": "data/uploads/195b73aa60574845b31ec2238953f51b/us_aw_078-24-28_p096.png",
    "foundation": "data/uploads/db3b78b916a546ea884ff08cbce9e449/us_aw_078-24-33_p056.png",
    "school": "data/uploads/1553fcf1f6bb4be489673d0338aec621/uk_dfe_school_plan.png",
}

# (sheet, fact, gold, checked by hand, wordings)
KEYED = [
    ("dorm", "total gross area", 26562, True, [
        "What is the total gross area in SF?",
        "Total building area?",
        "How many square feet is the whole building?",
        "What's the gross floor area of the dormitory?",
        "total sf",
        "What is the total area of the dorm in square feet?",
    ]),
    ("dorm", "dorm rooms", 144, True, [
        "How many dorm rooms are there?",
        "How many dormitory rooms in total?",
        "Number of bedrooms in the building?",
        "how many dorms",
        "Count the sleeping rooms.",
    ]),
    ("dorm", "dorm rooms on floor 2", 48, True, [
        "How many dorm rooms are on the second floor?",
        "How many dorms on the 2nd floor?",
        "Number of rooms on level 2?",
        "How many dorm rooms does floor two have?",
    ]),
    ("dorm", "west wing circulation", 914, True, [
        "What's the circulation area of the west wing?",
        "West wing corridor area?",
        "How much circulation space is in the west wing, in square feet?",
        "circulation west wing sf",
    ]),
    ("piping", "FP tags", 5, True, [
        "How many FP tags are on this piping plan?",
        "How many fire pumps are shown?",
        "Count the FP labels.",
        "how many FP",
    ]),
    ("piping", "CV tags", 5, True, [
        "How many control valves (CV) are shown?",
        "How many CV tags are there?",
        "Number of control valves?",
        "Count the CVs on the drawing.",
    ]),
    ("piping", "suction header size", 16, True, [
        "What size is the suction header?",
        "Suction header diameter?",
        "What is the pipe size of the suction header in inches?",
        "how big is the suction header",
    ]),
    ("foundation", "MCC trench length", 4275, True, [
        "How long is the motor control center trench?",
        "Length of the MCC trench?",
        "What is the motor control centre trench length in mm?",
        "How long is the trench for the motor control center, in metres?",
    ]),
    ("foundation", "overall length", 27000, True, [
        "What is the overall length of the building in mm?",
        "Overall building length?",
        "How long is the building?",
        "What's the total length of the foundation in metres?",
    ]),
    ("school", "hall area", 247, False, [
        "What is the area of the hall in m2?",
        "How big is the main hall?",
        "Hall floor area?",
    ]),
    ("school", "library area", 26.8, False, [
        "How big is the library?",
        "What is the library's floor area in square metres?",
        "library area",
    ]),
    ("school", "group rooms", 10, False, [
        "How many group rooms are there?",
        "Number of group rooms?",
        "Count the group rooms on this level.",
    ]),
]

OPEN = [
    ("dorm", "How many doors are on this floor plan?"),
    ("dorm", "How many windows are there?"),
    ("dorm", "What is the area of each room?"),
    ("dorm", "What is the overall length of the building?"),
    ("piping", "What pipe sizes are shown on this plan?"),
    ("piping", "How many PS tags are there?"),
    ("piping", "What is the drawing scale?"),
    ("foundation", "What are the slab areas by type?"),
    ("foundation", "What is the slab area?"),
    ("foundation", "What is the drawing scale?"),
    ("foundation", "How thick is the slab?"),
    ("school", "What is the skirting length in the fitness room?"),
    ("school", "How many doors are there?"),
    ("school", "How many windows are there?"),
    ("school", "What is the area of each room?"),
    ("school", "What is the drawing scale?"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    jobs = [("keyed", sheet, fact, gold, checked, q) for sheet, fact, gold, checked, qs in KEYED for q in qs]
    jobs += [("open", sheet, "", None, None, q) for sheet, q in OPEN]

    def one(j):
        kind, sheet, fact, gold, checked, q = j
        d = _ask(a.base, SHEETS[sheet], q)
        return {"kind": kind, "sheet": sheet, "fact": fact, "gold": gold, "checked": checked, "question": q,
                "answer": d.get("answer"), "unit": d.get("unit"), "status": d.get("status"), "engine": d.get("source"),
                "confidence": d.get("confidence"), "explanation": (d.get("explanation") or "")[:160],
                "n_evidence": len(d.get("evidence") or []), "correct": _stoa_ok(d.get("answer"), gold, area="area" in fact or "circulation" in fact) if gold else None,
                "wall_s": round(d["wall_s"], 2), "error": d.get("error")}

    with cf.ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(one, jobs))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "stoa_wording.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    keyed = [r for r in rows if r["kind"] == "keyed"]
    lines = ["# Stoa sheets: judge-style wordings through the hosted app", ""]
    ok = sum(r["correct"] for r in keyed)
    lines.append(f"Keyed: {ok}/{len(keyed)} right ({100 * ok / len(keyed):.0f}%). "
                 f"Verified answers: {sum(r['status'] == 'verified' for r in keyed)}, of which wrong: "
                 f"{sum(r['status'] == 'verified' and not r['correct'] for r in keyed)}.")
    lines.append("")
    for sheet, fact, gold, checked, _ in KEYED:
        rs = [r for r in keyed if r["fact"] == fact]
        hits = sum(r["correct"] for r in rs)
        lines.append(f"## {sheet}: {fact} = {gold}{'' if checked else ' (not checked by hand)'}  ({hits}/{len(rs)})")
        for r in rs:
            mark = "OK  " if r["correct"] else "MISS"
            lines.append(f"- {mark} `{r['question']}` -> {r['answer']} {r['unit'] or ''} [{r['status']}, {r['engine']}]"
                         + (f" ERROR {r['error']}" if r["error"] else ""))
        lines.append("")
    lines.append("## Open questions (no key: judge by eye)")
    for r in [r for r in rows if r["kind"] == "open"]:
        lines.append(f"- {r['sheet']}: `{r['question']}` -> {r['answer']} {r['unit'] or ''} [{r['status']}, {r['engine']}, "
                     f"{r['n_evidence']} marks] {r['explanation']}" + (f" ERROR {r['error']}" if r["error"] else ""))
    (OUT / "stoa_wording.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
