"""Rooms, doors and windows from the lines of a raster floor plan.

1. Walls: dark strokes that survive a morphological opening. Thin lines (furniture, door swings,
   glazing, text) are removed; filled walls stay.
2. Gaps: openings in a wall line are closed with long horizontal and vertical kernels. A closed
   piece only counts as an opening if it is a thin strip (about one wall thick), so a whole narrow
   room is never filled in by mistake. An opening with glazing lines in the original is a window;
   an empty one is a door (or a plain passage).
3. Rooms: flood fill from the centre of each room label inside the closed walls. Area = pixels /
   px_per_m², measured to the wall faces. Perimeter = the fill's outline; skirting = perimeter
   minus the door openings on it.

All of this is an estimate. A fill that leaks outside the building or swallows other labels is
reported as a failure, never as a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Optional, Tuple

import numpy as np

WORK_PPM = 45.0  # work at about 2.2 cm per pixel: enough for walls, fast on a 14000 px sheet


@dataclass
class Gap:
    kind: str  # "door" | "window" | "fill"
    box: Tuple[int, int, int, int]  # x0, y0, x1, y1 in work pixels
    width_m: float


@dataclass
class Plan:
    f: float  # work pixels per raster pixel
    ppm: float  # work pixels per metre
    walls: np.ndarray  # bool, closed walls (openings filled)
    gaps: List[Gap]
    labels: np.ndarray  # int32 labelled free space
    building: Tuple[int, int, int, int]
    gap_mask: np.ndarray  # int32: index+1 of the gap at each pixel


@dataclass
class Room:
    label: str
    area_m2: float
    perimeter_m: float
    doors: List[Gap] = field(default_factory=list)
    windows: List[Gap] = field(default_factory=list)
    polygon: List[Tuple[float, float]] = field(default_factory=list)  # raster pixels
    problem: Optional[str] = None

    @property
    def door_width_m(self) -> float:
        return sum(d.width_m for d in self.doors)

    @property
    def skirting_m(self) -> float:
        return max(self.perimeter_m - self.door_width_m, 0.0)


def _odd(n: float) -> int:
    n = max(3, int(round(n)))
    return n if n % 2 else n + 1


@lru_cache(maxsize=4)
def analyse(raster: str, px_per_m: float) -> Plan:
    import cv2
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(raster).convert("L")
    f = min(1.0, WORK_PPM / px_per_m)
    if f < 1.0:
        im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.Resampling.BOX)
    g = np.asarray(im)
    ppm = px_per_m * f
    dark = (g < 150).astype(np.uint8)

    # 1. walls: strokes thicker than ~6 cm survive
    k = _odd(0.07 * ppm)
    walls = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))

    # 2. openings: close along each axis, keep only thin strips
    # several passes with longer kernels: small gaps close first and become wall, so a long
    # kernel later cannot merge them with their neighbours into one blob
    max_thick = 0.9 * ppm
    gap_mask = np.zeros(walls.shape, np.int32)
    gaps: List[Gap] = []
    closed = walls.copy()
    for L_m, axis in [(L, a) for L in (1.1, 1.6, 2.2, 3.2, 4.5) for a in ("h", "v")]:
        L = int(round(L_m * ppm))
        kern = cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1) if axis == "h" else (1, L))
        new = cv2.morphologyEx(closed, cv2.MORPH_CLOSE, kern) & (1 - closed)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(new, connectivity=4)
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            thick, length = (h, w) if axis == "h" else (w, h)
            # an opening is a strip along the wall: long and thin. A filled-in room is not.
            if thick > max_thick or thick < 0.04 * ppm or length < max(0.5 * ppm, 1.3 * thick):
                continue
            if area < 0.6 * w * h:
                continue
            # glazing lines are thin and grey after downsampling, so look for any ink, not dark ink
            orig = g[y:y + h, x:x + w] < 225
            glazing = orig.mean() if orig.size else 0
            if thick > 0.45 * ppm:
                kind = "fill"  # a recess between wall ends: closed, but not an opening
            elif glazing > 0.12:
                kind = "window"
            elif length <= 2.1 * ppm:
                kind = "door"
            else:
                continue  # a long empty gap is an open passage: leave it open
            gaps.append(Gap(kind, (x, y, x + w, y + h), length / ppm))
            sel = lab[y:y + h, x:x + w] == i
            closed[y:y + h, x:x + w][sel] = 1
            gap_mask[y:y + h, x:x + w][sel] = len(gaps)

    # building extent: the big wall components (title block and logo are small)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    big = [i for i in range(1, n) if stats[i][4] > 0.02 * closed.sum()] if n > 1 else []
    if big:
        x0 = min(stats[i][0] for i in big)
        y0 = min(stats[i][1] for i in big)
        x1 = max(stats[i][0] + stats[i][2] for i in big)
        y1 = max(stats[i][1] + stats[i][3] for i in big)
    else:
        x0, y0, x1, y1 = 0, 0, closed.shape[1], closed.shape[0]
    gaps_in = []
    remap = np.zeros(len(gaps) + 1, np.int32)
    for idx, gp in enumerate(gaps, start=1):
        cx, cy = (gp.box[0] + gp.box[2]) / 2, (gp.box[1] + gp.box[3]) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            gaps_in.append(gp)
            remap[idx] = len(gaps_in)
    gap_mask = remap[gap_mask]

    free = (1 - closed).astype(np.uint8)
    _, labels = cv2.connectedComponents(free, connectivity=4)
    return Plan(f, ppm, closed.astype(bool), gaps_in, labels.astype(np.int32), (x0, y0, x1, y1), gap_mask)


def room_at(plan: Plan, label: str, cx: float, cy: float, other_labels: List[Tuple[str, float, float]]) -> Room:
    """The room around a label centre (raster pixels)."""
    import cv2

    f, ppm = plan.f, plan.ppm
    x, y = int(cx * f), int(cy * f)
    H, W = plan.labels.shape
    if not (0 <= x < W and 0 <= y < H):
        return Room(label, 0, 0, problem="label is outside the image")
    lid = plan.labels[y, x]
    if lid == 0:  # label centre fell on a wall pixel: look nearby
        r = int(0.3 * ppm)
        win = plan.labels[max(0, y - r):y + r, max(0, x - r):x + r]
        vals, counts = np.unique(win[win > 0], return_counts=True)
        if len(vals) == 0:
            return Room(label, 0, 0, problem="no free space at the label")
        lid = vals[np.argmax(counts)]
    mask = plan.labels == lid
    ys, xs = np.nonzero(mask)
    bx0, by0, bx1, by1 = plan.building
    if xs.min() <= bx0 + 1 or ys.min() <= by0 + 1 or xs.max() >= bx1 - 2 or ys.max() >= by1 - 2:
        return Room(label, 0, 0, problem="the outline is not closed (the fill reached the outside)")
    inside = [o for o, ox, oy in other_labels
              if 0 <= int(oy * f) < H and 0 <= int(ox * f) < W and plan.labels[int(oy * f), int(ox * f)] == lid]
    area = mask.sum() / ppm ** 2
    m8 = mask.astype(np.uint8)
    contours, _ = cv2.findContours(m8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(contours, key=cv2.contourArea)
    approx = cv2.approxPolyDP(c, 0.05 * ppm, True)
    perim = cv2.arcLength(approx, True) / ppm
    # openings touching this room
    ring = cv2.dilate(m8, np.ones((5, 5), np.uint8)).astype(bool) & ~mask
    ids = np.unique(plan.gap_mask[ring])
    touching = [plan.gaps[i - 1] for i in ids if i > 0]
    room = Room(label, float(area), float(perim),
                doors=[gp for gp in touching if gp.kind == "door"],
                windows=[gp for gp in touching if gp.kind == "window"],
                polygon=[(float(p[0][0]) / f, float(p[0][1]) / f) for p in approx])
    if inside:
        room.problem = f"the outline also contains {', '.join(sorted(set(inside)))}, so rooms may be merged"
    return room


def gaps_in_building(plan: Plan) -> List[Gap]:
    return plan.gaps


def gap_box_raster(plan: Plan, gp: Gap) -> Tuple[float, float, float, float]:
    x0, y0, x1, y1 = gp.box
    return (x0 / plan.f, y0 / plan.f, x1 / plan.f, y1 / plan.f)


# ------------------------------------------------------------------------------------ thin-line regions (slabs)

SLAB_PPM = 60.0


@lru_cache(maxsize=4)
def _ink(raster: str, px_per_m: float):
    import cv2
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(raster).convert("L")
    f = min(1.0, SLAB_PPM / px_per_m)
    if f < 1.0:
        im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.Resampling.BOX)
    ink = (np.asarray(im) < 230).astype(np.uint8)
    ink = cv2.dilate(ink, np.ones((3, 3), np.uint8))  # seal dashed lines
    return f, ink


def outline_region(raster: str, px_per_m: float, seed: Tuple[float, float],
                   erase: List[Tuple[float, float, float, float]]) -> Optional[Tuple[float, List[Tuple[float, float]]]]:
    """Closed region around `seed` inside thin ink lines, with `erase` boxes (raster px) cleared first.

    Holes (hatching, symbols) are filled: the area is the outer outline. Returns (m², polygon in
    raster px) or None if the region leaks to the sheet edge or covers most of the sheet."""
    import cv2

    f, ink = _ink(raster, px_per_m)
    ink = ink.copy()
    for x0, y0, x1, y1 in erase:
        ink[max(0, int(y0 * f)):int(y1 * f) + 1, max(0, int(x0 * f)):int(x1 * f) + 1] = 0
    free = (1 - ink).astype(np.uint8)
    H, W = free.shape
    sx, sy = int(seed[0] * f), int(seed[1] * f)
    if not (0 <= sx < W and 0 <= sy < H) or not free[sy, sx]:
        return None
    mask = np.zeros((H + 2, W + 2), np.uint8)
    cv2.floodFill(free, mask, (sx, sy), 2, flags=4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY)
    region = mask[1:-1, 1:-1] > 0
    ys, xs = np.nonzero(region)
    if xs.min() <= 1 or ys.min() <= 1 or xs.max() >= W - 2 or ys.max() >= H - 2 or region.mean() > 0.4:
        return None
    contours, _ = cv2.findContours(region.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(contours, key=cv2.contourArea)
    ppm = px_per_m * f
    area = cv2.contourArea(c) / ppm ** 2
    approx = cv2.approxPolyDP(c, 0.1 * ppm, True)
    return float(area), [(float(p[0][0]) / f, float(p[0][1]) / f) for p in approx]
