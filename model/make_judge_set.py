"""M1b: judge-style test set (contract C1) -> data/splits/judge_questions.jsonl

30 questions the way a judge would type them, all on held-out or unlabelled drawings:
- 15 paraphrases ("paraphrase") of dataset questions in new wordings and languages (sv, fr, nl, casual en/fi/de).
  Gold answers are looked up from questions.jsonl via (path, original-question prefix), not retyped.
- 10 new questions ("new") on held-out swiss / CubiCasa / IFC drawings, answers checked by hand.
- 5 on unlabelled HABS / Finna drawings ("unlabelled"), answered by hand or marked should-abstain.

`answer_check` records how each hand answer was obtained, so Mark can re-verify quickly.
Every row has checked=false until Mark looks at it.

  python -m model.make_judge_set
"""
from __future__ import annotations

import collections

from .common import SPLITS_DIR, guess_lang, is_heldout, load_questions, source_of, write_jsonl

OUT = SPLITS_DIR / "judge_questions.jsonl"

SW = "data/swiss_dwellings/site2297_bldg3392_floor15123.pdf"
SW2 = "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf"
C1 = "data/cubicasa5k/colorful-12094.png"
C2 = "data/cubicasa5k/high_quality_architectural-10500.png"
C3 = "data/cubicasa5k/high_quality_architectural-8798.png"
VIT1 = "data/ifc_models/bimspeed-vitoria_ald26-before_plan-02-p1.pdf"
FINNA = "data/finna/hka.139877703731200_160449953667200.jpg"  # Brändö, Helsingfors 1948, Swedish labels
HABS = "data/habs/hi0934_sheet_00002.jpg"  # HAPCO house, Lanai City HI: floor plan + 2 sections

# (path, judge wording, original question prefix to copy the gold answer from)
PARAPHRASES = [
    (SW, "Hur många fönster finns på den här planritningen?", "How many windows are drawn"),
    (SW, "Combien y a-t-il de portes au total sur ce plan, portes intérieures et portes d'entrée comprises ?", "How many doors (interior doors"),
    (SW, "what's the total usable floor area of the indoor rooms on this floor? leave out balconies", "What is the total net floor area in m"),
    (SW, "Hur stor är nettoarean för lägenhet B i kvadratmeter, utan balkonger och andra uteplatser?", "What is the net floor area of apartment B"),
    (SW, "Hoeveel badkuipen staan er op deze plattegrond?", "How many bathtubs are drawn"),
    (SW2, "Combien de logements figurent sur ce plan d'étage ?", "How many apartments"),
    (SW2, "how many WCs on this floor?", "How many toilets (WC)"),
    (SW2, "Wie viele Zimmer mit der Beschriftung «Bad» hat dieses Stockwerk?", "How many rooms labelled 'Bad'"),
    (C1, "Hur många fönster har lägenheten?", "How many windows are shown"),
    (C1, "Hur många sovrum finns det på planen?", "How many bedrooms"),
    (C2, "Combien de cuvettes de WC sont dessinées sur ce plan ?", "How many toilet bowls"),
    (C2, "how many bedrooms does this flat have", "How many bedrooms"),
    (C2, "Onko asunnossa saunaa? Montako?", "How many saunas"),
    (C3, "Montako ovea asunnossa on? Pelkkiä aukkoja ei lasketa.", "How many doors are shown"),
    (VIT1, "Combien de portes y a-t-il sur le plan de l'étage P1 ?", "How many doors are shown on the floor plan of 'P1'"),
]

