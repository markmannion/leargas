"""M5 (run 1) / M9 (run 2): build SFT JSONL from the TRAINING split only.

  python -m model.build_sft --out data/sft/run1.jsonl --n 20000                    # run 1: answer + unit
  python -m model.build_sft --out data/sft/run2.jsonl --n 60000 --points           # run 2: + points (C4/M4b)
  python -m model.build_sft --preview 12                                           # save what the model sees

Rows: {"id", "image": "data/...png", "question", "target", "source", "type", "lang", "has_points"}.
Images stay on disk (resolved with JUNCTION_DATA at train time), so the JSONL stays small.

Balancing (the plan: "keep source x type x language balanced")
- 50% CubiCasa, 50% swiss (swiss questions are answered from the PNG twin, never rasterised).
- Inside a source, equal shares per (type, language) bucket, then round-robin over question
  templates inside the bucket, so 'How many saunas' doesn't drown out 'How many windows'.
- Swiss area questions are kept only for drawings that print room areas (307 of 1,040; see
  common.swiss_printed_areas). On the rest the m² simply isn't in the pixels.
- --abstain-frac (default 0.02): adds "should abstain" examples (questions the drawing cannot
  answer, e.g. fire ratings), target {"answer": null, ...}. This teaches cannot_verify. Set 0 to disable.

Points (run 2, --points)
- Reads data/points/swiss_points.jsonl (Harry, C4) and data/points/cubicasa_points.jsonl (M4b), in any
  of these shapes, one line per item or per drawing:
    {"path": "data/swiss_dwellings/x.png", "kind": "window", "x": 0.41, "y": 0.22}
    {"path": "...", "kind": "window", "point": [0.41, 0.22]}
    {"path": "...", "items": [{"kind": "window", "xy": [0.41, 0.22]}, ...]}
  Coordinates are normalised [x, y] in 0-1 against the PNG.
- A count question gets points only if the label count equals the gold answer (otherwise the
  labels and the question disagree and we'd teach noise); it then falls back to answer-only.

Run 2 without points (the agreed fallback): reweighted mix + harder wording
  python -m model.build_sft --out data/sft/run2.jsonl --n 20000 \
      --reweight results/preds/gemma-ft__heldout_raster.jsonl --paraphrase-frac 0.25
- --reweight PREDS: per-family accuracy of a run on data/splits/raster_eval.jsonl (family = source x
  type x object kind, e.g. cubicasa5k/count/window). Weak families are oversampled (up to 3x), families
  above 90% are cut (down to 0.3x). Sampling is weighted and without replacement, from a pool twice the
  size of --n that is already balanced the run 1 way.
- --paraphrase-frac F: rewrites a share F of the English questions in other words ("Count the windows on
  this sheet.", "What's the number of ...?"), same gold answer. Stoa's judges word questions their own way.
- Abstain rows now also include out-of-scope questions in Stoa's style (pipe sizes, slab reinforcement).
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import re
from pathlib import Path

from .common import (REPO_ROOT, abs_path, guess_lang, is_heldout, load_jsonl, load_questions, prints_areas, source_of,
                     template_of, write_jsonl)
from .prompt import MAX_SIDE, format_target, load_image

POINT_FILES = [REPO_ROOT / "data" / "points" / "swiss_points.jsonl", REPO_ROOT / "data" / "points" / "cubicasa_points.jsonl"]

# question keywords (all dataset languages) -> canonical point kind
KIND_RULES = [
    ("window", r"window|fenster|fenêtre|finestr|ikkun"),
    ("door", r"\bdoor|tür|porte|porta|\bov(e|ia)"),
    ("toilet", r"toilet|\bwc|wc-istu"),
    ("sink", r"washbasin|wash basin|sink|lavabo|lavabi|pesu- ja tiskiallas|allas"),
    ("bathtub", r"bathtub|badewanne|baignoire|vasch"),
    ("shower", r"shower|dusche|douche|docc|suihku"),
]
SHOWER_OR_BATH = r"showers and bathtubs|suihkua ja kylpyammetta"

ABSTAIN_QUESTIONS = [
    ("What is the fire rating of the entrance door?", "fire ratings are not shown on this drawing"),
    ("What is the ceiling height of the living room?", "ceiling heights are not shown on a floor plan"),
    ("What year was this building constructed?", "no construction date is shown"),
    ("How many parking spaces does the building have?", "no parking is shown on this drawing"),
    ("What is the U-value of the external walls?", "thermal values are not shown"),
    ("Mikä on ulko-oven paloluokka?", "paloluokkia ei ole merkitty piirustukseen"),
    ("Wie hoch ist die Raumhöhe im Wohnzimmer?", "Raumhöhen sind im Grundriss nicht angegeben"),
    ("Who is the architect of this building?", "no architect is named on this drawing"),
    ("What size is the main supply pipe?", "no piping is shown on this floor plan"),
    ("How many pipe supports are shown?", "no piping is shown on this floor plan"),
    ("What is the slab thickness and reinforcement?", "no structural slab details are shown"),
    ("What is the rebar spacing in the foundation slab?", "no structural details are shown"),
]

# ---------------------------------------------------------------------------------------- run 2 helpers

def family(r: dict) -> str:
    kinds = question_kinds(r["question"]) if r["type"] == "count" else None
    return f"{r['source']}/{r['type']}/{kinds[0] if kinds else 'other'}"


def family_weights(preds_path: str, lo: float = 0.3, hi: float = 3.0) -> dict[str, float]:
    """{family: weight} from one run's predictions on the fixed held-out raster set."""
    from .scoring import score

    gold = {r["id"]: r for r in load_jsonl(REPO_ROOT / "data" / "splits" / "raster_eval.jsonl")}
    hits: dict = collections.defaultdict(list)
    for p in load_jsonl(Path(preds_path)):
        g = gold.get(p["id"])
        if g is None:
            continue
        ok = score(p.get("answer"), p.get("unit"), g, bool(p.get("abstained"))) == "correct"
        hits[family(g)].append(ok)
    acc = {f: sum(v) / len(v) for f, v in hits.items() if len(v) >= 8}
    if not acc:
        raise SystemExit(f"--reweight: no usable predictions in {preds_path}")
    mean = sum(acc.values()) / len(acc)
    w = {}
    for f, a in acc.items():
        if a > 0.9:
            w[f] = lo
        else:
            w[f] = max(lo, min(hi, (1 - a) / max(1 - mean, 1e-6)))
    print("reweight (family: acc -> weight):")
    for f in sorted(acc, key=acc.get):
        print(f"  {f:40s} {acc[f]:.2f} -> {w[f]:.2f}  (n={len(hits[f])})")
    return w


