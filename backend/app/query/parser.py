"""question -> ParseResult. Tries, in order:

1. template  exact match on the normalized template table (all dataset languages)   conf 0.99
2. rules     keyword rules on English questions (paraphrase-tolerant)                conf 0.85
3. llm       Gemma via OpenAI-compatible endpoint, if LEARGAS_LLM_BASE_URL is set   conf 0.70
4. none      -> the caller should answer cannot_verify / hand off to the raster model

Table path: LEARGAS_QUERY_TEMPLATES or backend/data/query_templates.json (see build_templates.py).
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict

from . import llm
from .build_templates import DEFAULT_OUT
from .normalize import normalize
from .rules import parse_template
from .schema import ParseResult

log = logging.getLogger(__name__)

CONF_TEMPLATE, CONF_RULES, CONF_LLM = 0.99, 0.85, 0.70


@lru_cache(maxsize=1)
def templates() -> Dict[str, dict]:
    p = Path(os.environ.get("LEARGAS_QUERY_TEMPLATES", DEFAULT_OUT))
    if not p.exists():
        log.warning("query template table not found at %s; English rules + LLM only", p)
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)["templates"]


def parse(question: str, use_llm: bool = True) -> ParseResult:
    t, args = normalize(question)
    values = [v for _, v in args]

    hit = templates().get(t)
    if hit is not None:
        en_args = args if hit["perm"] is None else [args[i] for i in hit["perm"]]
        q = parse_template(hit["en"], en_args)
        if q is not None:
            return ParseResult(query=q, parser="template", confidence=CONF_TEMPLATE, template=t, args=values)

    q = parse_template(t, args)
    if q is not None:
        return ParseResult(query=q, parser="rules", confidence=CONF_RULES, template=t, args=values)

    if use_llm and llm.enabled():
        try:
            q = llm.parse_with_llm(question)
        except Exception as e:  # network, bad JSON, invalid query: degrade to cannot_verify
            log.warning("LLM query parse failed: %s", e)
            return ParseResult(parser="none", confidence=0.0, template=t, args=values, reason=f"LLM parse failed: {e}")
        if q is not None:
            return ParseResult(query=q, parser="llm", confidence=CONF_LLM, template=t, args=values)
        return ParseResult(parser="llm", confidence=0.0, template=t, args=values,
                           reason="Not a single count/area/length/volume question")

    return ParseResult(parser="none", confidence=0.0, template=t, args=values,
                       reason="No template or rule matched" + ("" if llm.enabled() else "; LLM fallback not configured"))
