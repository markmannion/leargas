"""M3 / contract C3: the ONE prompt builder and output parser for every Gemma call.

Training (build_sft), serving evals (baseline_eval, run evals), the model sweep and Harry's
router all go through this file, so train and serve prompts can never drift apart.

Raster answering
    msgs = build_messages(image, question)                  # OpenAI/vLLM chat format
    text, logprobs = ...call the endpoint with logprobs=True...
    out = parse_output(text, logprobs)
    # -> {"answer": 12 | 47.37 | None, "unit": "count", "points": [[x, y], ...] | None,
    #     "confidence": 0.93, "reason": str | None, "ok": True}

    or simply:  from model.client import ask; out = ask(image, question, model="gemma-ft")

Text-only JSON tasks (Harry's question -> query parser)
    msgs = build_text_messages(system, question, few_shot=[(q, {"op": ...}), ...])
    obj = extract_json(text)

Conventions
- The model writes points as [y, x] on a 0-1000 grid. That's Gemma's native detection convention,
  the same as box_2d = [y1, x1, y2, x2]. parse_output converts them to the C2 convention:
  [x, y] normalised 0-1 against the image.
- Units are normalised to the dataset's spelling: count | m2 | m | m3 | ft2.
- Abstaining is part of the format: {"answer": null, "unit": null, "reason": "..."}.
- Thinking is never enabled (no <|think|> token): answers are short JSON, fast, and logprob-scored.
"""
from __future__ import annotations

import base64
import io
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

PROMPT_VERSION = "v1"

# Same value as vLLM --mm-processor-kwargs max_soft_tokens and the training processor.
MAX_SOFT_TOKENS = 560
# Images are pre-resized so the long side is at most this, on the laptop and the box, for
# training and serving alike. ~1600 px is about what the largest (1120-token) budget resolves, so
# nothing is lost even if MAX_SOFT_TOKENS is raised later, and uploads stay small.
MAX_SIDE = 1600

UNITS = ("count", "m2", "m", "m3", "ft2")

SYSTEM_PROMPT = (
    "You read construction drawings (floor plans, schedules, sections) and answer quantity "
    "take-off questions about the drawing shown. Questions may be in any language.\n"
    "Reply with ONE JSON object and nothing else:\n"
    '{"answer": <number>, "unit": "count" | "m2" | "m" | "m3" | "ft2"}\n'
    "- count questions: an integer and unit \"count\". Areas in m2 unless the question says otherwise.\n"
    "- If the drawing cannot answer the question (the information is not shown, or it is not "
    'this kind of drawing), reply {"answer": null, "unit": null, "reason": "<short reason>"}.'
)

POINTS_ADDENDUM = (
    "\nFor count questions also list where each counted item is, as "
    '"points": [[y, x], ...] on a 0-1000 grid of the image (one point per item, len(points) == answer).'
)


# --------------------------------------------------------------------------- images

def load_image(image: Any, max_side: int = MAX_SIDE):
    """Path | bytes | PIL.Image -> RGB PIL.Image with long side <= max_side (never upscaled)."""
    from PIL import Image  # lazy: text-only users don't need Pillow

    Image.MAX_IMAGE_PIXELS = None  # some archive scans are huge
    if isinstance(image, (str, Path)):
        img = Image.open(image)
    elif isinstance(image, (bytes, bytearray)):
        img = Image.open(io.BytesIO(image))
    else:
        img = image
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    img = img.convert("RGB")
    w, h = img.size
    s = max_side / max(w, h)
    if s < 1:
        img = img.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    return img


def image_to_data_url(image: Any, max_side: int = MAX_SIDE) -> str:
    img = load_image(image, max_side)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# --------------------------------------------------------------------------- messages

def system_prompt(with_points: bool = False) -> str:
    return SYSTEM_PROMPT + (POINTS_ADDENDUM if with_points else "")


def build_messages(image: Any, question: str, with_points: bool = False, max_side: int = MAX_SIDE) -> list[dict]:
    """OpenAI-compatible chat messages for vLLM. Image first, then text (Gemma's recommended order)."""
    return [
        {"role": "system", "content": system_prompt(with_points)},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_to_data_url(image, max_side)}},
                {"type": "text", "text": question.strip()},
            ],
        },
    ]


