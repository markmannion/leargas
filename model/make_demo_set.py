"""M1: demo question set (contract C1) -> data/splits/demo_questions.jsonl

50 held-out questions across every source and type, plus 3 deliberately unanswerable ones.
Pinned questions back the demo script's beats; the rest are drawn with a fixed seed.

  python -m model.make_demo_set

Every row carries "checked": false. Mark flips it to true after looking at the drawing
(the dataset answers are the ground truth; the check is that the drawing actually shows it
and that it reads well on screen). Re-running keeps rows whose id already exists with checked=true.
"""
from __future__ import annotations

import collections
import random

from .common import SPLITS_DIR, guess_lang, is_heldout, load_jsonl, load_questions, source_of, write_jsonl

SEED = 2026
OUT = SPLITS_DIR / "demo_questions.jsonl"

SWISS_DEMO = "data/swiss_dwellings/site2297_bldg3392_floor15123.pdf"  # 12 windows, 2 flats, rooms with m²
SWISS_README = "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf"  # the dataset README's example
CUBI_BEAT3 = "data/cubicasa5k/colorful-12094.png"  # clean plan, 5 windows, Finnish question
CUBI_BEAT4 = "data/cubicasa5k/high_quality_architectural-10500.png"  # 2 WCs (KH + WC room)
A801 = "data/opening_design/Sports_Complex/Sheets - Current Set/A-801 - Door and Finish Schedules & Wall Types.pdf"

# (path, question prefix, beat) -- prefix matching keeps this robust to long template tails
PINS = [
    (SWISS_DEMO, "How many windows are drawn", "beat1"),
    (SWISS_DEMO, "Wie gross ist die gesamte Nettogeschossfläche", "beat2"),
    (SWISS_DEMO, "What is the net floor area of apartment A", "beat2"),
    (SWISS_DEMO, "How many toilets (WC)", None),
    (SWISS_DEMO, "Wie viele Wohnungen", None),
    (SWISS_DEMO, "How many rooms labelled 'Zimmer'", None),
    (SWISS_README, "How many apartments", None),
    (A801, "On sheet A-801 of the Xcel Sports Complex drawings, how many doors in the door schedule are door type A1", "beat5"),
    (A801, "On sheet A-801 of the Xcel Sports Complex drawings, what door type is door 121.A", None),
    (A801, "On sheet A-801 of the Xcel Sports Complex drawings, what is the area of room 128", None),
]

# how many of each source in the final 50 (pins count towards these)
QUOTA = {"cubicasa5k": 15, "swiss_dwellings": 14, "ifc_models": 8, "opening_design": 8, "ifc_bench": 5}

UNANSWERABLE = [
    {
        "path": "data/cubicasa5k/{cubi}",
        "question": "What is the fire rating of the wall between the kitchen and the bathroom?",
        "why": "Floor plans of this kind carry no fire ratings; there is nothing to read or count.",
    },
    {
        "path": SWISS_DEMO,
        "question": "How many parking spaces are in the underground garage of this building?",
        "why": "The drawing is one above-ground floor; the garage is not shown.",
    },
    {
        "path": "data/cubicasa5k/{cubi}",
        "question": "What year was this apartment built, and who was the architect?",
        "why": "No title block or metadata on the plan says this.",
    },
]


def _row(q: dict, idx: int, beat: str | None = None) -> dict:
    return {
        "id": f"demo_{idx:02d}",
        "path": q["path"],
        "question": q["question"],
        "answer": q["answer"],
        "unit": q["unit"],
        "type": q["type"],
        "source": source_of(q["path"]),
        "lang": guess_lang(q["question"]),
        "expected": "answer",
        "beat": beat,
        "checked": False,
        "notes": "",
    }


