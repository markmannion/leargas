"""LLM fallback: ask Gemma (any OpenAI-compatible chat endpoint, e.g. vLLM) to emit a Query as JSON.

Only used when neither the template table nor the English rules match, e.g. free-form or
paraphrased demo questions in other languages.

Config (env):
    LEARGAS_LLM_BASE_URL   e.g. http://<verda-host>:8000/v1   (unset -> fallback disabled)
    LEARGAS_LLM_MODEL      default "gemma-base"
    LEARGAS_LLM_API_KEY    optional
    LEARGAS_LLM_TIMEOUT    seconds, default 5
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from pydantic import ValidationError

from .. import gemma_status

from .schema import Op, Query, RoomType, Scope, Target

SYSTEM = f"""You convert questions about a construction drawing into a JSON query for a geometry engine.
The question may be in any language. Reply with ONE JSON object and nothing else.

If the question asks for a single count, area, length or volume, reply {{"query": {{...}}}} with fields:
  op: one of {[e.value for e in Op]}
  target: one of {[e.value for e in Target]}
  scope: one of {[e.value for e in Scope]}  ("plan" = this drawing; "level" needs `level`; "model" needs `model`)
  room_type: one of {[e.value for e in RoomType]} (only when target is "room" and a room category is named)
  label: exact printed room label if the question quotes one (keep the original spelling)
  room_id: room number if given, e.g. "7.01"
  name: exact IFC space name if given, e.g. "Kitchen (A103)"
  apartment: apartment letter if given, e.g. "B"
  level: storey name if given, model: model name if given
  exclude_outdoor: true if balconies/terraces/outdoor spaces are excluded
  numbered_only: true if only numbered indoor rooms count
  side_area: true for wall side area
  unit: "count" for counts, else "m", "m2", "m3" (or "ft", "ft2", "ft3" if asked in feet)
Omit fields that don't apply.

Otherwise (a list, a comparison, a material, a yes/no question, or anything else), reply {{"query": null}}."""

EXAMPLES: List[Dict[str, str]] = [
    {"role": "user", "content": "Wie viele Fenster sind auf diesem Grundriss eingezeichnet?"},
    {"role": "assistant", "content": '{"query": {"op": "count", "target": "window", "scope": "plan", "unit": "count"}}'},
    {"role": "user", "content": "Quelle est la surface nette totale de toutes les pièces nommées «Chambre» à cet étage ?"},
    {"role": "assistant", "content": '{"query": {"op": "area", "target": "room", "scope": "plan", "label": "Chambre", "unit": "m2"}}'},
    {"role": "user", "content": "Kuinka monta makuuhuonetta asunnossa on?"},
    {"role": "assistant", "content": '{"query": {"op": "count", "target": "room", "room_type": "bedroom", "scope": "plan", "unit": "count"}}'},
    {"role": "user", "content": "Hvad er den samlede længde af alle vægge på 'Stueplan' i meter?"},
    {"role": "assistant", "content": '{"query": {"op": "length", "target": "wall", "scope": "level", "level": "Stueplan", "unit": "m"}}'},
    {"role": "user", "content": "Which materials are used in the exterior walls?"},
    {"role": "assistant", "content": '{"query": null}'},
]


def enabled() -> bool:
    return bool(os.environ.get("LEARGAS_LLM_BASE_URL"))


def build_messages(question: str) -> List[Dict[str, str]]:
    return [{"role": "system", "content": SYSTEM}, *EXAMPLES, {"role": "user", "content": question}]


def parse_output(text: str) -> Optional[Query]:
    """Extract the JSON object from the model reply and validate it. Raises ValueError if malformed."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    obj: Any = json.loads(m.group(0))
    q = obj.get("query", obj) if isinstance(obj, dict) else None
    if q is None:
        return None
    try:
        return Query.model_validate(q)
    except ValidationError as e:
        raise ValueError(f"invalid query: {e.errors()[:2]}") from e


def parse_with_llm(question: str, client: Optional[httpx.Client] = None) -> Optional[Query]:
    base = os.environ["LEARGAS_LLM_BASE_URL"].rstrip("/")
    headers = {}
    if os.environ.get("LEARGAS_LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['LEARGAS_LLM_API_KEY']}"
    body = {
        "model": os.environ.get("LEARGAS_LLM_MODEL", "gemma-base"),
        "messages": build_messages(question),
        "temperature": 0,
        "max_tokens": 200,
    }
    if client is None:
        state = gemma_status.status(body["model"], url=base, key=os.environ.get("LEARGAS_LLM_API_KEY", ""))
        if not state["available"]:
            raise RuntimeError("Gemma query parsing is temporarily unavailable; local templates and rules still work.")
    c = client or httpx.Client(timeout=float(os.environ.get("LEARGAS_LLM_TIMEOUT", "5")))
    try:
        r = c.post(f"{base}/chat/completions", json=body, headers=headers)
        r.raise_for_status()
        return parse_output(r.json()["choices"][0]["message"]["content"])
    except httpx.HTTPError:
        if client is None:
            gemma_status.failed(body["model"], url=base, key=os.environ.get("LEARGAS_LLM_API_KEY", ""))
        raise RuntimeError("Gemma query parsing is temporarily unavailable; please try again shortly.") from None
    finally:
        if client is None:
            c.close()
