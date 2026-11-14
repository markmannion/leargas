"""Raster engine for Harry's router: one call -> a dict that validates as backend/app/schema.py `Answer`.

    from model.gemma_engine import answer as gemma_answer
    a = gemma_answer("data/cubicasa5k/colorful-10052.png", "How many windows?", engine="gemma_ft")
    Answer(**a)   # valid: status, source, evidence[].shape, sources[], latency_ms ...

What it does
- Picks the image the model sees: swiss .pdf/.dxf -> the PNG twin; images as-is. Anything else
  (IFC, opening_design PDFs) -> cannot_verify, since there's no raster to read.
- Swiss area question on a render that does not print room m² -> cannot_verify without calling the
  model (base Gemma is 0/68 on those; the DXF engine should answer them).
- Calls the served model (C3, model/client.py) and parses the reply (model/prompt.py).
- Status from calibrated confidence (results/calibration_<label>.json, made by model.calibrate):
    conf >= accept threshold        -> "verified"
    abstain floor <= conf < accept  -> "partial"   (answer shown, flagged as weakly supported)
    conf < abstain floor / no parse -> "cannot_verify" (answer null; the model's guess kept in sources[])
- Points (run 2, or `with_points=True`) become point evidence, numbered by the frontend.
- GEMMA_CROP_SWISS=1: swiss sheets are cropped to the plan before the model sees them (model/crop.py),
  and points are mapped back to sheet coordinates. Set it iff the served model was trained on crops.

Stdlib only (plus Pillow via prompt.py), so the backend needs no new dependencies.
Evidence coordinates are normalised 0-1 on the image the model saw. For swiss that is the PNG twin;
if /drawing serves the PDF page instead, check the two share the same framing (see HANDOFF).
"""
from __future__ import annotations

import json
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from .common import REPO_ROOT, abs_path, prints_areas, source_of

RESULTS = REPO_ROOT / "results"
SERVED_NAME = {"gemma_ft": "gemma-ft", "gemma_base": "gemma-base"}
UNITS = {"count", "m", "m2", "m3", "ft", "ft2", "ft3"}
IMAGE_EXT = {".png", ".jpg", ".jpeg"}

# Fallbacks when no calibration file exists. gemma-base on 957 held-out raster answers (Sat 12:15):
# conf >= 0.99 -> 93% right, 0.5-0.7 -> 27%, < 0.5 -> 15%.
DEFAULT_ACCEPT = 0.99
DEFAULT_FLOOR = float(os.environ.get("GEMMA_ABSTAIN_FLOOR", "0.5"))


def image_for(path: str) -> Path | None:
    """Dataset path -> the raster the model reads, or None if there isn't one."""
    p = Path(path)
    if p.suffix.lower() in IMAGE_EXT:
        return abs_path(path) if path.startswith("data/") else p
    if source_of(path) == "swiss_dwellings" and p.suffix.lower() in (".pdf", ".dxf"):
        return abs_path(str(p.with_suffix(".png")).replace("\\", "/"))
    return None


@lru_cache(maxsize=8)
def _calibration(label: str) -> dict:
    f = RESULTS / f"calibration_{label}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8")).get("thresholds", {})
        except (OSError, ValueError):
            pass
    return {}


def accept_threshold(label: str, source: str, qtype: str) -> float:
    th = _calibration(label)
    t = th.get(f"{source}/{qtype}")
    if t is None:
        t = th.get("ALL")
    return float(t) if t is not None else DEFAULT_ACCEPT


_AREA_WORDS = re.compile(r"m²|m2|\barea|fläche|surface|superficie|pinta-ala|areal|yta", re.I)


def guess_type(question: str, unit: str | None = None) -> str:
    if unit in ("m2", "ft2") or _AREA_WORDS.search(question):
        return "area"
    if unit in ("m", "ft"):
        return "length"
    if unit in ("m3", "ft3"):
        return "volume"
    return "count"


def _clip01(v: float) -> float:
    return min(1.0, max(0.0, float(v)))


def _base(path: str, question: str, qtype: str, source: str) -> dict:
    return {"path": path, "question": question, "type": qtype, "source": source, "evidence": [], "sources": []}


def _cannot(base: dict, why: str, latency_ms: float, confidence: float = 0.0) -> dict:
    return {**base, "answer": None, "unit": None, "status": "cannot_verify", "confidence": round(confidence, 4),
            "explanation": why, "latency_ms": round(latency_ms, 1)}


