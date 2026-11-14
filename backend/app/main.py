"""FastAPI app. `/ask` goes through the router (app/router.py): geometry engines + Gemma, reconciled.

Mock mode (LEARGAS_MOCK=1): if the (path, question) pair is in questions.jsonl, return the gold answer
with placeholder evidence (status=verified, source=mock); otherwise cannot_verify. Kept for frontend
work without the engines installed. Never used for evaluation.

Demo cache (LEARGAS_DEMO_CACHE=1): answers stored by backend/demo_cache.py are returned first, with
header X-Leargas-Cache: hit; misses go to the router (or mock) as usual. See app/demo_cache.py.

Run:  uvicorn app.main:app --reload --app-dir backend
"""

from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from typing import Dict, Tuple

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from . import demo_cache
from . import router as qa_router
from .drawings import questions_path, router as drawings_router
from .router import _guess_type
from .voice import router as voice_router

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
app.include_router(voice_router)


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
    mode = "mock" if _mock() else "live"
    gemma = qa_router.gemma_health() if mode == "live" else {"status": "disabled", "available": False, "models": {}}
    out = {"ok": True, "mode": mode, "gemma": gemma["available"], "gemma_status": gemma,
           "gold_questions_loaded": len(_gold())}
    if demo_cache.enabled():
        out["demo_cache"] = {"path": str(demo_cache.cache_path()),
                             "entries": len(demo_cache.entries(demo_cache.cache_path()))}
    return out


def _mock() -> bool:
    return os.environ.get("LEARGAS_MOCK", "").lower() in ("1", "true", "yes")


@app.get("/schema")
def schema() -> dict:
    """JSON Schema for request and response, for the frontend / Mark's parser."""
    return {"request": AskRequest.model_json_schema(), "answer": Answer.model_json_schema()}


@app.post("/ask", response_model=Answer)
def ask(req: AskRequest, response: Response) -> Answer:
    if demo_cache.enabled() and req.region is None:
        hit = demo_cache.lookup(req.path, req.question, req.engine)
        if hit is not None:
            response.headers["X-Leargas-Cache"] = "hit"
            return Answer.model_validate({**hit, "path": req.path, "question": req.question})
        response.headers["X-Leargas-Cache"] = "miss"
    if not _mock():
        return qa_router.route(req)
    return _mock_ask(req)


def _mock_ask(req: AskRequest) -> Answer:
    t0 = time.perf_counter()
    if req.region is not None:
        return Answer(
            path=req.path, question=req.question, region=req.region,
            answer=None, unit=None, type=req.type or _guess_type(req.question),
            status=Status.cannot_verify, confidence=0.0, source=Source.mock,
            explanation="Region questions require a live engine; whole-sheet dataset answers cannot verify a region.",
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
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