def weighted_pick(rows: list[dict], n: int, weights: dict[str, float], rng: random.Random) -> list[dict]:
    """n rows without replacement, P(row) ~ its family weight (Efraimidis-Spirakis keys)."""
    keyed = [(rng.random() ** (1.0 / weights.get(family(r), 1.0)), i) for i, r in enumerate(rows)]
    keyed.sort(reverse=True)
    out = [rows[i] for _, i in keyed[:n]]
    rng.shuffle(out)
    return out


_COUNT_Q = re.compile(r"^how many (.+?) (?:are|is) (?:there |drawn |shown |marked |visible )?(?:on|in) (?:this|the) (.+?)\??$", re.I)
_AREA_Q = re.compile(r"^what is the (total |net |combined )?(?:floor )?area of (.+?)(?:,? in m²| \(m²\))?\??$", re.I)


def paraphrase(q: str, rng: random.Random) -> str | None:
    """Reword an English dataset question; None if no rule fits (then the row keeps its wording)."""
    s = q.strip()
    m = _COUNT_Q.match(s)
    if m:
        what, where = m.group(1), m.group(2)
        return rng.choice([
            f"Count the {what} on this {where}.",
            f"What's the number of {what} shown on the {where}?",
            f"{what[0].upper() + what[1:]}: how many does this {where} have?",
            f"Can you tell me how many {what} this {where} shows?",
            f"how many {what} are there",
            f"Give me the total count of {what} on this sheet.",
            f"I need the number of {what} on this {where} for a quantity take-off.",
        ])
    m = _AREA_Q.match(s)
    if m:
        what = m.group(2)
        adj = (m.group(1) or "").strip()
        return rng.choice([
            f"How big is {what} in square metres?",
            f"Floor area of {what}?",
            f"What's the {adj + ' ' if adj else ''}area of {what} in m²?",
            f"Tell me the area of {what}.",
            f"How many m² is {what}?",
        ])
    return None


def raster_path(path: str) -> str:
    return path[:-4] + ".png" if path.endswith(".pdf") and "/swiss_dwellings/" in path else path


def question_kinds(q: str) -> list[str] | None:
    s = q.lower()
    if re.search(SHOWER_OR_BATH, s):
        return ["shower", "bathtub"]
    if re.search(r"label|bezeichnung|dénomination|denominazione|room|raum|huone|kitchen|keitti|sauna|balcon|parvek|floor|kerros|storey|apartment|wohnung", s):
        return None  # rooms/units: point labels are object symbols only
    for kind, rx in KIND_RULES:
        if re.search(rx, s):
            return [kind]
    return None