def answer(path: str, question: str, engine: str = "gemma_ft", qtype: str | None = None,
           with_points: bool | None = None, label: str | None = None, timeout: float = 60.0,
           ask_fn=None) -> dict:
    """Answer one question with Gemma. Never raises for model/parse failures (returns cannot_verify).

    engine: "gemma_ft" | "gemma_base" (Harry's Source values). label: calibration label
    (default: the served name, e.g. "gemma-ft"). ask_fn: injectable for tests (model.client.ask).
    """
    t0 = time.perf_counter()
    served = SERVED_NAME.get(engine, engine)
    label = label or served
    src = source_of(path)
    qtype = qtype or guess_type(question)
    base = _base(path, question, qtype, engine)

    img = image_for(path)
    if img is None:
        return _cannot(base, "No raster image for this drawing, so Gemma has nothing to read.", 0.0)
    if src == "swiss_dwellings" and qtype == "area" and prints_areas(path) is False:
        return _cannot(base, "This render doesn't print room areas, so they can't be read off the image. "
                             "Use the DXF geometry.", (time.perf_counter() - t0) * 1000)
    if with_points is None:
        with_points = qtype == "count" and engine == "gemma_ft" and os.environ.get("GEMMA_POINTS", "0") == "1"

    if ask_fn is None:
        from .client import ask as ask_fn  # noqa: PLC0415  (import late: reads .env)
    image: Any = str(img)
    box = None
    if src == "swiss_dwellings" and os.environ.get("GEMMA_CROP_SWISS", "0") == "1":
        from .crop import cropped  # noqa: PLC0415
        try:
            image, box = cropped(str(img))
        except Exception:  # noqa: BLE001  fall back to the full sheet
            image, box = str(img), None
    try:
        out = ask_fn(image, question, model=served, with_points=with_points, timeout=timeout)
    except Exception as e:  # noqa: BLE001  network / HTTP errors -> abstain, router keeps going
        return _cannot(base, f"Gemma endpoint error: {type(e).__name__}: {str(e)[:160]}",
                       (time.perf_counter() - t0) * 1000)
    latency = out.get("latency_ms") or (time.perf_counter() - t0) * 1000
    conf = out.get("confidence")
    conf = 0.0 if conf is None else _clip01(conf)

    if out.get("abstained"):
        return _cannot(base, out.get("reason") or "Gemma declined to answer from this drawing.", latency, conf)
    ans = out.get("answer")
    if not out.get("ok") or ans is None:
        return _cannot(base, "Gemma's reply couldn't be parsed into an answer.", latency, conf)

    unit = out.get("unit") if out.get("unit") in UNITS else None
    if isinstance(ans, str):
        qtype = "text"
        unit = None
    else:
        if unit is None:
            unit = "count" if qtype == "count" else "m2" if qtype == "area" else None
        if qtype == "count" or unit == "count":
            if float(ans) != int(ans):
                return _cannot(base, f"Gemma gave a non-integer count ({ans}).", latency, conf)
            ans, unit = int(ans), "count"
        elif unit:
            qtype = {"m2": "area", "ft2": "area", "m": "length", "ft": "length", "m3": "volume", "ft3": "volume"}.get(unit, qtype)
    base["type"] = qtype

    guess = {"source": engine, "answer": ans, "unit": unit, "confidence": round(conf, 4)}
    accept = accept_threshold(label, src, qtype)
    if conf < DEFAULT_FLOOR:
        a = _cannot(base, f"Gemma guessed {ans} but its confidence ({conf:.0%}) is below the "
                          f"{DEFAULT_FLOOR:.0%} floor.", latency, conf)
        a["sources"] = [guess]
        return a
    status = "verified" if conf >= accept else "partial"

    evidence = []
    for i, pt in enumerate(out.get("points") or [], 1):
        try:
            if box is not None:
                from .crop import crop_to_sheet  # noqa: PLC0415
                pt = crop_to_sheet(pt, box)
            x, y = _clip01(pt[0]), _clip01(pt[1])
        except (TypeError, ValueError, IndexError):
            continue
        evidence.append({"shape": {"kind": "point", "point": [x, y]}, "page": 0,
                         "label": f"item {i}", "value": None, "source": engine})

    why = out.get("reason") or (f"{'Fine-tuned' if engine == 'gemma_ft' else 'Base'} Gemma read the image"
                                + (f" and marked {len(evidence)} item(s)" if evidence else ""))
    if status == "partial":
        why += f". Confidence {conf:.1%} is below the {accept:.1%} needed to call it verified."
    return {**base, "answer": ans, "unit": unit, "status": status, "confidence": round(conf, 4),
            "evidence": evidence, "explanation": why, "sources": [guess], "latency_ms": round(latency, 1)}


if __name__ == "__main__":  # quick manual check against the live endpoint
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("question")
    ap.add_argument("--engine", default="gemma_base")
    a = ap.parse_args()
    print(json.dumps(answer(a.path, a.question, engine=a.engine), indent=1, ensure_ascii=False))
