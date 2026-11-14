"""Text on a sheet, with positions: the shared base of the sheet reader.

A vector PDF gives its text layer for free (PyMuPDF). A PNG/JPG, or a PDF with no text layer, is
read with OCR (RapidOCR, ONNX on the CPU) in overlapping tiles at full resolution, because a big
sheet shrunk to fit a vision model loses all of its text.

Every text item keeps its box in pixels of `Sheet.raster`, the full-resolution image the rest of
the sheet reader measures on. Results are cached as JSON per file (path + size + mtime).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

TILE = 2400
OVERLAP = 480
PDF_DPI = 300
CACHE_VERSION = 3
_locks: dict = {}
_locks_guard = threading.Lock()


@dataclass
class Text:
    text: str
    box: Tuple[float, float, float, float]  # x0, y0, x1, y1 in raster pixels
    conf: float = 1.0

    @property
    def cx(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def h(self) -> float:
        return self.box[3] - self.box[1]

    @property
    def w(self) -> float:
        return self.box[2] - self.box[0]


@dataclass
class Sheet:
    path: str  # the file the text came from
    raster: str  # the full-resolution image that boxes refer to
    width: int
    height: int
    source: str  # "pdf" (text layer) | "ocr"
    texts: List[Text] = field(default_factory=list)

    def norm_box(self, box) -> Tuple[float, float, float, float]:
        x0, y0, x1, y1 = box
        c = lambda v, d: min(max(v / d, 0.0), 1.0)  # noqa: E731
        return (c(x0, self.width), c(y0, self.height), c(x1, self.width), c(y1, self.height))


def cache_dir() -> Path:
    d = Path(os.environ.get("LEARGAS_SHEET_CACHE", Path(__file__).resolve().parents[2] / "data" / "sheet_cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(p: Path) -> str:
    st = p.stat()
    return hashlib.sha1(f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}|{CACHE_VERSION}".encode()).hexdigest()[:20]


def _open_image(p: Path):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    return Image.open(p)


# ------------------------------------------------------------------------------------ PDF

def _pdf_raster(pdf: Path) -> Path:
    """Page 1 rendered at PDF_DPI into the cache: the image geometry is measured on."""
    out = cache_dir() / f"{_key(pdf)}_p0.png"
    if not out.exists():
        import fitz

        with fitz.open(pdf) as doc:
            doc[0].get_pixmap(dpi=PDF_DPI).save(out)
    return out


def _pdf_texts(pdf: Path, width: int, height: int) -> List[Text]:
    """Text layer of page 1, one item per PDF text line, in raster pixels."""
    import fitz

    out: List[Text] = []
    with fitz.open(pdf) as doc:
        page = doc[0]
        sx, sy = width / page.rect.width, height / page.rect.height
        lines: dict = {}
        for x0, y0, x1, y1, word, b, ln, _ in page.get_text("words"):
            lines.setdefault((b, ln), []).append((x0, y0, x1, y1, word))
        for ws in lines.values():
            ws.sort(key=lambda w: w[0])
            box = (min(w[0] for w in ws) * sx, min(w[1] for w in ws) * sy,
                   max(w[2] for w in ws) * sx, max(w[3] for w in ws) * sy)
            out.append(Text(" ".join(w[4] for w in ws), box, 1.0))
    return out


# ------------------------------------------------------------------------------------ OCR

_ocr_engine = None


def _ocr():
    global _ocr_engine
    if _ocr_engine is None:
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        from rapidocr import RapidOCR

        _ocr_engine = RapidOCR(params={"Global.log_level": "warning"}) if _accepts_params() else RapidOCR()
    return _ocr_engine


def _accepts_params() -> bool:
    try:
        import inspect

        from rapidocr import RapidOCR

        return "params" in inspect.signature(RapidOCR.__init__).parameters
    except Exception:
        return False


def _tiles(w: int, h: int):
    step = TILE - OVERLAP
    xs = list(range(0, max(w - OVERLAP, 1), step)) or [0]
    ys = list(range(0, max(h - OVERLAP, 1), step)) or [0]
    for y in ys:
        for x in xs:
            yield x, y, min(x + TILE, w), min(y + TILE, h)


def _iou_like(a, b) -> float:
    """Intersection over the smaller box, so a fragment cut at a tile edge matches its full copy."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1.0
    return inter / small


def _ocr_texts(img_path: Path) -> Tuple[List[Text], int, int]:
    import numpy as np

    im = _open_image(img_path).convert("L")
    w, h = im.size
    arr = np.asarray(im)
    eng = _ocr()
    found: List[Text] = []
    for x0, y0, x1, y1 in _tiles(w, h):
        tile = arr[y0:y1, x0:x1]
        if tile.size == 0 or (tile < 200).mean() < 0.0005:  # blank paper: nothing to read
            continue
        r = eng(np.ascontiguousarray(np.stack([tile] * 3, axis=-1)))
        if r is None or r.boxes is None:
            continue
        for quad, txt, conf in zip(r.boxes, r.txts, r.scores):
            txt = (txt or "").strip()
            if not txt:
                continue
            xs = [p[0] for p in quad]
            ys = [p[1] for p in quad]
            box = (float(x0 + min(xs)), float(y0 + min(ys)), float(x0 + max(xs)), float(y0 + max(ys)))
            # drop items cut by an inner tile edge: the neighbouring tile sees them whole
            edge = 6
            cut = ((min(xs) < edge and x0 > 0) or (max(xs) > (x1 - x0) - edge and x1 < w)
                   or (min(ys) < edge and y0 > 0) or (max(ys) > (y1 - y0) - edge and y1 < h))
            found.append((cut, Text(txt, box, float(conf))))
    # merge duplicates from overlapping tiles: whole items first (most confident, then longest).
    # An item cut by a tile edge is kept only where no whole item already covers most of it, so a
    # long line cut in two still keeps both halves (rows() joins them again).
    found.sort(key=lambda ct: (not ct[0], ct[1].conf, len(ct[1].text)), reverse=True)
    kept: List[Text] = []
    for cut, t in found:
        if cut:
            area = max(t.w * t.h, 1.0)
            covered = sum(max(0.0, min(t.box[2], k.box[2]) - max(t.box[0], k.box[0]))
                          * max(0.0, min(t.box[3], k.box[3]) - max(t.box[1], k.box[1])) for k in kept)
            if covered / area < 0.5:
                kept.append(t)
        elif all(_iou_like(t.box, k.box) < 0.6 for k in kept):
            kept.append(t)
    return kept, w, h


