"""Rule-based English parser: question -> Query, no model needed.

Written against the dataset's English question templates, but keyword-driven rather than verbatim,
so close paraphrases ("how many windows are there?") also parse. Non-English questions are
handled by the translation table (see build_templates.py) or by the LLM fallback.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .normalize import Arg, normalize
from .schema import Query

# (pattern on the head noun phrase, target, room_type). Order matters: most specific first.
_TARGETS: List[Tuple[str, str, Optional[str]]] = [
    (r"sanitary (fixtures?|objects?)", "sanitary_fixture", None),
    (r"light(ing)? fixtures?|luminaires?|lights?\b", "light_fixture", None),
    (r"showers? (and|or|\+) (bath)?tubs?|(bath)?tubs? (and|or|\+) showers?", "shower_or_bathtub", None),
    (r"sinks? (and|or|\+) (wash ?|hand ?)?basins?|(wash ?|hand ?)?basins? (and|or|\+) sinks?|\bsinks?\b", "sink_or_washbasin", None),
    (r"(wash ?|hand ?)basins?|lavabos?", "washbasin", None),
    (r"\b(wc|toilet) rooms?|separate (wc|toilets?)", "room", "wc"),
    (r"toilet bowls?|wc seats?|toilets?|\bwcs?\b", "toilet", None),
    (r"bath ?tubs?|\btubs?\b", "bathtub", None),
    (r"showers?", "shower", None),
    (r"bathrooms?|washrooms?|shower rooms?", "room", "bathroom"),
    (r"bedrooms?", "room", "bedroom"),
    (r"kitchens?|kitchenettes?", "room", "kitchen"),
    (r"saunas?", "room", "sauna"),
    (r"balcon(y|ies)", "room", "balcony"),
    (r"^(floors|storeys|stories|levels)\b", "storey", None),
    (r"apartments?|residential units?|\bflats?\b|dwellings?", "apartment", None),
    (r"\bdoors?\b|\bdoorways?\b", "door", None),
    (r"windows?", "window", None),
    (r"walls?", "wall", None),
    (r"slabs?|floor plates?", "slab", None),
    (r"columns?|pillars?", "column", None),
    (r"beams?", "beam", None),
    (r"stairs?|staircases?|stairways?", "stair", None),
    (r"rooms?|spaces?", "room", None),
]

# Qualifiers we can't express in a Query: better to refuse than to answer a different question.
_UNSUPPORTED = re.compile(
    r"\b(exterior|external|interior|internal|fire|material|type[sd]?|thickness|gross|footprint|"
    r"largest|smallest|tallest|average|per|each|which|list|with their)\b"
)

_COUNT = re.compile(r"\b(how many|number of|count)\b")
_HEAD_COUNT = re.compile(
    r"\b(?:how many|number of|count(?: the| all)?)\s+(.+?)"
    r"(?=\s(?:are|is|does|do|were|have|has|can|shown|drawn|there|in|on|of|exist)\b|\?|$)"
)
_HEAD_MEASURE = re.compile(
    r"\b(area|length|volume)(?:\s+in\s+(?:m²|m2|m³|m3|metres|meters|ft²|square feet))?\s+of\s+"
    r"(?:all\s+)?(?:the\s+)?(.+?)(?=\s(?:on|in)\b|,|\?|$)"
)


def _strip_parens(t: str) -> str:
    """Remove explanatory parentheticals, but keep ones holding placeholders, e.g. '(<S>)'."""
    return re.sub(r"\s*\((?![^)]*<[SNL]>)[^)]*\)", "", t)


def _arg_after(t: str, pattern: str, args: List[Arg]) -> Optional[str]:
    """Value of the first placeholder matched by `pattern` (which must contain one <X> group)."""
    m = re.search(pattern, t)
    if not m:
        return None
    idx = len(re.findall(r"<[SNL]>", t[: m.start(1)]))
    return args[idx][1] if idx < len(args) else None


def parse_template(template: str, args: List[Arg]) -> Optional[Query]:
    """Parse an English normalized template + its args into a Query, or None."""
    t = re.sub(r"<([snl])>", lambda m: f"<{m.group(1).upper()}>", template.lower())
    t = _strip_parens(t)
    t = re.sub(r"\s+", " ", t).strip()

    # --- op + head noun phrase ---
    if _COUNT.search(t):
        op = "count"
        m = _HEAD_COUNT.search(t)
        head = m.group(1) if m else t
    else:
        m = _HEAD_MEASURE.search(t)
        if not m:
            return None  # no "<measure> of <thing>" structure: leave it to the LLM
        op = {"area": "area", "length": "length", "volume": "volume"}[m.group(1)]
        head = m.group(2)

    if _UNSUPPORTED.search(t.split("?")[0]):
        return None

    target = room_type = None
    for pat, tgt, rt in _TARGETS:
        if re.search(pat, head):
            target, room_type = tgt, rt
            break
    if target is None:
        return None

    q = dict(op=op, target=target, room_type=room_type)

    # --- arguments ---
    q["label"] = _arg_after(t, r"(?:labelled|labeled|named|called|marked)\s+(<S>)", args)
    q["room_id"] = _arg_after(t, r"\broom\s+(<N>)", args)
    if q["room_id"] and q["label"] is None:
        q["label"] = _arg_after(t, r"\broom\s+<N>\s*\((<S>)\)", args)
    q["apartment"] = _arg_after(t, r"\bapartment\s+(<L>)", args)
    q["model"] = _arg_after(t, r"\bmodel\s+(<S>)", args)
    q["level"] = (
        _arg_after(t, r"floor plan of\s+(<S>)", args)
        or _arg_after(t, r"\b(?:level|storey|floor)\s+(<S>)", args)
        or _arg_after(t, r"\bon\s+(<S>)", args)
    )
    if target == "room" and q["label"] is None and q["room_id"] is None:
        q["name"] = _arg_after(t, r"\broom\s+(<S>)", args)  # IFC space name, e.g. 'Kitchen (A103)'

    q["scope"] = "model" if q["model"] else "level" if q["level"] else "plan"

    # --- qualifiers ---
    full = template.lower()
    q["exclude_outdoor"] = bool(re.search(r"(except|excluding|without|not counting|ohne|hors)[^?]*(balcon|loggia|terrace|outdoor)", full))
    q["numbered_only"] = "numbered" in full
    q["side_area"] = bool(re.search(r"side area", full))

    if op == "count":
        q["unit"] = "count"
    elif re.search(r"ft²|ft2|square feet|sq ?ft", full):
        q["unit"] = {"area": "ft2", "length": "ft", "volume": "ft3"}[op]
    else:
        q["unit"] = {"area": "m2", "length": "m", "volume": "m3"}[op]

    return Query(**{k: v for k, v in q.items() if v is not None})


def parse_english(question: str) -> Optional[Query]:
    return parse_template(*normalize(question))