def main() -> None:
    qs = [q for q in load_questions() if is_heldout(q["path"])]
    rng = random.Random(SEED)
    chosen: list[tuple[dict, str | None]] = []
    used = set()

    for path, prefix, beat in PINS:
        hit = next((q for q in qs if q["path"] == path and q["question"].startswith(prefix)), None)
        if hit is None:
            raise SystemExit(f"pin not found / not held out: {path} :: {prefix}")
        chosen.append((hit, beat))
        used.add(id(hit))

    have = collections.Counter(source_of(q["path"]) for q, _ in chosen)

    # beat 3: a clean CubiCasa plan asked in Finnish; beat 4: a toilet count of 2 (click a missed toilet: 2 -> 3).
    # Both were looked at by eye (Sat 03:00): 12094 is a clean "colorful" plan; 10500 has one WC in KH and one in WC.
    cubi = [q for q in qs if source_of(q["path"]) == "cubicasa5k"]
    rng.shuffle(cubi)
    fi_pick = next(q for q in qs if q["path"] == CUBI_BEAT3 and q["question"].startswith("Kuinka monta ikkunaa"))
    wc_pick = next(q for q in qs if q["path"] == CUBI_BEAT4 and q["question"].startswith("How many toilet bowls"))
    for q, beat in ((fi_pick, "beat3"), (wc_pick, "beat4")):
        chosen.append((q, beat))
        used.add(id(q))
        have["cubicasa5k"] += 1

    # fill the rest per source, spreading over (type, template-ish, lang) so every type shows up
    for src, n in QUOTA.items():
        pool = [q for q in qs if source_of(q["path"]) == src and id(q) not in used]
        rng.shuffle(pool)
        # round-robin over (type, lang, first 40 chars) buckets for variety
        buckets = collections.defaultdict(list)
        for q in pool:
            buckets[(q["type"], guess_lang(q["question"]), q["question"][:40])].append(q)
        keys = sorted(buckets)
        rng.shuffle(keys)
        # put types this source hasn't covered yet first
        seen_types = {q["type"] for q, _ in chosen if source_of(q["path"]) == src}
        keys.sort(key=lambda k: k[0] in seen_types)
        seen_paths = collections.Counter(q["path"] for q, _ in chosen)
        i = 0
        while have[src] < n and keys:
            k = keys[i % len(keys)]
            if buckets[k]:
                q = buckets[k].pop()
                if seen_paths[q["path"]] < 3 or src in ("opening_design", "ifc_bench", "ifc_models"):
                    chosen.append((q, None))
                    seen_paths[q["path"]] += 1
                    have[src] += 1
            else:
                keys.remove(k)
                continue
            i += 1

    rows = [_row(q, i + 1, beat) for i, (q, beat) in enumerate(chosen)]

    cubi_paths = sorted({q["path"].rsplit("/", 1)[1] for q in cubi})
    for j, u in enumerate(UNANSWERABLE):
        path = u["path"].format(cubi=cubi_paths[(j * 37) % len(cubi_paths)])
        rows.append({
            "id": f"demo_u{j + 1}",
            "path": path,
            "question": u["question"],
            "answer": None,
            "unit": None,
            "type": "unanswerable",
            "source": source_of(path),
            "lang": "en",
            "expected": "cannot_verify",
            "beat": "beat7" if j == 1 else None,
            "checked": False,
            "notes": u["why"],
        })

    # keep Mark's hand checks across re-runs
    if OUT.exists():
        old = {r["id"]: r for r in load_jsonl(OUT)}
        for r in rows:
            o = old.get(r["id"])
            if o and o.get("checked") and o["path"] == r["path"] and o["question"] == r["question"]:
                r["checked"], r["notes"] = True, o.get("notes", "")

    write_jsonl(OUT, rows)
    c = collections.Counter((r["source"], r["type"]) for r in rows)
    print(f"{len(rows)} demo questions -> {OUT}")
    for k, v in sorted(c.items()):
        print(f"  {k[0]:16s} {k[1]:13s} {v}")


if __name__ == "__main__":
    main()
