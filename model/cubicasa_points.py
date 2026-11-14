"""M4b: CubiCasa point labels from the public CubiCasa5k SVG annotations (ONLY if Stoa said yes).

UNTESTED against the real archive: written before download. Start with --inspect, which prints the
SVG class names actually used, and adjust KIND_RULES if needed (5 minutes).

  # on the box, after setup_box.sh CUBICASA=1 finished:
  python -m model.cubicasa_points --root ~/cubicasa/cubicasa5k --inspect 5
  python -m model.cubicasa_points --root ~/cubicasa/cubicasa5k            # writes data/points/cubicasa_points.jsonl
  python -m model.cubicasa_points --root ~/cubicasa/cubicasa5k --check 5  # overlay PNGs for the 5-image check
  python -m model.cubicasa_points --root ~/cubicasa/cubicasa5k --heldout-eval   # M12 ground truth (eval only)

Mapping: dataset 'data/cubicasa5k/colorful-10052.png' -> '<root>/colorful/10052/model.svg'
(likewise high_quality-*, high_quality_architectural-*).

Output: one line per drawing, TRAINING split only (held-out drawings are never written):
  {"path": "data/cubicasa5k/colorful-10052.png", "items": [{"kind": "window", "xy": [0.41, 0.22]}, ...],
   "counts": {"window": 7, ...}, "agree": {"window": true, ...}}
xy is the item's bbox centre, normalised by the SVG's own width/height (the PNGs are renders of it).
"agree" compares our count with the questions.jsonl answer for the same drawing; build_sft only uses
points when the counts agree, so a mapping mistake costs coverage, not correctness.

Training use only, never as an answer lookup.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .common import REPO_ROOT, abs_path, is_heldout, load_questions, source_of, write_jsonl

OUT = REPO_ROOT / "data" / "points" / "cubicasa_points.jsonl"
# Held-out labels for M12's point-accuracy eval ONLY. Separate folder so build_sft (which reads
# data/points/*_points.jsonl by exact name) can never train on them.
EVAL_OUT = REPO_ROOT / "data" / "points" / "eval" / "cubicasa_heldout.jsonl"

# (kind, regex on the <g class="..."> attribute). First match wins; order matters.
KIND_RULES = [
    ("window", r"\bWindow\b"),
    ("door", r"\bDoor\b"),
    ("toilet", r"\b(Toilet|WC|Closet)\b"),
    ("sink", r"\b(Sink|WashBasin|Washbasin|Basin)\b"),
    ("bathtub", r"\b(Bathtub|BathTub|Bath)\b"),
    ("shower", r"\b(Shower)\b"),
]

# question prefix (EN, as in questions.jsonl) -> kinds counted
QUESTION_KINDS = {
    "How many windows": ["window"],
    "How many doors": ["door"],
    "How many toilet bowls": ["toilet"],
    "How many sinks and wash basins": ["sink"],
    "How many showers and bathtubs": ["shower", "bathtub"],
}

_NUM = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?")


def svg_for(path: str, root: Path) -> Path:
    stem = Path(path).stem  # colorful-10052 / high_quality_architectural-10500
    folder, num = stem.rsplit("-", 1)
    return root / folder / num / "model.svg"


def _size(svg: ET.Element) -> tuple[float, float]:
    vb = svg.get("viewBox")
    if vb:
        _, _, w, h = (float(v) for v in vb.replace(",", " ").split())
        return w, h
    return float(re.sub(r"[^\d.]", "", svg.get("width", "1"))), float(re.sub(r"[^\d.]", "", svg.get("height", "1")))


def _translate(el: ET.Element) -> tuple[float, float]:
    t = el.get("transform", "")
    m = re.search(r"translate\(\s*([-\d.e]+)[ ,]+([-\d.e]+)", t)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"matrix\(([^)]*)\)", t)
    if m:
        v = [float(x) for x in _NUM.findall(m.group(1))]
        if len(v) == 6:
            return v[4], v[5]
    return 0.0, 0.0


def _coords(el: ET.Element, dx: float = 0.0, dy: float = 0.0) -> list[tuple[float, float]]:
    """All coordinates under el (polygon/polyline points, rect, line, circle, simple path numbers)."""
    tx, ty = _translate(el)
    dx, dy = dx + tx, dy + ty
    tag = el.tag.rsplit("}", 1)[-1]
    pts: list[tuple[float, float]] = []
    if tag in ("polygon", "polyline"):
        nums = [float(v) for v in _NUM.findall(el.get("points", ""))]
        pts += [(nums[i] + dx, nums[i + 1] + dy) for i in range(0, len(nums) - 1, 2)]
    elif tag == "rect":
        x, y = float(el.get("x", 0)), float(el.get("y", 0))
        w, h = float(el.get("width", 0)), float(el.get("height", 0))
        pts += [(x + dx, y + dy), (x + w + dx, y + h + dy)]
    elif tag == "line":
        pts += [(float(el.get("x1", 0)) + dx, float(el.get("y1", 0)) + dy), (float(el.get("x2", 0)) + dx, float(el.get("y2", 0)) + dy)]
    elif tag in ("circle", "ellipse"):
        cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
        r = float(el.get("r", el.get("rx", 0)))
        pts += [(cx - r + dx, cy - r + dy), (cx + r + dx, cy + r + dy)]
    elif tag == "path":
        nums = [float(v) for v in _NUM.findall(re.sub(r"[a-z]", " ", el.get("d", "")))]  # absolute commands only
        pts += [(nums[i] + dx, nums[i + 1] + dy) for i in range(0, len(nums) - 1, 2)]
    for ch in el:
        if ch.tag.rsplit("}", 1)[-1] == "g" and ch.get("class") and _kind(ch.get("class")):
            continue  # nested annotated items are counted on their own
        pts += _coords(ch, dx, dy)
    return pts


def _kind(cls: str | None) -> str | None:
    if not cls:
        return None
    for kind, rx in KIND_RULES:
        if re.search(rx, cls):
            return kind
    return None


def parse_svg(svg_path: Path) -> tuple[list[dict], tuple[float, float]]:
    root = ET.parse(svg_path).getroot()
    w, h = _size(root)
    items = []

    def walk(el: ET.Element, dx: float, dy: float, inside: bool):
        tx, ty = _translate(el)
        cls = el.get("class")
        kind = _kind(cls) if el.tag.rsplit("}", 1)[-1] == "g" else None
        if kind and not inside:
            pts = _coords(el, dx, dy)
            if pts:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
                items.append({"kind": kind, "xy": [round(cx / w, 4), round(cy / h, 4)], "class": cls})
            inside = True  # parts of this item (e.g. a door's swing) aren't separate items
        for ch in el:
            walk(ch, dx + tx, dy + ty, inside)

    walk(root, 0.0, 0.0, False)
    return items, (w, h)


def gold_counts(questions: list[dict]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = collections.defaultdict(dict)
    for q in questions:
        if source_of(q["path"]) != "cubicasa5k":
            continue
        for prefix, kinds in QUESTION_KINDS.items():
            if q["question"].startswith(prefix):
                out[q["path"]]["+".join(kinds)] = q["answer"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path, help="unzipped cubicasa5k folder (contains colorful/, high_quality/, ...)")
    ap.add_argument("--inspect", type=int, default=0, help="print <g> class frequencies for N SVGs and exit")
    ap.add_argument("--check", type=int, default=0, help="write N overlay PNGs to data/points/check/ and exit")
    ap.add_argument("--heldout-eval", action="store_true",
                    help=f"M12: write HELD-OUT drawings only, to {EVAL_OUT.relative_to(REPO_ROOT)} (eval ground truth; "
                         "build_sft never reads it)")
    a = ap.parse_args()

    qs = load_questions()
    paths = sorted({q["path"] for q in qs if source_of(q["path"]) == "cubicasa5k"})

    if a.inspect:
        freq = collections.Counter()
        for p in paths[: a.inspect]:
            for g in ET.parse(svg_for(p, a.root)).getroot().iter():
                if g.get("class"):
                    freq[g.get("class")] += 1
        for cls, n in freq.most_common(60):
            print(f"{n:5d}  {cls!r:60s} -> {_kind(cls)}")
        return

    gold = gold_counts(qs)
    rows, stats = [], collections.Counter()
    for p in paths:
        if is_heldout(p) != a.heldout_eval:  # training labels: train split only; --heldout-eval: the reverse
            stats["skipped_other_split"] += 1
            continue
        svg = svg_for(p, a.root)
        if not svg.exists():
            stats["missing_svg"] += 1
            continue
        try:
            items, _ = parse_svg(svg)
        except ET.ParseError:
            stats["bad_svg"] += 1
            continue
        counts = collections.Counter(i["kind"] for i in items)
        agree = {}
        for key, g in gold.get(p, {}).items():
            n = sum(counts[k] for k in key.split("+"))
            agree[key] = n == g
            stats[f"agree_{key}"] += n == g
            stats[f"total_{key}"] += 1
        rows.append({"path": p, "items": [{"kind": i["kind"], "xy": i["xy"]} for i in items],
                     "counts": dict(counts), "agree": agree})

    if a.check:
        from PIL import Image, ImageDraw
        out_dir = OUT.parent / "check"
        out_dir.mkdir(parents=True, exist_ok=True)
        colors = {"window": "#1f5fad", "door": "#2c7a4b", "toilet": "#c8283a", "sink": "#9a5f06", "bathtub": "#6250d6", "shower": "#e87ba4"}
        for r in rows[: a.check]:
            img = Image.open(abs_path(r["path"])).convert("RGB")
            d = ImageDraw.Draw(img)
            for it in r["items"]:
                x, y = it["xy"][0] * img.width, it["xy"][1] * img.height
                d.ellipse([x - 6, y - 6, x + 6, y + 6], outline=colors.get(it["kind"], "black"), width=3)
            img.save(out_dir / Path(r["path"]).name)
            print(f"{r['path']}: counts {r['counts']}  agree {r['agree']}")
        print(f"overlays in {out_dir}: check that circles sit on the symbols")
        return

    out = EVAL_OUT if a.heldout_eval else OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(out, rows)
    print(f"wrote {len(rows)} drawings -> {out}")
    for key in QUESTION_KINDS.values():
        k = "+".join(key)
        if stats[f"total_{k}"]:
            print(f"  count agreement {k:15s} {stats[f'agree_{k}']}/{stats[f'total_{k}']} = {stats[f'agree_{k}'] / stats[f'total_{k}']:.0%}")
    print({k: v for k, v in stats.items() if not k.startswith(("agree_", "total_"))})


if __name__ == "__main__":
    main()
