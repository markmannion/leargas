"""Crop swiss sheets to the floor plan (finding 4 in HANDOFF: the plan fills ~1/3 of a 2480x1753 sheet,
so at a 1600 px / 560-token budget the symbols are tiny and base Gemma under-counts by ~1.5).

Every swiss render has the same layout: an outer frame, a full-width separator line above the
legend/title strip, and the plan in between. We find those lines, take the ink bbox inside, and pad it.

    python -m model.crop --stats 300                  # crop-area stats + failures on a sample
    python -m model.crop --preview 8                  # sheet with the box drawn -> scratch/preview dir
    python -m model.crop --write                      # data/swiss_dwellings_crop/<stem>.png + boxes.json
                                                      #   (under JUNCTION_DATA, so abs_path() finds them)

Coordinates: `box` is (x0, y0, x1, y1) normalised 0-1 on the sheet. sheet_to_crop / crop_to_sheet map
[x, y] points between the two frames, so point labels and predicted points stay on the sheet for the UI.
Stdlib + Pillow only.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from functools import lru_cache
from pathlib import Path
from typing import Any

from .common import DATASET_ROOT, abs_path

CROP_DIR = "data/swiss_dwellings_crop"
BOXES = DATASET_ROOT / CROP_DIR / "boxes.json"
WORK_W = 620  # detection runs on a ~1/4-scale copy
PAD = 0.015   # of the sheet's long side


def _gray(img) -> Any:
    from PIL import Image
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    return img.convert("L")


def _line_groups(counts: list[int], thresh: float) -> list[tuple[int, int]]:
    out, start = [], None
    for i, c in enumerate(counts + [0]):
        if c >= thresh and start is None:
            start = i
        elif c < thresh and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def plan_box(img) -> tuple[float, float, float, float]:
    """Sheet image -> normalised (x0, y0, x1, y1) of the plan. Falls back to the whole sheet."""
    from PIL import Image, ImageFilter

    g = _gray(img)
    W0, H0 = g.size
    s = WORK_W / W0
    # 1-px frame/separator lines vanish in a plain downscale: thicken dark strokes first, then box-average.
    k = max(3, (round(1 / s) // 2) * 2 + 1)
    g = g.filter(ImageFilter.MinFilter(k)).resize((WORK_W, max(1, round(H0 * s))), Image.BOX)
    W, H = g.size
    dark = g.point(lambda v: 255 if v < 160 else 0)
    px = dark.load()
    rows = [sum(1 for x in range(W) if px[x, y]) for y in range(H)]
    cols = [sum(1 for y in range(H) if px[x, y]) for x in range(W)]

    hl = _line_groups(rows, 0.6 * W)  # frame top/bottom + legend separator
    vl = _line_groups(cols, 0.6 * H)  # frame left/right
    top = hl[0][1] + 1 if hl and hl[0][0] < 0.15 * H else 0
    bottom = H
    if len(hl) >= 2:
        # separator = lowest full-width line above the bottom frame, in the lower half of the sheet
        inner = [gr for gr in hl[1:] if 0.5 * H < gr[0] < 0.97 * H]
        if inner:
            bottom = inner[0][0]
        elif hl[-1][0] > 0.85 * H:
            bottom = hl[-1][0]
    left = vl[0][1] + 1 if vl and vl[0][0] < 0.15 * W else 0
    right = vl[-1][0] if vl and vl[-1][0] > 0.85 * W else W

    m = 2  # stay clear of the frame lines themselves
    region = (left + m, top + m, right - m, bottom - m)
    if region[2] - region[0] < 0.2 * W or region[3] - region[1] < 0.2 * H:
        return (0.0, 0.0, 1.0, 1.0)
    bb = dark.crop(region).getbbox()
    if not bb:
        return (0.0, 0.0, 1.0, 1.0)
    x0, y0 = (region[0] + bb[0]) / W, (region[1] + bb[1]) / H
    x1, y1 = (region[0] + bb[2]) / W, (region[1] + bb[3]) / H
    px_, py_ = PAD * max(W0, H0) / W0, PAD * max(W0, H0) / H0
    return (max(0.0, x0 - px_), max(0.0, y0 - py_), min(1.0, x1 + px_), min(1.0, y1 + py_))


def crop_image(img, box):
    w, h = img.size
    return img.crop((round(box[0] * w), round(box[1] * h), round(box[2] * w), round(box[3] * h)))


def sheet_to_crop(pt, box) -> list[float] | None:
    """[x, y] on the sheet -> [x, y] on the crop, or None if it falls outside."""
    x = (pt[0] - box[0]) / (box[2] - box[0])
    y = (pt[1] - box[1]) / (box[3] - box[1])
    return [x, y] if 0 <= x <= 1 and 0 <= y <= 1 else None


def crop_to_sheet(pt, box) -> list[float]:
    return [box[0] + pt[0] * (box[2] - box[0]), box[1] + pt[1] * (box[3] - box[1])]


@lru_cache(maxsize=1)
def saved_boxes() -> dict[str, list[float]]:
    return json.loads(BOXES.read_text(encoding="utf-8")) if BOXES.exists() else {}


def crop_path(png_path: str) -> str:
    return f"{CROP_DIR}/{Path(png_path).stem}.png"


def box_for(png_path: str, img=None) -> tuple[float, float, float, float]:
    b = saved_boxes().get(Path(png_path).stem)
    if b:
        return tuple(b)  # type: ignore[return-value]
    from PIL import Image
    return plan_box(img if img is not None else Image.open(abs_path(png_path)))


def cropped(png_path: str):
    """(PIL image of the plan, box) for a swiss PNG path ('data/swiss_dwellings/x.png' or absolute)."""
    from PIL import Image
    p = Path(png_path)
    img = Image.open(p if p.is_absolute() else abs_path(png_path))
    box = box_for(png_path, img)
    return crop_image(img, box), box


def _swiss_pngs() -> list[str]:
    d = DATASET_ROOT / "data" / "swiss_dwellings"
    return sorted(f"data/swiss_dwellings/{p.name}" for p in d.glob("*.png"))


def main() -> None:
    from PIL import Image, ImageDraw

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stats", type=int, default=0, help="sample size for crop-area stats")
    ap.add_argument("--preview", type=int, default=0)
    ap.add_argument("--preview-dir", type=Path, default=Path("data/crop_preview"))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    paths = _swiss_pngs()
    rng = random.Random(3)

    if a.stats:
        fr, full = [], 0
        for p in rng.sample(paths, min(a.stats, len(paths))):
            b = plan_box(Image.open(abs_path(p)))
            if b == (0.0, 0.0, 1.0, 1.0):
                full += 1
            fr.append((b[2] - b[0]) * (b[3] - b[1]))
        q = statistics.quantiles(fr, n=10)
        print(f"{len(fr)} sheets: crop area / sheet area median {statistics.median(fr):.2f}, "
              f"p10 {q[0]:.2f}, p90 {q[-1]:.2f}, min {min(fr):.2f}, max {max(fr):.2f}; fell back to full sheet: {full}")
    if a.preview:
        a.preview_dir.mkdir(parents=True, exist_ok=True)
        for p in rng.sample(paths, min(a.preview, len(paths))):
            img = _gray(Image.open(abs_path(p))).convert("RGB")
            b = plan_box(img)
            w, h = img.size
            ImageDraw.Draw(img).rectangle([b[0] * w, b[1] * h, b[2] * w, b[3] * h], outline=(220, 0, 0), width=8)
            img.resize((w // 3, h // 3)).save(a.preview_dir / f"{Path(p).stem}.png")
        print(f"previews -> {a.preview_dir}")
    if a.write:
        out = DATASET_ROOT / CROP_DIR
        out.mkdir(parents=True, exist_ok=True)
        boxes = {}
        for i, p in enumerate(paths[: a.limit or None]):
            img = Image.open(abs_path(p))
            b = plan_box(img)
            boxes[Path(p).stem] = [round(v, 5) for v in b]
            crop_image(_gray(img), b).save(out / f"{Path(p).stem}.png", optimize=True)
            if i % 100 == 0:
                print(f"{i}/{len(paths)}")
        BOXES.write_text(json.dumps(boxes, indent=0, sort_keys=True), encoding="utf-8")
        print(f"wrote {len(boxes)} crops + {BOXES}")


if __name__ == "__main__":
    main()