def build_train_messages(image: Any, question: str, target: str, with_points: bool = False,
                         max_side: int = MAX_SIDE) -> list[dict]:
    """The same prompt in the HF/Unsloth vision format ({"type": "image", "image": PIL}), plus the target."""
    return [
        {"role": "system", "content": [{"type": "text", "text": system_prompt(with_points)}]},
        {"role": "user", "content": [
            {"type": "image", "image": load_image(image, max_side)},
            {"type": "text", "text": question.strip()},
        ]},
        {"role": "assistant", "content": [{"type": "text", "text": target}]},
    ]


def build_text_messages(system: str, question: str, few_shot: Iterable[tuple[str, Any]] = ()) -> list[dict]:
    """Text-only JSON task (e.g. Harry's question -> structured query). few_shot: (question, answer_obj)."""
    msgs = [{"role": "system", "content": system}]
    for q, a in few_shot:
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)})
    msgs.append({"role": "user", "content": question.strip()})
    return msgs


def request_params(max_tokens: int = 256) -> dict:
    """Sampling params for every evaluated call: greedy, with logprobs for confidence."""
    return {"temperature": 0.0, "max_tokens": max_tokens, "logprobs": True, "top_logprobs": 1}


# --------------------------------------------------------------------------- targets (training)

def normalize_unit(unit: Any) -> str | None:
    if unit is None:
        return None
    u = str(unit).strip().lower().replace("²", "2").replace("³", "3").replace(" ", "").replace("^", "")
    u = {"sqm": "m2", "m²": "m2", "sq.m": "m2", "sqft": "ft2", "sf": "ft2", "ft²": "ft2", "cbm": "m3",
         "pcs": "count", "items": "count", "number": "count", "#": "count", "n": "count", "": None}.get(u, u)
    return u


def format_number(x: Any) -> Any:
    """Dataset answers -> JSON-friendly number (ints stay ints, floats keep 2 decimals max)."""
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        return int(x) if x.is_integer() else round(x, 2)
    return x


def format_target(answer: Any, unit: Any, points_xy: list[list[float]] | None = None, reason: str | None = None) -> str:
    """Canonical assistant reply used as the SFT target. points_xy are C2-style [x, y] in 0-1."""
    if answer is None:
        return json.dumps({"answer": None, "unit": None, "reason": reason or "not shown on this drawing"}, ensure_ascii=False)
    obj: dict[str, Any] = {"answer": format_number(answer), "unit": normalize_unit(unit)}
    if points_xy is not None:
        obj["points"] = [[round(y * 1000), round(x * 1000)] for x, y in points_xy]
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))


# --------------------------------------------------------------------------- parsing

_THINK = re.compile(r"<\|channel\>.*?<channel\|>", re.S)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)
_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")
_NUMERIC_STR = re.compile(r"^\s*(?:about|approx\.?|ca\.?|~)?\s*-?\d+(?:[.,]\d+)?\s*(?:m\s*[²2³3]?|ft\s*[²2]|sq\s*\.?\s*m|sqm|sf|pcs|items?)?\s*$", re.I)


def _strip_noise(text: str) -> str:
    text = _THINK.sub("", text or "")
    text = text.replace("<end_of_turn>", "").replace("<eos>", "").strip()
    return text


def extract_json(text: str) -> Any:
    """First JSON object/array in text, tolerant of fences, preambles, trailing junk, single quotes,
    and trailing commas. Returns None if nothing parses."""
    text = _strip_noise(text)
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    for cand in candidates:
        for start in (i for i, ch in enumerate(cand) if ch in "{["):
            span = _balanced(cand, start)
            if span is None:
                continue
            s = cand[start:span]
            for attempt in (s, re.sub(r",\s*([}\]])", r"\1", s), s.replace("'", '"')):
                try:
                    return json.loads(attempt)
                except json.JSONDecodeError:
                    continue
    return None


