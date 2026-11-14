"""M12: point accuracy for run 2. Do the points the model outputs land on the items it counted?

  python -m model.baseline_eval --models gemma-ft --label gemma-ft-run2 --points      # predictions first
  python -m model.point_eval --preds results/preds/gemma-ft-run2__heldout_raster.jsonl
  python -m model.point_eval --preds ... --overlays 6      # + slide images in results/points_overlays/

Ground truth (normalised [x, y] on the PNG, same shapes build_sft reads):
- swiss: data/points/swiss_points.jsonl (Harry's C4). It covers all drawings, held-out included.
- CubiCasa held-out: data/points/eval/cubicasa_heldout.jsonl (cubicasa_points --heldout-eval).
Only count questions whose label count equals the gold answer are scored (same rule as build_sft),
so a labelling gap can't count against the model.

Metric: each predicted point is matched one-to-one to the nearest unmatched label point (greedy,
nearest pairs first). A match counts as a hit when it's within --radius of the image's long
side (default 2.5%, about one door-symbol width on a CubiCasa plan). Per question: precision =
hits / predicted points, recall = hits / labelled items. Reported per source × kind, micro-averaged.
Also reported: "consistent", the share of answers where len(points) == answer. When that's
low, the points are decoration and not the count's evidence.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
from pathlib import Path

from .baseline_eval import RESULTS, load_set
from .build_sft import load_points, question_kinds, raster_path
from .common import REPO_ROOT, abs_path, load_jsonl, load_questions

GT_FILES = [REPO_ROOT / "data" / "points" / "swiss_points.jsonl",
            REPO_ROOT / "data" / "points" / "eval" / "cubicasa_heldout.jsonl"]


def match(pred_px: list[tuple[float, float]], gold_px: list[tuple[float, float]], radius_px: float) -> int:
    """Greedy one-to-one matching, nearest pairs first. Returns the number of hits within radius."""
    pairs = sorted((math.dist(p, g), i, j) for i, p in enumerate(pred_px) for j, g in enumerate(gold_px))
    used_p, used_g, hits = set(), set(), 0
    for d, i, j in pairs:
        if d > radius_px:
            break
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        hits += 1
    return hits


def image_size(path: str) -> tuple[int, int]:
    from PIL import Image

    with Image.open(abs_path(path)) as im:  # header only, no decode
        return im.size


def evaluate(rows: list[dict], preds: dict[str, dict], gt: dict, radius: float) -> tuple[dict, list[dict]]:
    agg = collections.defaultdict(lambda: collections.Counter())
    per_q = []
    skipped = collections.Counter()
    for r in rows:
        if r.get("type") != "count":
            continue
        kinds = question_kinds(r["question"])
        img = raster_path(r.get("image") or r["path"])
        if not kinds:
            skipped["not a symbol question"] += 1
            continue
        if img not in gt:
            skipped["no labels for drawing"] += 1
            continue
        gold = [p for k in kinds for p in gt[img].get(k, [])]
        if len(gold) != r.get("answer"):
            skipped["labels disagree with gold count"] += 1
            continue
        p = preds.get(r["id"])
        if p is None:
            skipped["no prediction"] += 1
            continue
        pts = p.get("points") or []
        w, h = image_size(img)
        to_px = lambda xy: (xy[0] * w, xy[1] * h)  # noqa: E731
        hits = match([to_px(x) for x in pts], [to_px(x) for x in gold], radius * max(w, h))
        key = f"{r['source']}/{'+'.join(kinds)}"
        for k in (key, "ALL"):
            c = agg[k]
            c["questions"] += 1
            c["pred_points"] += len(pts)
            c["gold_points"] += len(gold)
            c["hits"] += hits
            c["with_points"] += bool(pts)
            c["consistent"] += bool(pts) and p.get("answer") == len(pts)
            c["count_correct"] += p.get("answer") == r.get("answer")
        per_q.append({"id": r["id"], "image": img, "question": r["question"], "kinds": kinds, "answer": p.get("answer"),
                      "gold": r.get("answer"), "pred_points": pts, "gold_points": gold, "hits": hits})
    summary = {}
    for k, c in sorted(agg.items(), key=lambda kv: (kv[0] == "ALL", kv[0])):
        prec = c["hits"] / c["pred_points"] if c["pred_points"] else None
        rec = c["hits"] / c["gold_points"] if c["gold_points"] else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else 0.0 if prec is not None and rec is not None else None
        summary[k] = {"n": c["questions"], "precision": _r(prec), "recall": _r(rec), "f1": _r(f1),
                      "with_points": _r(c["with_points"] / c["questions"]),
                      "consistent": _r(c["consistent"] / c["questions"]),
                      "count_acc": _r(c["count_correct"] / c["questions"])}
    summary["_skipped"] = dict(skipped)
    return summary, per_q


def _r(x):
    return None if x is None else round(x, 4)


def overlays(per_q: list[dict], n: int, radius: float, out_dir: Path) -> None:
    """Gold = green rings, predicted = crosses (blue if matched, red if not). For slides and spot checks."""
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    # most informative first: a mix of misses and clean hits
    picks = sorted(per_q, key=lambda q: (q["hits"] == len(q["gold_points"]) == len(q["pred_points"]), q["id"]))[:n]
    for q in picks:
        im = Image.open(abs_path(q["image"])).convert("RGB")
        w, h = im.size
        d = ImageDraw.Draw(im)
        s = max(4, round(max(w, h) / 200))
        rad = radius * max(w, h)
        for x, y in q["gold_points"]:
            d.ellipse([x * w - rad, y * h - rad, x * w + rad, y * h + rad], outline="#1a9850", width=max(2, s // 2))
        for x, y in q["pred_points"]:
            px, py = x * w, y * h
            hit = any(math.dist((px, py), (gx * w, gy * h)) <= rad for gx, gy in q["gold_points"])
            col = "#2166ac" if hit else "#d73027"
            d.line([px - s, py - s, px + s, py + s], fill=col, width=max(2, s // 2))
            d.line([px - s, py + s, px + s, py - s], fill=col, width=max(2, s // 2))
        name = f"{q['id']}_{'+'.join(q['kinds'])}_pred{q['answer']}_gold{q['gold']}.png"
        im.save(out_dir / name)
    print(f"{len(picks)} overlays in {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", required=True, type=Path, help="results/preds/<label>__<set>.jsonl from baseline_eval --points")
    ap.add_argument("--set", default=None, help="question set; default: inferred from the preds filename")
    ap.add_argument("--radius", type=float, default=0.025, help="hit radius as a fraction of the image's long side")
    ap.add_argument("--gt", nargs="*", type=Path, default=GT_FILES)
    ap.add_argument("--overlays", type=int, default=0)
    ap.add_argument("--out", type=Path, default=RESULTS / "points.json")
    a = ap.parse_args()

    label, _, set_name = a.preds.stem.partition("__")
    set_name = a.set or set_name
    missing = [str(f) for f in a.gt if not f.exists()]
    if missing:
        print(f"!! missing ground truth (those drawings are skipped): {missing}")
    gt = load_points([f for f in a.gt if f.exists()])
    rows = load_set(set_name, load_questions())
    preds = {p["id"]: p for p in load_jsonl(a.preds)}
    summary, per_q = evaluate(rows, preds, gt, a.radius)

    print(f"\n== point accuracy: {label} on {set_name} (hit radius {a.radius:.1%} of long side)")
    for k, v in summary.items():
        if k.startswith("_"):
            continue
        print(f"  {k:28s} n={v['n']:4d}  P={v['precision']}  R={v['recall']}  F1={v['f1']}  "
              f"consistent={v['consistent']}  count_acc={v['count_acc']}")
    print(f"  skipped: {summary['_skipped']}")

    report = json.loads(a.out.read_text(encoding="utf-8")) if a.out.exists() else {}
    report.setdefault(label, {})[set_name] = {"radius": a.radius, **summary}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {a.out}")
    if a.overlays:
        overlays(per_q, a.overlays, a.radius, RESULTS / "points_overlays" / label)


if __name__ == "__main__":
    main()