# ------------------------------------------------------------------------------------ entry

def _has_text_layer(pdf: Path) -> bool:
    import fitz

    with fitz.open(pdf) as doc:
        return len(doc) > 0 and len(doc[0].get_text("words")) >= 5


def read_sheet(path: Path) -> Sheet:
    """Text and positions for one drawing file (cached). Raises on unreadable files."""
    path = Path(path)
    key = _key(path)
    cached = cache_dir() / f"{key}.json"
    if cached.exists():
        d = json.loads(cached.read_text(encoding="utf-8"))
        d["texts"] = [Text(t["text"], tuple(t["box"]), t["conf"]) for t in d["texts"]]
        return Sheet(**d)
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:  # one OCR run per file, even with parallel requests
        if cached.exists():
            return read_sheet(path)
        if path.suffix.lower() == ".pdf":
            raster = _pdf_raster(path)
            w, h = _open_image(raster).size
            if _has_text_layer(path):
                texts, source = _pdf_texts(path, w, h), "pdf"
            else:
                texts, w, h = _ocr_texts(raster)
                source = "ocr"
        else:
            raster = path
            texts, w, h = _ocr_texts(path)
            source = "ocr"
        sheet = Sheet(str(path), str(raster), w, h, source, texts)
        d = asdict(sheet)
        cached.write_text(json.dumps(d), encoding="utf-8")
        return sheet


def warm(path: Path) -> None:
    """Read a sheet in the background (after an upload) so the first question is fast."""
    def run():
        try:
            read_sheet(path)
        except Exception as e:  # best effort
            log.warning("sheet warm-up failed for %s: %s", path, e)

    threading.Thread(target=run, daemon=True).start()


# ------------------------------------------------------------------------------------ layout helpers

def rows(texts: List[Text], gap_factor: float = 8.0) -> List[Text]:
    """Join items on the same line (e.g. 'TOTAL SECOND FLOOR =' + '26,562 SF') into one row."""
    items = sorted(texts, key=lambda t: (t.cy, t.box[0]))
    used = [False] * len(items)
    out: List[Text] = []
    for i, t in enumerate(items):
        if used[i]:
            continue
        used[i] = True
        group = [t]
        changed = True
        while changed:
            changed = False
            right = max(g.box[2] for g in group)
            hh = max(g.h for g in group)
            for j in range(len(items)):
                u = items[j]
                if used[j] or u.w < u.h * 0.6:  # skip vertical text
                    continue
                # a wide gap only joins a label to its value: "LABEL =" then "26,562 SF"
                left_text = max(group, key=lambda g: g.box[2]).text.rstrip()
                pairs = left_text.endswith(("=", ":")) or u.text.lstrip()[:1].isdigit()
                limit = gap_factor * hh if pairs else 2.5 * hh
                if abs(u.cy - t.cy) < 0.45 * max(hh, u.h) and 0.5 < u.h / max(hh, 1) < 2 and \
                        -hh < u.box[0] - right < limit:
                    group.append(u)
                    used[j] = True
                    changed = True
                    right = max(right, u.box[2])
        group.sort(key=lambda g: g.box[0])
        box = (min(g.box[0] for g in group), min(g.box[1] for g in group),
               max(g.box[2] for g in group), max(g.box[3] for g in group))
        out.append(Text(" ".join(g.text for g in group), box, min(g.conf for g in group)))
    return out


def blocks(texts: List[Text]) -> List[Text]:
    """Stack centred lines into one label ('Secondary' / 'Classroom' -> 'Secondary Classroom')."""
    items = sorted(texts, key=lambda t: (t.box[1], t.box[0]))
    used = [False] * len(items)
    out: List[Text] = []
    for i, t in enumerate(items):
        if used[i]:
            continue
        used[i] = True
        group = [t]
        last = t
        for j in range(i + 1, len(items)):
            u = items[j]
            if used[j]:
                continue
            gap = u.box[1] - last.box[3]
            if gap > 0.9 * last.h:
                if u.box[1] - last.box[3] > 3 * last.h:
                    break
                continue
            if gap < -0.3 * last.h or abs(u.cx - last.cx) > 0.6 * max(u.w, last.w) or not (0.7 < u.h / max(last.h, 1) < 1.4):
                continue
            group.append(u)
            used[j] = True
            last = u
        box = (min(g.box[0] for g in group), min(g.box[1] for g in group),
               max(g.box[2] for g in group), max(g.box[3] for g in group))
        out.append(Text(" ".join(g.text for g in group), box, min(g.conf for g in group)))
    return out


_ws = re.compile(r"\s+")


def norm(s: str) -> str:
    return _ws.sub(" ", re.sub(r"[^a-z0-9#./\-\"' ]", " ", s.lower())).strip()
