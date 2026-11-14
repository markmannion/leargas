"""Build the multilingual template table from questions.jsonl.

In the dataset every translated question directly follows its English original (same path, same
answer). So each translated template maps to exactly one English template, and its quoted values
line up with the English ones by value. The English templates are parsed by `rules.py`; the
translations inherit that parse.

The table is derived from the (non-commercial) dataset, so it is written to a gitignored path and
rebuilt locally rather than committed:

    cd backend && python -m app.query.build_templates --questions ../datasets/junction-dataset/questions.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .normalize import normalize
from .rules import parse_template

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "data" / "query_templates.json"


def _perm(en_args: List[Tuple[str, str]], fx_args: List[Tuple[str, str]]) -> Optional[Tuple[int, ...]]:
    """perm[i] = index in the translated args holding English arg i (matched by value)."""
    used, perm = set(), []
    for _, val in en_args:
        hit = next((j for j, (_, v) in enumerate(fx_args) if j not in used and v == val), None)
        if hit is None:
            return None
        used.add(hit)
        perm.append(hit)
    return tuple(perm)


def build(questions: str) -> Tuple[Dict[str, dict], dict]:
    rows = [json.loads(l) for l in open(questions, encoding="utf-8") if l.strip()]

    en_ok: Dict[str, bool] = {}
    en_seen: Counter = Counter()
    links: Dict[str, Counter] = defaultdict(Counter)  # translated template -> Counter[(en template, perm)]
    prev = None  # last English row whose template parsed
    for r in rows:
        t, args = normalize(r["question"])
        if t not in en_ok:
            en_ok[t] = parse_template(t, args) is not None
        if en_ok[t]:
            en_seen[t] += 1
            prev = (r, t, args)
            continue
        if prev and prev[0]["path"] == r["path"] and prev[0]["answer"] == r["answer"]:
            perm = _perm(prev[2], args)
            if perm is not None:
                links[t][(prev[1], perm)] += 1
        # A row that is neither parseable English nor right after one is left for the LLM.

    table: Dict[str, dict] = {t: {"en": t, "perm": None, "n": n} for t, n in en_seen.items()}
    ambiguous = 0
    for t, c in links.items():
        (en, perm), n = c.most_common(1)[0]
        if n < 0.9 * sum(c.values()):
            ambiguous += 1
            continue
        table[t] = {"en": en, "perm": list(perm), "n": sum(c.values())}

    covered = sum(v["n"] for v in table.values())
    stats = {
        "questions": len(rows),
        "covered": covered,
        "coverage": covered / len(rows),
        "templates_en": len(en_seen),
        "templates_translated": len(table) - len(en_seen),
        "ambiguous_dropped": ambiguous,
    }
    return table, stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", default=os.environ.get("LEARGAS_QUESTIONS"), required=not os.environ.get("LEARGAS_QUESTIONS"))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    table, stats = build(a.questions)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"stats": stats, "templates": table}, f, ensure_ascii=False, indent=1)
    print(json.dumps(stats, indent=2))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
