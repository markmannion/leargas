"""model.crop: coordinate round trip, synthetic sheet detection, and the engine maps crop points back."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from model import crop  # noqa: E402
from model.common import abs_path  # noqa: E402


def test_round_trip():
    box = (0.2, 0.1, 0.7, 0.6)
    for pt in ([0.2, 0.1], [0.45, 0.35], [0.7, 0.6]):
        c = crop.sheet_to_crop(pt, box)
        back = crop.crop_to_sheet(c, box)
        assert all(abs(a - b) < 1e-9 for a, b in zip(back, pt))
    assert crop.sheet_to_crop([0.1, 0.5], box) is None


def test_synthetic_sheet():
    from PIL import Image, ImageDraw
    W, H = 2480, 1753
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    d.rectangle([60, 60, W - 60, H - 60], outline=0, width=2)        # frame
    d.line([60, int(H * 0.83), W - 60, int(H * 0.83)], fill=0, width=2)  # legend separator
    d.rectangle([100, int(H * 0.86), 400, int(H * 0.9)], fill=0)        # legend ink (must be excluded)
    d.rectangle([900, 200, 1700, 1100], outline=0, width=8)            # the plan
    x0, y0, x1, y1 = crop.plan_box(img)
    assert 0.33 < x0 < 900 / W and 1700 / W < x1 < 0.72, (x0, x1)
    assert 0.08 < y0 < 200 / H and 1100 / H < y1 < 0.68, (y0, y1)


def test_engine_maps_points_back():
    png = "data/swiss_dwellings/site2297_bldg3392_floor15123.png"
    if not abs_path(png).exists():
        return  # dataset not on this machine
    from model import gemma_engine as ge
    seen = {}

    def ask(image, question, model, with_points=False, timeout=60):
        seen["size"] = image.size
        return {"ok": True, "abstained": False, "latency_ms": 5, "reason": None, "answer": 1, "unit": "count",
                "confidence": 0.999, "points": [[0.5, 0.5]]}
    os.environ["GEMMA_CROP_SWISS"] = "1"
    try:
        a = ge.answer(png.replace(".png", ".pdf"), "How many lifts?", engine="gemma_ft", label="none", ask_fn=ask)
    finally:
        os.environ.pop("GEMMA_CROP_SWISS")
    box = crop.box_for(png)
    assert seen["size"][0] < 2480 * 0.8
    pt = a["evidence"][0]["shape"]["point"]
    assert abs(pt[0] - (box[0] + box[2]) / 2) < 1e-6 and abs(pt[1] - (box[1] + box[3]) / 2) < 1e-6


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
