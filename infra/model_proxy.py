"""One OpenAI-compatible URL in front of several vLLM servers (contract C3).

vLLM serves one model per process. Harry and the eval scripts should only ever see one
MODEL_BASE_URL, so this proxy routes /v1/chat/completions (and /v1/completions) by the
request's "model" field and merges /v1/models.

  python infra/model_proxy.py --port 8000
  ROUTES='gemma-base=http://localhost:8001,gemma-ft=http://localhost:8002' python infra/model_proxy.py

Needs fastapi, uvicorn, httpx (installed in ~/venv-vllm by setup_box.sh).
"""
from __future__ import annotations

import argparse
import os
import time

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

DEFAULT_ROUTES = (
    "gemma-base=http://localhost:8001,gemma-ft=http://localhost:8002,"
    "gemma-e2b=http://localhost:8003,gemma-26b=http://localhost:8004"
)
API_KEY = os.environ.get("MODEL_API_KEY", "")
ROUTES = dict(kv.split("=", 1) for kv in os.environ.get("ROUTES", DEFAULT_ROUTES).split(",") if kv)

app = FastAPI(title="BlueprintTrace model proxy")
client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0))


def _auth(req: Request) -> None:
    if API_KEY and req.headers.get("authorization", "") != f"Bearer {API_KEY}":
        raise HTTPException(401, "bad api key")


@app.get("/health")
async def health():
    out = {}
    for name, base in ROUTES.items():
        try:
            r = await client.get(f"{base}/health", timeout=2.0)
            out[name] = r.status_code == 200
        except httpx.HTTPError:
            out[name] = False
    return out


@app.get("/v1/models")
async def models(req: Request):
    _auth(req)
    data = []
    for name, base in ROUTES.items():
        try:
            r = await client.get(f"{base}/v1/models", headers={"authorization": f"Bearer {API_KEY}"}, timeout=2.0)
            if r.status_code == 200:
                data.extend(r.json().get("data", []))
        except httpx.HTTPError:
            pass
    return {"object": "list", "data": data}


@app.post("/v1/{path:path}")
async def forward(path: str, req: Request):
    _auth(req)
    body = await req.body()
    try:
        model = (await req.json()).get("model")
    except Exception:
        raise HTTPException(400, "body must be JSON with a 'model' field")
    base = ROUTES.get(model)
    if base is None:
        raise HTTPException(404, f"unknown model {model!r}; served: {sorted(ROUTES)}")
    t0 = time.perf_counter()
    try:
        r = await client.post(
            f"{base}/v1/{path}",
            content=body,
            headers={"content-type": "application/json", "authorization": f"Bearer {API_KEY}"},
        )
    except httpx.HTTPError as e:
        return JSONResponse({"error": f"{model} unreachable: {e}"}, status_code=502)
    headers = {"x-upstream-latency-ms": f"{(time.perf_counter() - t0) * 1000:.0f}", "x-served-by": model}
    return Response(r.content, status_code=r.status_code, media_type="application/json", headers=headers)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    print("routes:", ROUTES)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
