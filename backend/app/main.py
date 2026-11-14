"""FastAPI scaffold. `/ask` is a mock until the router lands (Sat 18:30).

Mock behaviour: if LEARGAS_QUESTIONS points at questions.jsonl and the (path, question) pair is in it,
return the gold answer with placeholder evidence (status=verified, source=mock). Otherwise return
cannot_verify. Either way the response is a valid `Answer`, so the frontend can build against it.

Run:  uvicorn app.main:app --reload --app-dir backend
"""

from __future__ import annotations

import json
import time
from functools import lru_cache
from typing import Dict, Tuple

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .drawings import questions_path, router as drawings_router

from .schema import (
    Answer,
    AskRequest,
    BBoxEvidence,
    Evidence,
    PointEvidence,
    QuestionType,
    Source,
    Status,
)

app = FastAPI(title="leargas / BlueprintTrace", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(drawings_router)


@lru_cache(maxsize=1)
def _gold() -> Dict[Tuple[str, str], dict]:
    p = questions_path()
    if p is None:
        return {}
    out = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            out[(r["path"], r["question"])] = r
    return out


def _guess_type(question: str) -> QuestionType:
    q = question.lower()
    if any(k in q for k in ("m²", "m2", "area", "fläche", "pinta-ala", "areal", "surface")):
        return QuestionType.area
    if any(k in q for k in ("m³", "m3", "volume", "volumen")):
        return QuestionType.volume
    if any(k in q for k in ("length", "metres", "meters", "länge", "længde")):
        return QuestionType.length
    return QuestionType.count


def _mock_evidence(n: int) -> list:
    if n <= 0:
        return [Evidence(shape=BBoxEvidence(bbox=(0.25, 0.25, 0.75, 0.75)), label="mock region", source=Source.mock)]
    n = min(n, 30)
    return [
        Evidence(shape=PointEvidence(point=(0.1 + 0.8 * (i + 0.5) / n, 0.5)), label=f"mock item {i + 1}", source=Source.mock)
        for i in range(n)
    ]


@app.get("/health")
def health() -> dict:
    return {"ok": True, "mode": "mock", "gold_questions_loaded": len(_gold())}


@app.get("/schema")
def schema() -> dict:
    """JSON Schema for request and response, for the frontend / Mark's parser."""
    return {"request": AskRequest.model_json_schema(), "answer": Answer.model_json_schema()}


@app.post("/ask", response_model=Answer)
def ask(req: AskRequest) -> Answer:
    t0 = time.perf_counter()
    g = _gold().get((req.path, req.question))
    if g is not None:
        qtype = QuestionType(g["type"])
        ans = g["answer"]
        ev = _mock_evidence(ans if qtype == QuestionType.count else 0) if qtype != QuestionType.text else []
        return Answer(
            path=req.path,
            question=req.question,
            answer=ans,
            unit=g["unit"],
            type=qtype,
            status=Status.verified,
            confidence=1.0,
            source=Source.mock,
            evidence=ev,
            explanation="Mock: gold answer from questions.jsonl, placeholder evidence.",
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    return Answer(
        path=req.path,
        question=req.question,
        answer=None,
        unit=None,
        type=req.type or _guess_type(req.question),
        status=Status.cannot_verify,
        confidence=0.0,
        source=Source.mock,
        explanation="Mock: no engine connected yet and question not in the gold set.",
        latency_ms=(time.perf_counter() - t0) * 1000,
    )