# (path, question, answer, unit, type, how the answer was checked)
NEW = [
    (SW, "What is the area of the larger of the two balconies, in m²?", 20.82, "m2", "area",
     "PNG labels: Balkon 0.09 = 20.82 m², Balkon 0.16 = 15.65 m²"),
    (SW, "How many rooms labelled 'Zimmer' belong to apartment B?", 2, "count", "count",
     "PNG: Whg. B boundary (red dash-dot) contains Zimmer 0.14 and 0.15"),
    (SW, "What is the combined net area of both kitchens (Küche) on this floor, in m²?", 22.68, "m2", "area",
     "PNG labels: Küche 0.07 = 13.42 m² + Küche 0.11 = 9.26 m²"),
    (SW, "How many lifts are there on this floor?", 1, "count", "count", "PNG: one 'Lift 0.22'"),
    (SW, "What is the net area of the largest room on this floor, in m²?", 56.09, "m2", "area",
     "PNG labels: Raum 0.19 = 56.09 m² (next largest Zimmer 0.14 = 27.01 m²)"),
    (C1, "How many burners does the cooktop in the kitchen have?", 4, "count", "count",
     "PNG: hob with 4 rings on the lower kitchen counter"),
    (C2, "What is the area of the kitchen (K), in m²?", 12.4, "m2", "area", "PNG label under K: 12.4"),
    (C2, "How many rooms are labelled MH2?", 2, "count", "count", "PNG: MH2 10.2 and MH2 9.0"),
    (C3, "What total apartment area is written on the plan, in m²?", 91.5, "m2", "area",
     "PNG (printed upside down): 'AS B34, 4H, K, S, 91,5 m2'"),
    (VIT1, "How many windows are shown on the floor plan of P1?", 12, "count", "count",
     "Twin SVG: 12 distinct IfcWindow data-guids (same method gives 16 IfcDoor / 17 IfcSpace = dataset answers)"),
]

# (path, question, answer, unit, type, expected, how checked)
UNLABELLED = [
    (FINNA, "How many rooms labelled 'Rum' are on this floor plan?", 2, "count", "count", "answer",
     "JPG: two rooms marked 'Rum' either side of Salon/Matsal"),
    (FINNA, "Hur många badkar finns på ritningen?", 1, "count", "count", "answer",
     "JPG: one bathtub in 'Badr.' (top left)"),
    (FINNA, "What is the floor area of the Salon in m²?", None, None, "area", "cannot_verify",
     "No areas or dimension strings on the sheet, only 'I vån 1:100'. Should abstain"),
    (HABS, "How many bedrooms are shown on the floor plan?", 2, "count", "count", "answer",
     "JPG: rooms 103 and 104 'BEDROOM'"),
    (HABS, "What is the overall length of the house on the floor plan, in metres?", 11.14, "m", "length", "answer",
     "JPG: top dimension string 36'-6½\" = 11.138 m (2% tolerance covers rounding)"),
]


def main() -> None:
    qs = load_questions()
    by_path = collections.defaultdict(list)
    for q in qs:
        by_path[q["path"]].append(q)

    rows = []
    for i, (path, text, prefix) in enumerate(PARAPHRASES, 1):
        assert is_heldout(path), path
        gold = next((q for q in by_path[path] if q["question"].startswith(prefix)), None)
        if gold is None:
            raise SystemExit(f"no gold for {path} :: {prefix}")
        rows.append({"id": f"judge_p{i:02d}", "kind": "paraphrase", "path": path, "question": text,
                     "answer": gold["answer"], "unit": gold["unit"], "type": gold["type"],
                     "source": source_of(path), "lang": guess_lang(text), "expected": "answer",
                     "original_question": gold["question"], "answer_check": "copied from questions.jsonl",
                     "checked": False})
    for i, (path, text, ans, unit, typ, how) in enumerate(NEW, 1):
        assert is_heldout(path), path
        dup = [q for q in by_path[path] if q["question"].strip().lower() == text.strip().lower()]
        assert not dup, f"not new: {text}"
        rows.append({"id": f"judge_n{i:02d}", "kind": "new", "path": path, "question": text, "answer": ans,
                     "unit": unit, "type": typ, "source": source_of(path), "lang": guess_lang(text),
                     "expected": "answer", "answer_check": how, "checked": False})
    for i, (path, text, ans, unit, typ, expected, how) in enumerate(UNLABELLED, 1):
        assert path not in by_path, f"{path} has questions; not unlabelled"
        rows.append({"id": f"judge_u{i:02d}", "kind": "unlabelled", "path": path, "question": text, "answer": ans,
                     "unit": unit, "type": typ, "source": source_of(path), "lang": guess_lang(text),
                     "expected": expected, "answer_check": how, "checked": False})

    write_jsonl(OUT, rows)
    c = collections.Counter((r["kind"], r["lang"]) for r in rows)
    print(f"{len(rows)} judge questions -> {OUT}")
    for k, v in sorted(c.items()):
        print(f"  {k[0]:11s} {k[1]}  {v}")


if __name__ == "__main__":
    main()