def load_points(files: list[Path] | None = None) -> dict[str, dict[str, list[list[float]]]]:
    """-> {raster_png_path: {kind: [[x, y], ...]}}. Default files are the TRAINING label files."""
    out: dict[str, dict[str, list]] = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in (POINT_FILES if files is None else files):
        if not f.exists():
            continue
        for r in load_jsonl(f):
            path = raster_path(r["path"])
            items = r.get("items") or [r]
            for it in items:
                kind = (it.get("kind") or it.get("label") or it.get("class") or "").lower()
                kind = {"wc": "toilet", "washbasin": "sink", "lavabo": "sink", "bath": "bathtub", "tub": "bathtub"}.get(kind, kind)
                xy = it.get("xy") or it.get("point") or ([it["x"], it["y"]] if "x" in it and "y" in it else None)
                if kind and xy:
                    out[path][kind].append([float(xy[0]), float(xy[1])])
        print(f"points: loaded {f.name}")
    return out


def pick_balanced(rows: list[dict], n: int, rng: random.Random) -> list[dict]:
    by_src = collections.defaultdict(list)
    for r in rows:
        by_src[r["source"]].append(r)
    per_src = n // len(by_src)
    picked = []
    for src, items in sorted(by_src.items()):
        buckets = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in items:
            buckets[(r["type"], r["lang"])][template_of(r["question"])].append(r)
        per_bucket = per_src // len(buckets)
        for key in sorted(buckets):
            tmpl = buckets[key]
            for v in tmpl.values():
                rng.shuffle(v)
            order = sorted(tmpl)
            got, i = [], 0
            while len(got) < per_bucket and any(tmpl.values()):
                k = order[i % len(order)]
                if tmpl[k]:
                    got.append(tmpl[k].pop())
                i += 1
            picked.extend(got)
        print(f"  {src}: {len(buckets)} type x lang buckets, ~{per_bucket} each")
    if len(picked) < n:  # small buckets (e.g. swiss Italian) leave a gap: top up uniformly
        chosen = {id(r) for r in picked}
        rest = [r for r in rows if id(r) not in chosen]
        rng.shuffle(rest)
        picked.extend(rest[: n - len(picked)])
    rng.shuffle(picked)
    return picked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "sft" / "run1.jsonl"))
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--points", action="store_true", help="run 2: add points to count targets where labels agree")
    ap.add_argument("--abstain-frac", type=float, default=0.02)
    ap.add_argument("--keep-unprinted-areas", action="store_true",
                    help="keep swiss area questions on drawings without printed m² (default: drop them)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--val", type=int, default=300, help="extra held-in rows for a quick eval loss (from TRAIN drawings)")
    ap.add_argument("--crop-swiss", action="store_true",
                    help="swiss rows use the plan-only crops (python -m model.crop --write first); points mapped to the crop")
    ap.add_argument("--reweight", default=None, metavar="PREDS",
                    help="run 2: oversample families this run's held-out predictions got wrong")
    ap.add_argument("--paraphrase-frac", type=float, default=0.0,
                    help="run 2: share of English questions reworded (same gold answer)")
    ap.add_argument("--preview", type=int, default=0, help="save N resized training images to data/sft/preview/ and exit")
    a = ap.parse_args()
    rng = random.Random(a.seed)

    qs = [q for q in load_questions()
          if source_of(q["path"]) in ("cubicasa5k", "swiss_dwellings") and not is_heldout(q["path"]) and q["type"] != "text"]
    if not a.keep_unprinted_areas:
        before = len(qs)
        qs = [q for q in qs if not (q["type"] == "area" and prints_areas(q["path"]) is False)]
        print(f"dropped {before - len(qs)} swiss area questions on drawings that print no m² (unanswerable from pixels)")
    rows = [{**q, "source": source_of(q["path"]), "lang": guess_lang(q["question"]), "image": raster_path(q["path"])} for q in qs]
    boxes: dict = {}
    if a.crop_swiss:
        from .crop import BOXES, crop_path, saved_boxes
        boxes = saved_boxes()
        if not boxes:
            raise SystemExit(f"no crops at {BOXES}: run python -m model.crop --write first (on the machine that trains)")
        missing = {Path(r["image"]).stem for r in rows if r["source"] == "swiss_dwellings"} - set(boxes)
        if missing:
            raise SystemExit(f"{len(missing)} swiss images have no crop box, e.g. {sorted(missing)[:3]}")
        for r in rows:
            if r["source"] == "swiss_dwellings":
                r["sheet_image"], r["image"] = r["image"], crop_path(r["image"])
        print("swiss rows -> plan crops (data/swiss_dwellings_crop/)")
    print(f"training-split raster questions: {len(rows)}")

    if a.preview:
        out_dir = REPO_ROOT / "data" / "sft" / "preview"
        out_dir.mkdir(parents=True, exist_ok=True)
        for r in rng.sample(rows, a.preview):
            img = load_image(abs_path(r["image"]), MAX_SIDE)
            # ~what 560 soft tokens resolve: about 1.3 MP (assumes 16 px patches with 3x3 pooling).
            # Check the real number on the box: python -m model.train_lora --check-processor
            import math
            s = min(1.0, math.sqrt(1.29e6 / (img.width * img.height)))
            small = img.resize((int(img.width * s), int(img.height * s)))
            name = Path(r["image"]).stem + f"_{small.width}x{small.height}.png"
            small.save(out_dir / name)
            print(f"  {name}  q: {r['question'][:60]}  a: {r['answer']}")
        return

    n_abstain = int(a.n * a.abstain_frac)
    if a.reweight:
        pool = pick_balanced(rows, 2 * (a.n - n_abstain) + a.val, rng)
        val, rest = pool[: a.val], pool[a.val:]
        train = weighted_pick(rest, a.n - n_abstain, family_weights(a.reweight), rng)
    else:
        picked = pick_balanced(rows, a.n - n_abstain + a.val, rng)
        val, train = picked[: a.val], picked[a.val:]
    n_para = 0
    if a.paraphrase_frac > 0:
        for r in train:
            if r["lang"] == "en" and rng.random() < a.paraphrase_frac:
                new = paraphrase(r["question"], rng)
                if new:
                    r["question"] = new
                    n_para += 1
        print(f"paraphrased {n_para} English questions")

    points = load_points() if a.points else {}
    stats = collections.Counter()

    def to_row(r, i, split):
        pts = None
        if a.points and r["type"] == "count":
            kinds = question_kinds(r["question"])
            sheet = r.get("sheet_image", r["image"])
            if kinds and sheet in points:
                cand = [p for k in kinds for p in points[sheet].get(k, [])]
                if "sheet_image" in r:  # labels are on the sheet; the model sees the crop
                    from .crop import sheet_to_crop
                    box = boxes[Path(sheet).stem]
                    mapped = [sheet_to_crop(p, box) for p in cand]
                    if any(m is None for m in mapped):
                        stats["points_outside_crop"] += 1
                    cand = [m for m in mapped if m is not None]
                if len(cand) == r["answer"]:
                    pts = cand
                    stats["with_points"] += 1
                else:
                    stats["points_mismatch"] += 1
            elif kinds:
                stats["no_labels_for_image"] += 1
        return {"id": f"{split}_{i:06d}", "image": r["image"], "question": r["question"],
                "target": format_target(r["answer"], r["unit"], pts), "source": r["source"], "type": r["type"],
                "lang": r["lang"], "has_points": pts is not None, "answer": r["answer"], "unit": r["unit"]}

    out_rows = [to_row(r, i, "train") for i, r in enumerate(train)]
    imgs = sorted({r["image"] for r in train})
    for j in range(n_abstain):
        q, why = ABSTAIN_QUESTIONS[j % len(ABSTAIN_QUESTIONS)]
        img = rng.choice(imgs)
        out_rows.append({"id": f"abst_{j:05d}", "image": img, "question": q, "target": format_target(None, None, reason=why),
                         "source": source_of(img).removesuffix("_crop"), "type": "abstain", "lang": guess_lang(q), "has_points": False,
                         "answer": None, "unit": None})
    rng.shuffle(out_rows)
    write_jsonl(Path(a.out), out_rows)
    val_path = Path(a.out).with_name(Path(a.out).stem + "_val.jsonl")
    write_jsonl(val_path, [to_row(r, i, "val") for i, r in enumerate(val)])

    if a.reweight:
        fam = collections.Counter(family(r) for r in out_rows if r["type"] != "abstain")
        print("families after reweighting:", ", ".join(f"{k} {v}" for k, v in fam.most_common()))
    c = collections.Counter((r["source"], r["type"], r["lang"]) for r in out_rows)
    print(f"wrote {len(out_rows)} rows -> {a.out}  (+{len(val)} val -> {val_path.name})")
    for k, v in sorted(c.items()):
        print(f"  {k[0]:16s} {k[1]:8s} {k[2]}  {v}")
    if a.points:
        print(f"points: {dict(stats)}")
    print("sample target:", out_rows[0]["target"])


if __name__ == "__main__":
    main()
