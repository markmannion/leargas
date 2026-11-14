"""Answer one question about one large sheet from its text and lines.

Tools, tried in this order (the first that fits answers):
  slab      "slab area by type": slab callouts (thickness, bar size, spacing) + the region of each
  skirting  "baseboard / skirting / linear metres": room perimeter minus door openings
  doors     "how many doors / windows": openings found in the wall lines
  tags      "how many pumps / PS tags / check valves": numbered equipment tags (FP-1, PS-12, ...)
  printed   a value printed on the sheet ("TOTAL SECOND FLOOR = 26,562 SF", "TOTAL = 144 DORMS")
  labels    "how many group rooms": count of matching room labels
  area      room area from the room outline and the drawing scale
  llm       Gemma reads the most relevant text lines and must cite them (text answers)

Every answer carries evidence boxes and an honest confidence. Measured answers (areas, lengths,
openings) are estimates and never reach `verified` on their own.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from . import rooms as R
from .scale import Scale, find_scale
from .words import Sheet, Text, blocks, norm, read_sheet, rows

PRINTED_CONF = 0.92  # a value printed on the sheet, read with high OCR confidence and a strong match
TAG_CONF = 0.8
LABEL_CONF = 0.8
MEASURE_CONF = 0.7
OPENING_CONF = 0.55
LLM_CONF = 0.6

STOP = set("""a an the of on in at to for and or is are was be do does did there this that these those
what which how many much number count please tell me give show shown drawn drawing plan sheet floor
level its it as by with per each every all any value amount sum their our""".split())
GENERIC = {"area", "areas", "size", "square", "sq", "ft", "feet", "foot", "metres", "meters", "metre", "meter",
           "m2", "m", "sf", "net", "gross", "space", "spaces", "measure"}


@dataclass
class Box:
    box: Tuple[float, float, float, float]  # normalized
    label: str
    value: Optional[float] = None
    polygon: Optional[List[Tuple[float, float]]] = None  # normalized, if a shape is better than a box


@dataclass
class SheetResult:
    value: object = None
    unit: Optional[str] = None
    qtype: str = "text"
    confidence: float = 0.0
    evidence: List[Box] = field(default_factory=list)
    explanation: str = ""
    reason: Optional[str] = None
    tool: str = ""

    @property
    def ok(self) -> bool:
        return self.value is not None


# ------------------------------------------------------------------------------------ text helpers

def _stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("es") and w[-3] in "sxh":
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokens(s: str) -> List[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", s.lower())]


def content(s: str) -> List[str]:
    return [w for w in tokens(s) if w not in STOP]


_NUM = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(sf|sq\.?\s*ft|ft2|ft²|m2|m²|sqm|sq\.?\s*m|%|[a-z]+)?", re.I)


def last_number(s: str) -> Optional[Tuple[float, Optional[str], str]]:
    found = list(_NUM.finditer(s))
    if not found:
        return None
    m = found[-1]
    v = float(m.group(1).replace(",", ""))
    u = (m.group(2) or "").lower().replace(" ", "").replace(".", "")
    unit = {"sf": "ft2", "sqft": "ft2", "ft2": "ft2", "ft²": "ft2", "m2": "m2", "m²": "m2", "sqm": "m2"}.get(u)
    return v, unit, m.group(0)


def _q_kind(q: str) -> dict:
    ql = q.lower()
    return dict(
        count=bool(re.search(r"\bhow many\b|\bnumber of\b|\bcount\b", ql)),
        area=bool(re.search(r"\barea|m2|m²|square|sq\.? ?(ft|m)|footage|\bsf\b", ql)),
        skirting=bool(re.search(r"baseboard|skirting|linear\s*(met|m\b)|running\s*met", ql)),
        perimeter="perimeter" in ql,
        door=bool(re.search(r"\bdoor", ql)),
        window=bool(re.search(r"\bwindow", ql)),
        slab="slab" in ql,
    )


def _evidence(sheet: Sheet, items: List[Text], label=None) -> List[Box]:
    return [Box(sheet.norm_box(t.box), label or t.text) for t in items]


# ------------------------------------------------------------------------------------ tools

TAG_RE = re.compile(r"\b([A-Z]{1,5})-(\d{1,3}[A-Z]?)\b")
TAG_WORDS = {
    "pipe support": ["PS"], "support": ["PS"], "check valve": ["CV"], "fuel pump": ["FP"], "pump": ["FP", "P"],
    "filter separator": ["FSI", "FSR"], "control valve": ["FSCV", "CV"], "valve": ["CV", "FSCV"],
    "pressure indicating transmitter": ["PIT"], "transmitter": ["PIT"], "differential pressure": ["DPT"],
    "fan": ["EF", "SF", "F"], "air handling unit": ["AHU"], "ahu": ["AHU"], "column": ["C"],
}


def tool_tags(sheet: Sheet, question: str) -> Optional[SheetResult]:
    found: dict = {}
    for t in sheet.texts:
        for m in TAG_RE.finditer(t.text.upper()):
            found.setdefault(m.group(1), {}).setdefault(m.group(2), []).append(t)
    if not found:
        return None
    ql = question.lower()
    prefixes: List[str] = []
    for m in re.finditer(r"\b([A-Z]{1,5})\b(?:-\d+)?", question):  # an explicit tag prefix, e.g. "PS tags"
        if m.group(1) in found:
            prefixes.append(m.group(1))
    if not prefixes:
        for words in sorted(TAG_WORDS, key=len, reverse=True):
            if re.search(rf"\b{words}", ql):
                prefixes = [p for p in TAG_WORDS[words] if p in found]
                if prefixes:
                    break
    if not prefixes:
        return None
    tags, items = [], []
    for p in prefixes:
        for num, ts in sorted(found[p].items(), key=lambda kv: (len(kv[0]), kv[0])):
            tags.append(f"{p}-{num}")
            items.extend(ts)
    lst = ", ".join(tags[:30]) + (" …" if len(tags) > 30 else "")
    return SheetResult(
        value=len(tags), unit="count", qtype="count", confidence=TAG_CONF, tool="tags",
        evidence=_evidence(sheet, items),
        explanation=(f"{len(tags)} different {'/'.join(prefixes)} tags are printed on the sheet ({lst}); "
                     f"they appear on {len(items)} labels. Each tag number is counted once. Tags the text "
                     f"reader missed are not counted."))


def _rows(sheet: Sheet) -> List[Text]:
    return rows([t for t in sheet.texts if t.w >= t.h * 0.6])


def tool_printed(sheet: Sheet, question: str, kind: dict) -> Optional[SheetResult]:
    """A value printed on the sheet: the row whose words best match the question."""
    q = set(content(question)) - GENERIC
    if not q:
        return None
    best = None
    for r in _rows(sheet):
        num = last_number(r.text)
        if not num:
            continue
        rt = set(content(r.text))
        hit = q & rt
        if not hit:
            continue
        if kind["area"] and num[1] not in ("ft2", "m2"):
            continue
        if kind["count"] and num[1] in ("ft2", "m2"):
            continue
        score = len(hit) / len(q) - 0.02 * len(rt - q)  # prefer rows with nothing extra
        if best is None or score > best[0]:
            best = (score, r, num)
    if best is None or best[0] < 0.5:
        return None
    score, r, (v, unit, raw) = best
    qtype = "area" if unit in ("ft2", "m2") else ("count" if kind["count"] else "other")
    if qtype == "count":
        unit = "count"
        v = int(v)
    elif qtype == "other":
        # a size or a code: keep it as printed, e.g. 16" or 4275
        m = re.search(r"(\d[\d,./]*\s*(?:\"|”|''|'|mm|m\b|cm)?)", r.text[r.text.find(raw.split()[0]):] if raw else r.text)
        v = (m.group(1).strip() if m else raw).replace("''", '"')
        unit = None
        qtype = "text"
    conf = PRINTED_CONF if (score >= 0.66 and r.conf >= 0.9) else 0.75
    r = _trim_left(r, q)
    return SheetResult(value=v, unit=unit, qtype=qtype, confidence=conf, tool="printed",
                       evidence=_evidence(sheet, [r]),
                       explanation=f'Printed on the sheet: "{r.text}".')


def _trim_left(r: Text, q: set) -> Text:
    """OCR can read two columns as one line. Start the row at the first word the question matched,
    and shrink the box by the same share of characters (an estimate, good enough for a highlight)."""
    words = list(re.finditer(r"[A-Za-z0-9]+", r.text))
    first = next((m.start() for m in words if _stem(m.group(0).lower()) in q), 0)
    if first <= 0:
        return r
    x0, y0, x1, y1 = r.box
    cut = x0 + (x1 - x0) * first / max(len(r.text), 1)
    return Text(r.text[first:], (cut, y0, x1, y1), r.conf)


def _labels(sheet: Sheet) -> List[Text]:
    return [b for b in blocks(sheet.texts) if b.conf >= 0.7 and re.search(r"[A-Za-z]{3}", b.text)]


# Words that make a label a room name, for "how many rooms?" with no room type. Outdoor spaces
# (balcony, terrace) are left out. Matched on the lowercased label, so German umlauts work.
_ROOM_NAME = re.compile(
    r"\b(\w*rooms?|bed ?rooms?|kitchen\w*|bath\w*|living|lounge|dining|hall\w*|corridors?|lobby|foyer|"
    r"entr(y|ance)|wc|toilets?|lavatory|office|study|nursery|utility|laundry|pantry|stor(e|age)|"
    r"closet|wardrobe|cloaks?|garage|cellar|basement|attic|loft|sauna|gym|workshop|reception|"
    r"zimmer|k[uü]che|bad|wohnen|schlafen|essen|flur|diele|korridor|abstellraum|reduit|keller|"
    r"chambre|cuisine|salon|séjour|sejour|couloir)\b"
)


def _is_room_question(question: str) -> bool:
    """A count of rooms in general: 'how many rooms are there?', not 'how many group rooms?'."""
    return bool(re.search(r"\b(how many|number of|count(?: the| all)?)\s+(?:the\s+|all\s+)?rooms?\b",
                          question.lower()))


def _match_labels(labels: List[Text], question: str) -> List[Text]:
    if _is_room_question(question):
        return [b for b in labels if len(b.text) <= 40 and _ROOM_NAME.search(b.text.lower())]
    q = set(content(question)) - GENERIC - {"room"} | ({"room"} if re.search(r"\b\w+ rooms?\b", question.lower()) else set())
    q = {w for w in q if not w.isdigit()}
    if not q:
        return []
    out = []
    for b in labels:
        bt = set(content(b.text))
        if not bt or len(b.text) > 40:
            continue
        core = q - {"room"} if "room" in q and "room" not in bt else q
        if core and (core <= bt or (bt <= q and len(bt) >= 1 and bt != {"room"})):
            out.append(b)
    return out


def tool_label_count(sheet: Sheet, question: str) -> Optional[SheetResult]:
    found = _match_labels(_labels(sheet), question)
    if not found:
        return None
    names = sorted({f.text for f in found})
    return SheetResult(value=len(found), unit="count", qtype="count", confidence=LABEL_CONF, tool="labels",
                       evidence=_evidence(sheet, found),
                       explanation=f"{len(found)} matching labels on the sheet ({'; '.join(names[:6])}). "
                                   f"Rooms without a label are not counted.")


def _plan(sheet: Sheet) -> Tuple[Optional[Scale], Optional[R.Plan]]:
    sc = find_scale(sheet)
    if sc is None:
        return None, None
    return sc, R.analyse(sheet.raster, sc.px_per_m)


def _rooms_for(sheet: Sheet, plan: R.Plan, question: str) -> Tuple[List[R.Room], bool]:
    labels = _labels(sheet)
    bx0, by0, bx1, by1 = plan.building
    f = plan.f
    inside = [b for b in labels if bx0 <= b.cx * f <= bx1 and by0 <= b.cy * f <= by1]
    chosen = _match_labels(inside, question)
    all_rooms = not chosen
    if all_rooms:
        chosen = inside
    others = [(b.text, b.cx, b.cy) for b in inside]
    out = []
    for b in chosen:
        rest = [o for o in others if not (o[1] == b.cx and o[2] == b.cy)]
        out.append(R.room_at(plan, b.text, b.cx, b.cy, rest))
    return out, all_rooms


def _room_box(sheet: Sheet, room: R.Room, value: float, unit: str) -> Box:
    poly = [(min(max(x / sheet.width, 0), 1), min(max(y / sheet.height, 0), 1)) for x, y in room.polygon]
    xs = [p[0] for p in poly] or [0]
    ys = [p[1] for p in poly] or [0]
    return Box((min(xs), min(ys), max(xs), max(ys)), f"{room.label} {value:.1f} {unit}", value, poly or None)


def tool_rooms(sheet: Sheet, question: str, measure: str) -> Optional[SheetResult]:
    """measure: "area" | "skirting" | "perimeter"."""
    sc, plan = _plan(sheet)
    if plan is None:
        return SheetResult(reason="No drawing scale found on the sheet (no scale bar, scale ratio or dimension chain).")
    found, all_rooms = _rooms_for(sheet, plan, question)
    good = [r for r in found if not r.problem and r.area_m2 > 0.5]
    bad = [r for r in found if r.problem]
    if not good:
        why = bad[0].problem if bad else "no room label matched"
        return SheetResult(reason=f"Could not find a closed room outline: {why}.")
    unit = "m2" if measure == "area" else "m"
    vals = [(r, r.area_m2 if measure == "area" else (r.skirting_m if measure == "skirting" else r.perimeter_m)) for r in good]
    total = round(sum(v for _, v in vals), 1)
    sym = "m²" if unit == "m2" else "m"
    parts = "; ".join(f"{r.label} {v:.1f} {sym}" for r, v in vals[:8]) + (" …" if len(vals) > 8 else "")
    what = {"area": "floor area to the wall faces",
            "skirting": "skirting length (room outline minus door openings)",
            "perimeter": "room outline length"}[measure]
    expl = f"Measured {what} from the room outlines and the drawing scale ({sc.how}). {parts}."
    if measure == "skirting":
        doors = sum(len(r.doors) for r, _ in vals)
        expl += f" {doors} door openings ({sum(r.door_width_m for r, _ in vals):.1f} m) are taken off."
    if bad:
        expl += f" {len(bad)} matching label(s) left out: {bad[0].label}: {bad[0].problem}."
    if all_rooms:
        expl += " No room name matched, so this is the total of all labelled rooms with a closed outline."
    conf = MEASURE_CONF * (1.0 if sc.confidence >= 0.9 else 0.85) * (0.85 if bad else 1.0)
    return SheetResult(value=total, unit=unit, qtype="area" if measure == "area" else "length",
                       confidence=round(conf, 2), tool=measure,
                       evidence=[_room_box(sheet, r, v, sym) for r, v in vals], explanation=expl)


def tool_openings(sheet: Sheet, question: str, kind: dict) -> Optional[SheetResult]:
    sc, plan = _plan(sheet)
    if plan is None:
        return None
    want = "door" if kind["door"] else "window"
    labels_hit = _match_labels(_labels(sheet), question)
    if labels_hit:
        found, _ = _rooms_for(sheet, plan, question)
        good = [r for r in found if not r.problem]
        if not good:
            return None
        gaps = {id(g): g for r in good for g in (r.doors if want == "door" else r.windows)}.values()
        scope = ", ".join(sorted({r.label for r in good}))
    else:
        gaps = [g for g in plan.gaps if g.kind == want]
        scope = "the whole plan"
    gaps = list(gaps)
    if not gaps:
        return None
    ev = [Box(sheet.norm_box(R.gap_box_raster(plan, g)), f"{want} {g.width_m:.1f} m") for g in gaps]
    how = ("an empty gap in a wall line" if want == "door" else "a gap in a wall line with glazing lines")
    return SheetResult(value=len(gaps), unit="count", qtype="count", confidence=OPENING_CONF, tool="openings",
                       evidence=ev,
                       explanation=(f"{len(gaps)} {want} openings found in {scope}. Each one is {how}. "
                                    + ("Double doors count once; open passages can count as doors. " if want == "door"
                                       else "A long glazed band between two wall piers counts once. ")
                                    + "Treat this as an estimate."))


SLAB_RE = re.compile(r"(\d{2,4})\s*(?:mm\s*)?(?:thk\.?\s*)?slab", re.I)
BAR_RE = re.compile(r"\b((?:D|T|H|N|Y)\d{1,2}|#\d{1,2})\s*@\s*(\d{2,4})", re.I)


def tool_slab(sheet: Sheet, question: str) -> Optional[SheetResult]:
    calls = []
    for b in blocks(sheet.texts):
        s = b.text.upper()
        m = SLAB_RE.search(s)
        if not m:
            continue
        bar = BAR_RE.search(s)
        calls.append((b, int(m.group(1)), bar.group(1).upper() if bar else None, int(bar.group(2)) if bar else None))
    if not calls:
        return None
    sc = find_scale(sheet)
    # joint lines ("CJ") split one slab into panels: clear the ink next to each CJ label so the
    # panels of one slab join; clear each callout and its frame so the seed point is free
    cj = [t for t in sheet.texts if t.text.strip().upper() in ("CJ", "C.J.", "EJ", "IJ")]
    erase = []
    for t in cj:
        r = 1.5 * max(t.w, t.h)
        erase.append((t.box[0] - r, t.box[1] - r, t.box[2] + r, t.box[3] + r))
    for b, *_ in calls:
        lh = b.h / max(1, b.text.count(" ") // 3 + 1)
        m = max(0.6 * lh, 20)
        erase.append((b.box[0] - m, b.box[1] - m, b.box[2] + m, b.box[3] + m))
    types: dict = {}
    ev: List[Box] = []
    for b, thick, bar, spacing in calls:
        key = f"{thick} mm slab" + (f", {bar} @ {spacing}" if bar else "")
        area = None
        if sc is not None:
            got = R.outline_region(sheet.raster, sc.px_per_m, (b.cx, b.cy), erase)
            if got and got[0] > 1:
                area, poly = got
                room = R.Room(key, area, 0, polygon=poly)
                ev.append(_room_box(sheet, room, area, "m²"))
        ev.append(Box(sheet.norm_box(b.box), b.text))
        types.setdefault(key, []).append(area)
    parts = []
    total_known = 0.0
    for key, areas in types.items():
        known = [a for a in areas if a]
        if known:
            parts.append(f"{key}: {sum(known):.1f} m²")
            total_known += sum(known)
        else:
            parts.append(f"{key}: area not measured")
    answer = "; ".join(parts)
    expl = (f"{len(types)} slab type(s) from the slab callouts on the sheet. Each area is the closed region "
            f"around its callout, using the drawing scale" + (f" ({sc.how})" if sc else "") +
            ". A region can stop at a joint line, so an area can be only one panel of that slab. Check the highlighted regions.")
    return SheetResult(value=answer, unit=None, qtype="text", confidence=0.5, tool="slab", evidence=ev,
                       explanation=expl)


def tool_scale(sheet: Sheet) -> Optional[SheetResult]:
    sc = find_scale(sheet)
    if sc is None:
        return None
    printed = [t for t in sheet.texts if re.search(r"(?<![\d/])1\s*:\s*\d{2,4}\b|\d\s*\"\s*=\s*\d+\s*'", t.text)]
    txt = printed[0].text.strip() if printed else f"{sc.px_per_m:.1f} px per metre"
    return SheetResult(value=txt, qtype="text", confidence=0.9 if printed and sc.confidence >= 0.9 else 0.7,
                       tool="scale", evidence=_evidence(sheet, printed[:3]),
                       explanation=f"Scale used for measuring: {sc.how} ({sc.px_per_m:.1f} image pixels per metre).")


_FT_IN = re.compile(r"(\d{1,4})\s*['’]\s*-?\s*(\d{1,2})?\s*(?:\"|”|'')?")


def tool_overall(sheet: Sheet, question: str) -> Optional[SheetResult]:
    """'Overall length / width': the largest dimension string printed on the sheet."""
    best = None
    for t in sheet.texts:
        s = t.text.strip()
        m = _FT_IN.fullmatch(s)
        if m:
            metres = int(m.group(1)) * 0.3048 + (int(m.group(2)) * 0.0254 if m.group(2) else 0)
            cand = (metres, t, int(m.group(1)) + (int(m.group(2)) / 12 if m.group(2) else 0), "ft")
        elif re.fullmatch(r"\d{3,6}", s) and t.conf > 0.85:
            cand = (int(s) / 1000, t, int(s) / 1000, "m")  # metric dimensions are in mm
        else:
            continue
        if best is None or cand[0] > best[0]:
            best = cand
    if best is None:
        return None
    _, t, v, unit = best
    return SheetResult(value=round(v, 2), unit=unit, qtype="length", confidence=0.6, tool="overall",
                       evidence=_evidence(sheet, [t]),
                       explanation=f'The largest dimension printed on the sheet is "{t.text}". '
                                   f"This is the overall size only if that dimension spans the whole building.")


# ------------------------------------------------------------------------------------ LLM fallback

LLM_SYSTEM = """You answer a question about a construction drawing using only the numbered text lines read from it.
Each line has an id and its position on the sheet (x%, y% from the top left).
Reply with ONE JSON object and nothing else:
{"answer": <short answer, a number if one is asked>, "unit": <"count", "m", "m2", "ft", "ft2" or null>, "ids": [<ids of the lines that support the answer>], "confidence": <0 to 1>}
If the lines do not contain the answer, reply {"answer": null, "ids": [], "confidence": 0}."""


def _import_client():
    import sys

    repo = str(Path(__file__).resolve().parents[3])
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from model import client

    return client


def tool_llm(sheet: Sheet, question: str) -> SheetResult:
    if not (os.environ.get("MODEL_BASE_URL") or os.environ.get("LEARGAS_LLM_BASE_URL")):
        return SheetResult(reason="No sheet tool fits this question, and the language model is not configured.")
    rs = _rows(sheet)
    q = set(content(question)) - GENERIC
    scored = sorted(rs, key=lambda r: (-len(q & set(content(r.text))), r.cy))
    pick = [r for r in scored[:45]]
    pick.sort(key=lambda r: (r.cy, r.cx))
    lines = []
    for i, r in enumerate(pick):
        lines.append(f"[{i}] {r.text[:90]} ({100 * r.cx / sheet.width:.0f}%, {100 * r.cy / sheet.height:.0f}%)")
    body = "\n".join(lines)
    msgs = [{"role": "system", "content": LLM_SYSTEM},
            {"role": "user", "content": f"Text lines:\n{body}\n\nQuestion: {question}"}]
    try:
        client = _import_client()
        r = client.chat(msgs, model=os.environ.get("LEARGAS_LLM_MODEL", "gemma-base"), timeout=25,
                        temperature=0, max_tokens=200)
        text = r["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.S)
        obj = json.loads(m.group(0)) if m else {}
    except Exception as e:
        return SheetResult(reason=f"The language model could not read the sheet text: {type(e).__name__}.")
    ans = obj.get("answer")
    ids = [i for i in obj.get("ids") or [] if isinstance(i, int) and 0 <= i < len(pick)]
    if ans in (None, "", []) or not ids:
        return SheetResult(reason="The sheet text does not contain an answer the model can cite.")
    unit = obj.get("unit") if obj.get("unit") in ("count", "m", "m2", "ft", "ft2") else None
    qtype = "text"
    if isinstance(ans, (int, float)) and not isinstance(ans, bool):
        qtype = {"count": "count", "m2": "area", "ft2": "area", "m": "length", "ft": "length"}.get(unit or "", "other")
        if qtype == "count":
            ans = int(round(ans))
    else:
        ans = str(ans)
    cited = [pick[i] for i in ids]
    return SheetResult(value=ans, unit=unit, qtype=qtype, confidence=LLM_CONF, tool="llm",
                       evidence=_evidence(sheet, cited),
                       explanation="Gemma read this from the sheet text and cited the highlighted lines: "
                                   + " | ".join(f'"{c.text}"' for c in cited[:4]))


# ------------------------------------------------------------------------------------ entry point

def answer(path: Path, question: str) -> SheetResult:
    try:
        sheet = read_sheet(path)
    except Exception as e:
        return SheetResult(reason=f"Could not read the sheet: {type(e).__name__}: {e}")
    if not sheet.texts:
        return SheetResult(reason="No text found on the sheet.")
    kind = _q_kind(question)
    steps = []
    if kind["slab"]:
        steps.append(lambda: tool_slab(sheet, question))
    if kind["skirting"]:
        steps.append(lambda: tool_rooms(sheet, question, "skirting"))
    if kind["perimeter"]:
        steps.append(lambda: tool_rooms(sheet, question, "perimeter"))
    if kind["count"]:
        steps.append(lambda: tool_tags(sheet, question))
        steps.append(lambda: tool_printed(sheet, question, kind))
        if kind["door"] or kind["window"]:
            steps.append(lambda: tool_openings(sheet, question, kind))
        else:
            steps.append(lambda: tool_label_count(sheet, question))
    if kind["area"]:
        steps.append(lambda: tool_printed(sheet, question, kind))
        steps.append(lambda: tool_rooms(sheet, question, "area"))
    ql = question.lower()
    if re.search(r"\bscale\b", ql) and not kind["area"]:
        steps.insert(0, lambda: tool_scale(sheet))
    if re.search(r"\boverall\b|\btotal (length|width)\b|\b(length|width) of the (building|foundation|slab)", ql):
        steps.append(lambda: tool_overall(sheet, question))
    if not any(kind.values()):
        steps.append(lambda: tool_printed(sheet, question, kind))
    reasons = []
    for step in steps:
        try:
            r = step()
        except Exception as e:  # one broken tool must not stop the others
            reasons.append(f"{type(e).__name__}: {e}")
            continue
        if r is None:
            continue
        if r.ok:
            return r
        if r.reason:
            reasons.append(r.reason)
    r = tool_llm(sheet, question)
    if not r.ok and reasons:
        r.reason = " ".join(reasons + [r.reason or ""]).strip()
    return r