def _balanced(s: str, start: int) -> int | None:
    open_ch = s[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return i + 1 if c == close_ch else None
    return None


def _to_number(v: Any) -> float | int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v if not (isinstance(v, float) and math.isnan(v)) else None
    m = _NUM.search(str(v).replace(" ", "").replace(" ", ""))
    if not m:
        return None
    s = m.group(0).replace(",", ".")
    f = float(s)
    return int(f) if f.is_integer() and "." not in s else f


def _points(v: Any) -> list[list[float]] | None:
    """[[y, x] 0-1000, ...] -> [[x, y] 0-1, ...]. Also accepts {"point": [y, x]} items and box_2d."""
    if not isinstance(v, list):
        return None
    out = []
    for p in v:
        if isinstance(p, dict):
            p = p.get("point") or p.get("point_2d") or p.get("box_2d") or p.get("yx")
        if isinstance(p, (list, tuple)) and len(p) == 4:  # box_2d [y1, x1, y2, x2] -> centre
            p = [(p[0] + p[2]) / 2, (p[1] + p[3]) / 2]
        if isinstance(p, (list, tuple)) and len(p) == 2:
            try:
                y, x = float(p[0]), float(p[1])
            except (TypeError, ValueError):
                continue
            out.append([min(max(x / 1000, 0.0), 1.0), min(max(y / 1000, 0.0), 1.0)])
    return out


def parse_output(text: str, logprobs: Any = None) -> dict:
    """Model reply (+ optional vLLM logprobs) -> {answer, unit, points, confidence, reason, ok}.

    Never raises. ok=False means nothing usable was found (treat as abstain)."""
    res: dict[str, Any] = {"answer": None, "unit": None, "points": None, "confidence": None,
                           "reason": None, "ok": False, "abstained": False}
    obj = extract_json(text)
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):  # bare detection list
        obj = {"answer": len(obj), "unit": "count", "points": obj}
    if isinstance(obj, dict):
        lower = {str(k).lower(): v for k, v in obj.items()}
        raw_ans = next((lower[k] for k in ("answer", "value", "count", "result", "total") if k in lower), None)
        res["unit"] = normalize_unit(lower.get("unit"))
        res["reason"] = lower.get("reason")
        res["points"] = _points(lower.get("points"))
        if raw_ans is None and ("answer" in lower or res["reason"]):
            res["abstained"], res["ok"] = True, True
        elif isinstance(raw_ans, str) and not _NUMERIC_STR.match(raw_ans):
            if raw_ans.strip():
                res["answer"], res["ok"] = raw_ans.strip(), True  # text answers (schedules)
        else:
            res["answer"] = _to_number(raw_ans)
            res["ok"] = res["answer"] is not None
    else:
        # last resort: first number in the reply
        clean = _strip_noise(text)
        n = _to_number(clean)
        if n is not None:
            res["answer"], res["ok"] = n, True
            if re.search(r"m\s*[²2]", clean):
                res["unit"] = "m2"
    if res["unit"] is None and isinstance(res["answer"], int):
        res["unit"] = "count"
    res["confidence"] = answer_confidence(text, logprobs, res)
    return res


# --------------------------------------------------------------------------- confidence

def _tok_items(logprobs: Any) -> list[tuple[str, float]]:
    """Accepts the OpenAI SDK object, the raw JSON dict, a list of {token, logprob}, or (token, lp) pairs."""
    if logprobs is None:
        return []
    content = logprobs
    if isinstance(logprobs, dict):
        content = logprobs.get("content", logprobs.get("tokens"))
    elif hasattr(logprobs, "content"):
        content = logprobs.content
    items = []
    for t in content or []:
        if isinstance(t, dict):
            items.append((t.get("token", ""), float(t.get("logprob", 0.0))))
        elif isinstance(t, (list, tuple)) and len(t) == 2:
            items.append((str(t[0]), float(t[1])))
        elif hasattr(t, "token"):
            items.append((t.token, float(t.logprob)))
    return items


def answer_confidence(text: str, logprobs: Any, parsed: dict | None = None) -> float | None:
    """Mean token probability over the tokens that spell the answer value.

    The answer span is the value after "answer": in the reply (or the first number, if the
    model ignored the JSON format). If token texts don't line up with `text`, it falls back to
    the mean over all tokens that contain a digit, then over all tokens."""
    items = _tok_items(logprobs)
    if not items:
        return None
    joined = "".join(t for t, _ in items)
    m = re.search(r'"answer"\s*:\s*("(?:[^"\\]|\\.)*"|[^,}\s]+)', joined)
    if m is None:
        m = _NUM.search(joined)
    probs: list[float] = []
    if m is not None:
        a, b = m.span(1) if m.re.groups else m.span()
        pos = 0
        for tok, lp in items:
            end = pos + len(tok)
            if end > a and pos < b and tok.strip() not in ('"', ""):
                probs.append(math.exp(lp))
            pos = end
    if not probs:
        probs = [math.exp(lp) for t, lp in items if any(ch.isdigit() for ch in t)]
    if not probs:
        probs = [math.exp(lp) for _, lp in items]
    return round(sum(probs) / len(probs), 4)
