"""Scan/photo augmentation for an SFT file: a fraction of rows get a randomly degraded copy of their image.

    python -m model.augment_sft --data data/sft/spec_cc.jsonl --out data/sft/spec_cc_aug.jsonl \
        --img-dir ~/aug/spec_cc --frac 0.5

Each augmented row's "image" becomes an absolute path to its own degraded PNG (abs_path() leaves
absolute paths alone, so train_lora needs no change). The ops and strengths are drawn at random per
row (grey, skew, paper tint + uneven light, blur, low contrast, noise, downscale, JPEG), on purpose
NOT the three fixed recipes in model/robustness.py, so the held-out robustness check is not just
measuring those recipes. Held-out drawings are refused. Runs where the dataset images are (the box).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import random
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .common import abs_path, is_heldout, load_jsonl
from .robustness import _jpeg, _noise, _rotate


def degrade(im: Image.Image, rng: random.Random) -> Image.Image:
    im = im.convert("RGB")
    if rng.random() < 0.5:
        im = ImageOps.grayscale(im).convert("RGB")
    if rng.random() < 0.7:
        im = _rotate(im, rng.uniform(-6, 6))
    if rng.random() < 0.4:  # paper tint + light falloff from one side
        w, h = im.size
        r, g, b = im.split()
        gk, bk = rng.uniform(0.9, 1.0), rng.uniform(0.75, 0.95)
        im = Image.merge("RGB", (r, g.point(lambda v: int(v * gk)), b.point(lambda v: int(v * bk))))
        ramp = Image.linear_gradient("L").rotate(rng.choice([0, 90, 180, 270]), expand=True).resize((w, h))
        k = rng.uniform(0.1, 0.4)
        im = Image.composite(im, Image.new("RGB", (w, h), (0, 0, 0)), ramp.point(lambda v: int(255 - k * v)))
    if rng.random() < 0.4:
        f = rng.uniform(0.35, 0.9)
        im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.BILINEAR)
    if rng.random() < 0.6:
        im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.6)))
    if rng.random() < 0.6:
        im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.55, 1.0))
    if rng.random() < 0.5:
        im = _noise(im, rng.uniform(15, 45), rng.uniform(0.03, 0.12))
    if rng.random() < 0.8:
        im = _jpeg(im, rng.randint(25, 80))
    return im


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--img-dir", required=True)
    ap.add_argument("--frac", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    a = ap.parse_args()

    rows = load_jsonl(Path(a.data))
    img_dir = Path(a.img_dir).expanduser()
    img_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    out_rows, jobs = [], []
    for r in rows:
        if is_heldout(r["image"]):
            raise SystemExit(f"held-out drawing in training data: {r['image']}")
        if rng.random() < a.frac:
            seed = int(hashlib.md5(f"{a.seed}:{r['id']}".encode()).hexdigest()[:8], 16)
            dst = img_dir / f"{r['id']}.png"
            if not dst.exists():
                jobs.append((r["image"], str(dst), seed))
            r = {**r, "image": str(dst), "aug_of": r["image"]}
        out_rows.append(r)
    with multiprocessing.Pool(a.workers) as pool:
        for i, _ in enumerate(pool.imap_unordered(_make, jobs, chunksize=4), 1):
            if i % 500 == 0:
                print(f"  {i}/{len(jobs)} images", flush=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_aug = sum("aug_of" in r for r in out_rows)
    print(f"wrote {a.out}: {len(rows)} rows, {n_aug} augmented ({len(jobs)} new images) -> {img_dir}")


def _make(job: tuple[str, str, int]) -> None:
    rel, dst, seed = job
    src = Image.open(abs_path(rel))
    if src.mode in ("RGBA", "LA", "P"):
        src = src.convert("RGBA")
        src = Image.alpha_composite(Image.new("RGBA", src.size, (255, 255, 255, 255)), src)
    tmp = dst + ".tmp.png"
    degrade(src, random.Random(seed)).save(tmp)
    os.replace(tmp, dst)  # a killed run never leaves a half-written image behind


if __name__ == "__main__":
    main()
