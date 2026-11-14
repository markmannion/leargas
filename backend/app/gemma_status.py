"""Short, cached readiness checks and a cooldown after failed inference requests."""
from __future__ import annotations

import os
import time
from functools import lru_cache
from threading import Lock

import httpx

CHECK_TIMEOUT = float(os.environ.get("LEARGAS_GEMMA_CHECK_TIMEOUT", "3"))
CHECK_INTERVAL = float(os.environ.get("LEARGAS_GEMMA_CHECK_INTERVAL", "10"))


class Endpoint:
    def __init__(self, url: str, key: str):
        self.url, self.key = url.rstrip("/"), key
        self.lock = Lock()
        self.probing = Lock()
        self.models: set[str] = set()
        self.checked = False
        self.expires = 0.0
        self.failures: dict[str, float] = {}

    def _snapshot(self, model: str) -> dict:
        with self.lock:
            state = "checking" if not self.checked else "available" if model in self.models else "unavailable"
            if self.failures.get(model, 0) > time.monotonic():
                state = "unavailable"
            return {"status": state, "available": state == "available"}

    def status(self, model: str) -> dict:
        with self.lock:
            due = time.monotonic() >= self.expires
        # Only one caller probes an endpoint; others use its last known state.
        if due and self.probing.acquire(blocking=False):
            try:
                models = set()
                try:
                    with httpx.Client(timeout=CHECK_TIMEOUT, trust_env=False) as client:
                        response = client.get(f"{self.url}/models", headers={"Authorization": f"Bearer {self.key}"})
                        response.raise_for_status()
                        models = {row["id"] for row in response.json()["data"] if isinstance(row.get("id"), str)}
                except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                    pass
                with self.lock:
                    self.models, self.checked = models, True
                    self.expires = time.monotonic() + CHECK_INTERVAL
            finally:
                self.probing.release()
        return self._snapshot(model)

    def failed(self, model: str) -> None:
        with self.lock:
            self.failures[model] = time.monotonic() + CHECK_INTERVAL


@lru_cache(maxsize=8)
def endpoint(url: str, key: str = "") -> Endpoint:
    return Endpoint(url, key)


def status(model: str = "gemma-ft", *, url: str | None = None, key: str | None = None) -> dict:
    url = os.environ.get("MODEL_BASE_URL", "") if url is None else url
    if not url:
        return {"status": "unconfigured", "available": False}
    return endpoint(url, os.environ.get("MODEL_API_KEY", "") if key is None else key).status(model)


def failed(model: str, *, url: str | None = None, key: str | None = None) -> None:
    url = os.environ.get("MODEL_BASE_URL", "") if url is None else url
    if url:
        endpoint(url, os.environ.get("MODEL_API_KEY", "") if key is None else key).failed(model)


def reason(state: dict) -> str:
    if state["status"] == "unconfigured":
        return "Gemma is not configured (MODEL_BASE_URL)."
    if state["status"] == "checking":
        return "Gemma availability is being checked. Please try again shortly."
    return "Gemma is temporarily unavailable. Geometry and cached answers remain available; Gemma will retry automatically."
