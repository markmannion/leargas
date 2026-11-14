"""Drawing scale: how many raster pixels make one real metre.

Three independent readings, all from the sheet's own text:
  bar     a metric scale bar's labels ("0", "10m", "20m" on one line): measured on the sheet itself
  chain   a chain of metric dimension strings ("600 3450 600 3600" in mm). Neighbouring labels sit
          (a + b) / 2 apart, so each pair gives pixels per mm; the median is robust to stray numbers
  ratio   a printed scale ("1:200", 1/4" = 1'-0", 1" = 40'-0") plus the paper size, from the title
          block ("A2", "ANSI D") or the sheet's aspect ratio

The measured readings (bar, chain) win; the ratio is a cross-check. Two readings that agree within
4% give high confidence, one reading gives medium confidence.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .words import Sheet, Text

# landscape paper widths in mm, with height for the aspect ratio check
PAPER = {
    "A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210),
    "ANSI E": (1118, 864), "ANSI D": (864, 559), "ANSI C": (559, 432), "ANSI B": (432, 279),
    "ARCH E": (1219, 914), "ARCH D": (914, 610), "ARCH C": (610, 457),
}
FT = 0.3048
IN = 0.0254


@dataclass
class Scale:
    px_per_m: float
    confidence: float
    how: str
    readings: List[Tuple[str, float]]


def _scale_bar(texts: List[Text]) -> Optional[Tuple[float, str]]:
    """Metric ("0 10m 20m") or imperial ("0' 20' 40'") bar labels on one line."""
    zeros = [t for t in texts if re.fullmatch(r"\s*0\s*'?\s*", t.text)]
    marks = []
    for t in texts:
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*m\s*", t.text, re.I)
        if m and float(m.group(1)) > 0:
            marks.append((float(m.group(1)), t))
            continue
        m = re.fullmatch(r"\s*(\d+)\s*['’]\s*", t.text)
        if m and int(m.group(1)) > 0:
            marks.append((int(m.group(1)) * FT, t))
    best = None
    for z in zeros:
        same = [(v, t) for v, t in marks if abs(t.cy - z.cy) < 1.5 * max(z.h, t.h) and t.cx > z.cx]
        if not same:
            continue
        v, t = max(same, key=lambda vt: vt[0])
        ppm = (t.cx - z.cx) / v
        # the label centre sits right of the tick by about half the "m"; good enough at bar lengths
        if ppm > 0 and (best is None or v > best[2]):
            best = (ppm, f"scale bar 0 to {v:g} m", v)
    return (best[0], best[1]) if best else None


_NUM = re.compile(r"^\d{2,6}$")


def _dimension_chain(texts: List[Text]) -> Optional[Tuple[float, str]]:
    nums = [t for t in texts if _NUM.match(t.text.strip()) and t.w >= t.h * 0.8]
    nums.sort(key=lambda t: (round(t.cy / max(t.h, 1)), t.cx))
    ks = []
    for i, a in enumerate(nums):
        row = [b for b in nums if b is not a and abs(b.cy - a.cy) < 0.4 * a.h and b.cx > a.cx]
        if not row:
            continue
        b = min(row, key=lambda t: t.cx)
        va, vb = int(a.text), int(b.text)
        if va < 50 or vb < 50:
            continue
        gap = b.cx - a.cx
        if gap < 2 * a.h:
            continue
        ks.append(gap / ((va + vb) / 2))  # px per mm
    if len(ks) < 4:
        return None
    med = statistics.median(ks)
    close = [k for k in ks if abs(k - med) / med < 0.08]
    if len(close) < max(4, len(ks) // 3):
        return None
    return statistics.median(close) * 1000, f"{len(close)} mm dimension pairs"


def _paper(sheet: Sheet) -> Tuple[Optional[str], float]:
    """Paper width in mm: from the title block if the aspect ratio agrees, else from the ratio."""
    ratio = sheet.width / sheet.height
    if ratio < 1:
        ratio = 1 / ratio
    named = []
    for t in sheet.texts:
        s = t.text.upper()
        for name in PAPER:
            if re.search(rf"(?<![A-Z0-9]){name.replace(' ', r'\s*')}(?![0-9])", s):
                named.append(name)
    for name in named:
        w, h = PAPER[name]
        if abs(w / h - ratio) < 0.03:
            return name, w
    name = min(PAPER, key=lambda n: abs(PAPER[n][0] / PAPER[n][1] - ratio))
    if abs(PAPER[name][0] / PAPER[name][1] - ratio) < 0.02:
        return name, PAPER[name][0]
    return None, 0.0


def _ratio(sheet: Sheet) -> Optional[Tuple[float, str]]:
    paper, paper_w = _paper(sheet)
    if not paper:
        return None
    long_px = max(sheet.width, sheet.height)
    px_per_paper_mm = long_px / paper_w
    for t in sheet.texts:
        s = t.text.upper().replace("”", '"').replace("’", "'").replace("''", '"')
        m = re.search(r"(?<![\d/])1\s*:\s*(\d{1,4})(?![\d/])", s)
        if m and int(m.group(1)) in (10, 20, 25, 50, 100, 200, 250, 500, 1000, 1250, 2500):
            n = int(m.group(1))
            return px_per_paper_mm * 1000 / n, f"printed scale 1:{n} on {paper}"
        m = re.search(r"(\d+)?\s*/?\s*(\d+)?\s*\"\s*=\s*(\d+)\s*'\s*-?\s*(\d+)?\s*\"?", s)
        if m and ("=" in s) and ("'" in s):
            num, den, ft, inch = m.groups()
            if num and den:
                paper_in = int(num) / int(den)
            elif num:
                paper_in = float(num)
            else:
                continue
            real_m = int(ft) * FT + (int(inch) * IN if inch else 0)
            if paper_in <= 0 or real_m <= 0:
                continue
            return px_per_paper_mm * paper_in * 25.4 / real_m, f"printed scale {m.group(0).strip()} on {paper}"
    return None


def find_scale(sheet: Sheet) -> Optional[Scale]:
    readings = []
    for name, fn in (("bar", _scale_bar), ("chain", _dimension_chain), ("ratio", _ratio)):
        try:
            r = fn(sheet.texts) if name != "ratio" else fn(sheet)
        except Exception:
            r = None
        if r:
            readings.append((name, r[0], r[1]))
    if not readings:
        return None
    measured = [r for r in readings if r[0] in ("bar", "chain")]
    main = measured[0] if measured else readings[0]
    others = [r for r in readings if r is not main]
    agree = [r for r in others if abs(r[1] - main[1]) / main[1] < 0.04]
    conf = 0.9 if agree else (0.6 if main[0] != "ratio" else 0.5)
    how = main[2] + (f", agrees with {agree[0][2]}" if agree else "")
    if others and not agree:
        how += f" (other reading: {others[0][2]} differs by {abs(others[0][1] - main[1]) / main[1]:.0%})"
    return Scale(main[1], conf, how, [(r[0], r[1]) for r in readings])
