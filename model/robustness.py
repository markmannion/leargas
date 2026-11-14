"""Scan-robustness check: degraded copies of the held-out raster images, scored like the clean set.

Judges upload their own scans, phone photos and JPEGs; every training image is a clean render. This
writes a mirror dataset root per degradation, with only the held-out eval images replaced, so the
normal eval runs unchanged against it:

    python -m model.robustness --out ~/degraded --modes scan,photo,lowres [--samples 3]
    JUNCTION_DATA=~/degraded/scan python -m model.baseline_eval --models gemma-ft --label gemma-ft-scan \
        --sets heldout_raster

Each mirror keeps the question path and file name (data/.../x.png), so answers score against the
same gold. Degradations are seeded per image, so reruns give identical files. Pillow only.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import random
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .common import DATASET_ROOT, load_jsonl
from .baseline_eval import RASTER_EVAL


def _jpeg(im: Image.Image, q: int) -> Image.Image:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=q)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _noise(im: Image.Image, sigma: float, alpha: float) -> Image.Image:
    n = Image.effect_noise(im.size, sigma).convert("RGB")
    return Image.blend(im, n, alpha)


def _rotate(im: Image.Image, deg: float) -> Image.Image:
    return im.rotate(deg, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))


def scan(im: Image.Image, rng: random.Random) -> Image.Image:
    """Office scanner / photocopy: grey, slightly skewed, soft, speckled, low-quality JPEG."""
    im = ImageOps.grayscale(im).convert("RGB")
    im = _rotate(im, rng.uniform(-2.0, 2.0))
    im = im.filter(ImageFilter.GaussianBlur(0.8))
    im = ImageEnhance.Contrast(im).enhance(0.75)
    im = _noise(im, 40, 0.10)
    return _jpeg(im, 35)


def photo(im: Image.Image, rng: random.Random) -> Image.Image:
    """Phone photo of a printout: rotated, warm paper tint, uneven light, soft focus, JPEG."""
    im = _rotate(im.convert("RGB"), rng.uniform(-5.0, 5.0))
    w, h = im.size
    r, g, b = im.split()
    im = Image.merge("RGB", (r, g.point(lambda v: int(v * 0.95)), b.point(lambda v: int(v * 0.82))))
    # light falls off across the sheet: up to 35% darker on one side
    side = rng.choice(["l", "r", "t", "b"])
    ramp = Image.linear_gradient("L").resize((w, h))
    ramp = {"t": ramp, "b": ramp.rotate(180), "l": ramp.rotate(90, expand=True).resize((w, h)),
            "r": ramp.rotate(-90, expand=True).resize((w, h))}[side]
    shade = ramp.point(lambda v: int(255 - 0.35 * v))
    im = Image.composite(im, Image.new("RGB", (w, h), (0, 0, 0)), shade)
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    return _jpeg(_noise(im, 25, 0.06), 50)


def lowres(im: Image.Image, rng: random.Random) -> Image.Image:
    """Low-resolution screenshot / fax: under half size, heavy JPEG."""
    w, h = im.size
    f = rng.uniform(0.40, 0.50)
    im = im.convert("RGB").resize((max(1, int(w * f)), max(1, int(h * f))), Image.BILINEAR)
    return _jpeg(im, 30)


MODES = {"scan": scan, "photo": photo, "lowres": lowres}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--modes", default="scan,photo,lowres")
    ap.add_argument("--samples", type=int, default=3, help="also write N before/after pairs to <out>/samples")
    a = ap.parse_args()

    rows = load_jsonl(RASTER_EVAL)
    images = sorted({r["image"] for r in rows})
    out = Path(a.out).expanduser()
    for mode in a.modes.split(","):
        fn = MODES[mode]
        root = out / mode
        root.mkdir(parents=True, exist_ok=True)
        q = root / "questions.jsonl"
        if not q.exists():
            os.symlink(DATASET_ROOT / "questions.jsonl", q)
        for i, rel in enumerate(images):
            dst = root / rel
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            seed = int(hashlib.md5(f"{mode}:{rel}".encode()).hexdigest()[:8], 16)
            src = Image.open(DATASET_ROOT / rel)
            if src.mode in ("RGBA", "LA", "P"):  # flatten transparency on white
                src = src.convert("RGBA")
                bg = Image.new("RGBA", src.size, (255, 255, 255, 255))
                src = Image.alpha_composite(bg, src)
            im = fn(src.convert("RGB"), random.Random(seed))
            im.save(dst)  # same name (.png), degraded content
            if i < a.samples:
                s = out / "samples"
                s.mkdir(exist_ok=True)
                stem = Path(rel).stem
                src.convert("RGB").save(s / f"{stem}__clean.png")
                im.save(s / f"{stem}__{mode}.png")
        print(f"{mode}: {len(images)} images -> {root}")


if __name__ == "__main__":
    main()
