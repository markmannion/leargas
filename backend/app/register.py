"""Register Swiss Dwellings DXF geometry onto the sheet image (PNG twin, or the PDF page).

DXF coordinates are world metres, y up. Each Swiss sheet is a matplotlib render of the same
geometry on an A3 page: an outer frame, the plan in the middle, and a legend/title strip below a
full-width separator line. The plan is drawn at a standard scale (1:100 or 1:200 so far), axis
aligned, with equal x/y scale. So the mapping is a scale + translation with a y flip:

    u = tx + s_x * x        v = ty - s_y * y        (u, v normalized 0-1 on the page)

Fit
  1. Find the plan region (inside the frame, above the separator) and its ink bounding box.
  2. Compare it with the DXF extents of the drawn layers (walls, windows, doors, fixtures, outlines):
     the x and y scale estimates must agree (aspect check). Some plans are clipped by the frame
     (door swings past the edge); then the scale comes from the unclipped axis only.
  3. Snap the scale to the nearest standard drawing scale (1:N at the image dpi) when it is within
     SNAP_TOL; centre the DXF extents on the ink box.
  4. Refine the translation by a few pixels to put wall/window/door outlines on ink (keeping the
     best scale candidate), then verify:
     the fraction of sampled outline points that land on ink (`hit_rate`) must reach MIN_HIT_RATE.
Any failed check returns None: callers must then show no evidence rather than misplaced evidence.

The PDF and the PNG twin are saves of the same matplotlib figure (same page, same dpi), so a
transform fitted on the PNG is valid in normalized coordinates on a rendered PDF page too.

    from app.register import dxf_to_image
    t = dxf_to_image("…/site107_bldg107_floor427.png")   # or the .pdf / .dxf path
    u, v = t(x, y)                                        # normalized 0-1 on the sheet
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

DRAWN_LAYERS = ("WALL", "WINDOW", "DOOR", "FIXTURE", "ROOM_OUTLINE", "UNIT_OUTLINE")
CHECK_LAYERS = ("WALL", "WINDOW", "DOOR")  # crisp black outlines, used to verify the fit
STANDARD_SCALES = (20, 25, 50, 75, 100, 150, 200, 250, 300, 400, 500, 750, 1000)
INK = 200            # grey level below which a pixel counts as ink
LINE = 0.6           # a frame/separator line spans this fraction of the sheet
ASPECT_TOL = 0.03    # x and y scale estimates from the bbox must agree this well
SNAP_TOL = 0.015     # snap to a standard scale when the bbox estimate is this close
MIN_HIT_RATE = 0.9   # fraction of outline samples that must land on ink (within 1 px)
SEARCH_PX = 4        # translation refinement window, pixels each way
MAX_CLIP = 0.1       # beyond ASPECT_TOL, treat the short axis as clipped up to this mismatch
STROKE_PX = 8        # ink may overhang the geometry by this much (stroke widths)
SAMPLE_STEP = 0.1    # metres between outline samples


@dataclass(frozen=True)
class Transform:
    """DXF world metres (y up) -> normalized 0-1 coordinates on a sheet image (y down)."""

    sx: float              # normalized units per metre, x
    sy: float              # normalized units per metre, y (the flip is in __call__)
    tx: float
    ty: float
    image: str             # the raster the fit was measured on
    size: Tuple[int, int]  # its pixel size (w, h)
    scale: Optional[int]   # N of the 1:N drawing scale when snapped, else None
    hit_rate: float        # fraction of outline samples on ink after the fit
    aspect_error: float    # |s_x/s_y - 1| of the raw bbox estimate

    def __call__(self, x: float, y: float) -> Tuple[float, float]:
        return (self.tx + self.sx * x, self.ty - self.sy * y)

    def points(self, pts: Iterable[Sequence[float]], clamp: bool = True) -> List[Tuple[float, float]]:
        out = []
        for p in pts:
            u, v = self(p[0], p[1])
            if clamp:
                u, v = min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0)
            out.append((u, v))
        return out

    def to_pixels(self, x: float, y: float) -> Tuple[float, float]:
        u, v = self(x, y)
        return (u * self.size[0], v * self.size[1])

    def to_dict(self) -> dict:
        return {"sx": self.sx, "sy": self.sy, "tx": self.tx, "ty": self.ty, "image": self.image,
                "size": list(self.size), "scale": self.scale, "hit_rate": self.hit_rate,
                "aspect_error": self.aspect_error}


# ------------------------------------------------------------------------------------ raster side

def _gray(path: Path):
    import numpy as np
    from PIL import Image

    img = Image.open(path)
    dpi = img.info.get("dpi", (150.0, 150.0))[0] or 150.0
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    return np.asarray(img.convert("L")), float(dpi)


def _groups(idx) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for i in idx.tolist():
        if out and i == out[-1][1] + 1:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return out


def plan_region(gray) -> Optional[Tuple[int, int, int, int]]:
    """(x0, y0, x1, y1) pixels inside the frame and above the legend separator, or None."""
    import numpy as np

    dark = gray < 160
    H, W = dark.shape
    hl = _groups(np.where(dark.sum(1) >= LINE * W)[0])
    vl = _groups(np.where(dark.sum(0) >= LINE * H)[0])
    if len(hl) < 3 or len(vl) < 2:
        return None
    top, bottom_frame = hl[0], hl[-1]
    sep = hl[-2]  # the lowest full-width line above the bottom frame is the legend separator
    if not (top[0] < 0.15 * H and sep[0] > 0.5 * H and bottom_frame[0] > 0.85 * H):
        return None
    left, right = vl[0], vl[-1]
    if not (left[0] < 0.15 * W and right[0] > 0.85 * W):
        return None
    m = 3
    return (left[1] + 1 + m, top[1] + 1 + m, right[0] - m, sep[0] - m)


def _ink_bbox(gray, region) -> Optional[Tuple[int, int, int, int]]:
    import numpy as np

    x0, y0, x1, y1 = region
    ink = gray[y0:y1, x0:x1] < INK
    rows, cols = np.where(ink.any(1))[0], np.where(ink.any(0))[0]
    if not len(rows) or not len(cols):
        return None
    return (x0 + int(cols[0]), y0 + int(rows[0]), x0 + int(cols[-1]) + 1, y0 + int(rows[-1]) + 1)


# ------------------------------------------------------------------------------------ DXF side

def _dxf_geometry(dxf: Path):
    """(extents (xmin, ymin, xmax, ymax) of the drawn layers, outline sample points (n, 2))."""
    import ezdxf
    import numpy as np
    from ezdxf import bbox

    msp = ezdxf.readfile(dxf).modelspace()
    drawn = [e for e in msp if e.dxf.layer in DRAWN_LAYERS]
    if not drawn:
        return None, None
    ext = bbox.extents(drawn)
    if not ext.has_data:
        return None, None
    samples = []
    for e in drawn:
        if e.dxf.layer not in CHECK_LAYERS or e.dxftype() != "LWPOLYLINE":
            continue
        pts = [(p[0], p[1]) for p in e.get_points("xy")]
        if e.closed and len(pts) > 2:
            pts.append(pts[0])
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            n = max(1, int(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 / SAMPLE_STEP))
            t = np.linspace(0.0, 1.0, n + 1)
            samples.append(np.stack([ax + (bx - ax) * t, ay + (by - ay) * t], 1))
    pts = np.concatenate(samples) if samples else np.zeros((0, 2))
    return (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y), pts


# ------------------------------------------------------------------------------------ fit

def _near_ink(gray):
    """Ink mask dilated by one pixel (3x3)."""
    import numpy as np

    ink = gray < INK
    out = ink.copy()
    out[1:, :] |= ink[:-1, :]
    out[:-1, :] |= ink[1:, :]
    row = out.copy()
    out[:, 1:] |= row[:, :-1]
    out[:, :-1] |= row[:, 1:]
    return out


def _hits(mask, px, py) -> float:
    import numpy as np

    H, W = mask.shape
    xi, yi = np.rint(px).astype(int), np.rint(py).astype(int)
    inside = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
    if not inside.any():
        return 0.0
    hit = np.zeros(len(xi), bool)
    hit[inside] = mask[yi[inside], xi[inside]]
    return float(hit.mean())


def register(dxf: Path, image: Path) -> Optional[Transform]:
    """Fit DXF -> image for one Swiss sheet; None when the fit fails any check."""
    gray, dpi = _gray(image)
    H, W = gray.shape
    region = plan_region(gray)
    if region is None:
        return None
    box = _ink_bbox(gray, region)
    ext, samples = _dxf_geometry(dxf)
    if box is None or ext is None or samples is None or len(samples) < 20:
        return None
    dw, dh = ext[2] - ext[0], ext[3] - ext[1]
    iw, ih = box[2] - box[0], box[3] - box[1]
    if dw <= 0 or dh <= 0:
        return None
    kx, ky = iw / dw, ih / dh  # pixels per metre
    aspect = abs(kx / ky - 1)
    if aspect > MAX_CLIP:
        return None
    # Scale candidates: each axis' estimate snapped to a standard 1:N. Matplotlib clips the plan at
    # its axes (a door swing past the edge), which shortens one axis, so both axes are tried. The
    # raw estimate is a candidate only when the axes agree (no clipping, non-standard scale).
    cands = {}
    for e in (kx, ky):
        for n in STANDARD_SCALES:
            k_std = dpi / 25.4 * 1000 / n
            if abs(e / k_std - 1) <= SNAP_TOL:
                cands[n] = k_std
    if aspect <= ASPECT_TOL and not cands:
        cands[None] = kx if iw >= ih else ky  # the longer axis: strokes matter less there
    mask, near = gray < INK, _near_ink(gray)
    best = None
    for scale, k in cands.items():
        if k * dw < iw - STROKE_PX or k * dh < ih - STROKE_PX:
            continue  # the ink can't be bigger than the plan
        h, ox, oy = _place(mask, near, samples, k, box, ext, iw, ih)
        if best is None or h > best[0]:
            best = (h, scale, k, ox, oy)
    if best is None or best[0] < MIN_HIT_RATE:
        return None
    hit_rate, scale, k, ox, oy = best
    return Transform(sx=k / W, sy=k / H, tx=ox / W, ty=oy / H, image=str(image), size=(W, H),
                     scale=scale, hit_rate=round(hit_rate, 4), aspect_error=round(aspect, 4))


def _place(mask, near, samples, k, box, ext, iw, ih):
    """Best translation at scale k: centre the extents on the ink box, then search a few pixels
    (wider along an axis where the ink is shorter than the plan, i.e. clipped)."""
    dw, dh = ext[2] - ext[0], ext[3] - ext[1]
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    mx, my = (ext[0] + ext[2]) / 2, (ext[1] + ext[3]) / 2
    ox, oy = cx - k * mx, cy + k * my  # pixel = (ox + k x, oy - k y)
    rx = SEARCH_PX + max(0, int(k * dw - iw))
    ry = SEARCH_PX + max(0, int(k * dh - ih))
    bx, by = ox + k * samples[:, 0], oy - k * samples[:, 1]
    best = (-1.0, 0, 0)
    for dx in range(-rx, rx + 1):
        for dy in range(-ry, ry + 1):
            h = _hits(mask, bx + dx, by + dy)
            if h > best[0] + 1e-9 or (abs(h - best[0]) <= 1e-9 and dx * dx + dy * dy < best[1] ** 2 + best[2] ** 2):
                best = (h, dx, dy)
    ox, oy = ox + best[1], oy + best[2]
    return _hits(near, ox + k * samples[:, 0], oy - k * samples[:, 1]), ox, oy


def sheet_raster(path: Path) -> Optional[Path]:
    """The raster to fit on for a drawing path: the PNG itself, or the same-stem PNG twin."""
    if path.suffix.lower() == ".png" and path.is_file():
        return path
    twin = path.with_suffix(".png")
    return twin if twin.is_file() else None


@lru_cache(maxsize=256)
def _cached(dxf: str, image: str) -> Optional[Transform]:
    try:
        return register(Path(dxf), Path(image))
    except Exception:
        return None


def dxf_to_image(drawing_path) -> Optional[Transform]:
    """Transform from the DXF twin of `drawing_path` (.png/.pdf/.dxf) to its sheet image, or None.

    None when there is no DXF twin, no PNG twin to measure on, or the fit fails its checks.
    """
    p = Path(drawing_path)
    dxf = p.with_suffix(".dxf")
    image = sheet_raster(p)
    if not dxf.is_file() or image is None:
        return None
    return _cached(str(dxf.resolve()), str(image.resolve()))
