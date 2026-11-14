"""Tiny stdlib client for the C3 endpoint (OpenAI-compatible vLLM behind infra/model_proxy.py).

    from model.client import ask, chat
    out = ask("data/cubicasa5k/colorful-10052.png", "How many windows?", model="gemma-ft")
    # parse_output(...) fields + {"raw": str, "latency_ms": int, "model": str, "usage": {...}}

Reads MODEL_BASE_URL / MODEL_API_KEY from the environment or the repo's .env.
No third-party deps, so it works on the laptop, on the box and inside Harry's backend.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .common import REPO_ROOT, abs_path
from .prompt import PROMPT_VERSION, build_messages, parse_output, request_params

RAW_LOG = REPO_ROOT / "data" / "model_outputs" / "raw.jsonl"


def _load_env() -> None:
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


def base_url() -> str:
    url = os.environ.get("MODEL_BASE_URL")
    if not url:
        raise RuntimeError("MODEL_BASE_URL not set (see .env.example)")
    return url.rstrip("/")


def chat(messages: list[dict], model: str, timeout: float = 120.0, **params: Any) -> dict:
    """POST /chat/completions, return the raw JSON response plus latency_ms."""
    body = {"model": model, "messages": messages, **params}
    req = urllib.request.Request(
        f"{base_url()}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ.get('MODEL_API_KEY', '')}"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{model}: HTTP {e.code}: {e.read()[:500]!r}") from e
    data["latency_ms"] = round((time.perf_counter() - t0) * 1000)
    return data


def resolve_image(image: Any) -> Any:
    """Dataset-relative 'data/...' paths are resolved against JUNCTION_DATA."""
    if isinstance(image, str) and image.startswith("data/") and not Path(image).exists():
        return abs_path(image)
    return image


def ask(image: Any, question: str, model: str = "gemma-base", with_points: bool = False,
        max_tokens: int = 256, log_raw: bool = False, timeout: float = 120.0) -> dict:
    msgs = build_messages(resolve_image(image), question, with_points=with_points)
    resp = chat(msgs, model, timeout=timeout, **request_params(max_tokens))
    choice = resp["choices"][0]
    text = choice["message"].get("content") or ""
    out = parse_output(text, choice.get("logprobs"))
    out.update(raw=text, latency_ms=resp["latency_ms"], model=model, usage=resp.get("usage", {}),
               prompt_version=PROMPT_VERSION)
    if log_raw:
        RAW_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(RAW_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"model": model, "image": str(image), "question": question, "text": text,
                                "logprobs": choice.get("logprobs"), "parsed": {k: out[k] for k in
                                ("answer", "unit", "points", "confidence", "ok")}}, ensure_ascii=False) + "\n")
    return out
