"""Evaluate synthetic floor plans using a vision endpoint, API, or local geometry.

    python -m model.synthetic_eval --data data/synthetic --engine gemma-base
    python -m model.synthetic_eval --data data/synthetic --engine geometry --category geometry --language en
    python -m model.synthetic_eval --data data/synthetic --predictions external.jsonl

Vision calls use model.client and its existing MODEL_BASE_URL/MODEL_API_KEY settings.
Only the image and question are supplied to the model. No gold hints are sent.
"""
from __future__ import annotations

import argparse
import collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import random
import sys
import time

from .common import REPO_ROOT
from .scoring import _HARRY


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate(gold: list[dict], predictions: list[dict]) -> tuple[dict, list[dict]]:
    """Missing/errors never earn credit for abstention. Mock gold lookups are rejected."""
    if any(p.get("source") == "mock" or any(s.get("source") == "mock" for s in p.get("sources", []))
           for p in predictions):
        raise ValueError("Mock predictions cannot measure model accuracy; disable LEARGAS_MOCK.")
    if _HARRY is None:
        raise RuntimeError("backend/score.py is required for unit-aware scoring")
    by_id = {p["id"]: p for p in predictions if "id" in p}
    by_pair = {(p["path"], p["question"]): p for p in predictions if "path" in p and "question" in p}
    buckets = collections.defaultdict(collections.Counter)
    details = []
    for g in gold:
        p = by_id.get(g["id"], by_pair.get((g["path"], g["question"])))
        expected_refusal = g.get("expected") == "cannot_verify"
        invalid = p is not None and (p.get("error") or p.get("ok") is False)
        refusal = p is not None and not invalid and (p.get("status") == "cannot_verify" or p.get("abstained") is True
                                                    or ("answer" in p and p["answer"] is None))
        if p is None:
            correct, outcome = False, "missing"
        elif invalid or "answer" not in p:
            correct, outcome = False, "error"
        elif expected_refusal:
            correct = bool(refusal)
            outcome = "correct_refusal" if correct else "unsupported_answer"
        elif refusal:
            correct, outcome = False, "abstain"
        else:
            result = _HARRY(g, p)
            correct, outcome = result["correct"], result["outcome"]
        keys = ["overall", "unanswerable" if expected_refusal else "answerable"]
        keys += [f"{k}/{g[k]}" for k in ("type", "difficulty", "style", "language", "category", "split")]
        answered = p is not None and not invalid and "answer" in p and not refusal
        for key in keys:
            b = buckets[key]
            b["n"] += 1
            b["correct"] += correct
            b["answered"] += answered
            b["correct_answered"] += correct and answered
            b[outcome] += 1 if outcome != "correct" else 0
        details.append(dict(id=g["id"], path=g["path"], question=g["question"],
                            gold=g["answer"], predicted=p.get("answer") if p else None,
                            correct=bool(correct), outcome=outcome, group_id=g["group_id"]))
    report = {}
    for key, b in sorted(buckets.items(), key=lambda kv: (kv[0] != "overall", kv[0])):
        report[key] = dict(n=b["n"], correct=b["correct"], accuracy=b["correct"] / b["n"],
                           coverage=b["answered"] / b["n"],
                           precision=b["correct_answered"] / b["answered"] if b["answered"] else None,
                           outcomes={k: v for k, v in b.items() if k not in {"n", "correct", "answered", "correct_answered"} and v})
    groups = collections.defaultdict(list)
    for row in details:
        groups[row["group_id"]].append(row["correct"])
    report["_meta"] = dict(independent_layouts=len(groups), questions=len(gold), tolerance=.02,
                           layout_macro_accuracy=sum(sum(v) / len(v) for v in groups.values()) / len(groups) if groups else None,
                           note="Synthetic accuracy only. Variants and paraphrases of each layout are correlated.")
    return report, details


@lru_cache(maxsize=128)
def _drawing(path: str):
    from app.dxf import parse_dxf
    return parse_dxf(path)


def predict(g: dict, root: Path, engine: str, api: str | None, timeout: float, points: bool) -> dict:
    started = time.perf_counter()
    try:
        if api:
            import httpx
            name = {"gemma-base": "gemma_base", "gemma-ft": "gemma_ft"}.get(engine, engine)
            r = httpx.post(api.rstrip("/") + "/ask", json=dict(path=g["path"], question=g["question"], engine=name), timeout=timeout)
            r.raise_for_status()
            p = r.json()
        elif engine == "geometry":
            from app.dxf import CannotVerify
            from app.query.adapters import to_dxf
            from app.query.parser import parse
            q = parse(g["question"], use_llm=False).query
            dq = to_dxf(q) if q is not None else None
            try:
                if dq is None:
                    raise CannotVerify("Question unsupported by the local parser / DXF adapter")
                result = _drawing(str(root / Path(g["path"]).with_suffix(".dxf"))).query(dq)
                p = dict(answer=result.value, unit=result.unit, status="verified", source="geometry_dxf")
            except CannotVerify as e:
                p = dict(answer=None, unit=None, status="cannot_verify", reason=str(e), source="geometry_dxf")
        else:
            from .client import ask
            p = ask(str(root / g["path"]), g["question"], model=engine, timeout=timeout, with_points=points)
        if not isinstance(p, dict):
            raise ValueError("Expected a JSON object prediction")
        p.update(id=g["id"], path=g["path"], question=g["question"])
        p["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return p
    except Exception as e:
        return dict(id=g["id"], path=g["path"], question=g["question"], answer=None,
                    error=f"{type(e).__name__}: {e}", latency_ms=round((time.perf_counter() - started) * 1000, 2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=Path("data/synthetic"))
    ap.add_argument("--engine", choices=("gemma-base", "gemma-ft", "geometry", "auto"), default="gemma-base")
    ap.add_argument("--api", help="Existing /ask API; its LEARGAS_DATA_ROOT must point to --data")
    ap.add_argument("--split", choices=("train", "validation", "test", "all"), default="test")
    for k in ("category", "language", "style", "difficulty"):
        ap.add_argument("--" + k, help="Comma-separated values to include")
    ap.add_argument("--limit", type=int, help="Deterministic shuffled subset, not the first N rows")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--points", action="store_true")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--predictions", type=Path, help="Score existing predictions without making calls")
    a = ap.parse_args()
    if a.concurrency < 1 or a.timeout <= 0 or (a.limit is not None and a.limit < 1):
        ap.error("concurrency, timeout and limit must be positive")
    if a.engine == "auto" and not a.api and not a.predictions:
        ap.error("--engine auto requires --api")
    root = a.data.resolve()
    gold_path = root / "questions.jsonl"
    gold = read_jsonl(gold_path)
    if a.split != "all":
        gold = [g for g in gold if g["split"] == a.split]
    for key in ("category", "language", "style", "difficulty"):
        if value := getattr(a, key):
            gold = [g for g in gold if g[key] in value.split(",")]
    random.Random(a.seed).shuffle(gold)
    if a.limit:
        gold = gold[:a.limit]
    if not gold:
        ap.error("No questions match this selection")
    out = a.out or (a.predictions if a.predictions else
                    Path("results/synthetic") / f"{a.engine}_{a.split}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    config = dict(dataset_sha256=hashlib.sha256(gold_path.read_bytes()).hexdigest(),
                  selection_sha256=hashlib.sha256("\n".join(g["id"] for g in gold).encode()).hexdigest(),
                  engine=a.engine, api=a.api, points=a.points)
    metadata = Path(str(out) + ".run.json")
    if a.predictions:
        preds = read_jsonl(a.predictions)
    else:
        # Validate connection before starting a large run. Never load gold into mock mode.
        if a.api:
            import httpx
            health = httpx.get(a.api.rstrip("/") + "/health", timeout=a.timeout)
            health.raise_for_status()
            if health.json().get("mode") == "mock":
                ap.error("API is in mock mode; disable LEARGAS_MOCK before evaluating")
        elif a.engine != "geometry":
            from .client import base_url
            base_url()
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        if out.exists():
            if not a.resume:
                ap.error(f"{out} already exists; choose --out or use --resume")
            if not metadata.exists() or json.loads(metadata.read_text()) != config:
                ap.error("Resume configuration/dataset/selection differs from the saved run")
            preds = read_jsonl(out)
        else:
            preds = []
            metadata.write_text(json.dumps(config, indent=2) + "\n")
        done = {p["id"] for p in preds if not p.get("error") and p.get("ok") is not False}
        todo = [g for g in gold if g["id"] not in done]
        print(f"Selected {len(gold)} questions on {len({g['group_id'] for g in gold})} layouts; running {len(todo)} ({a.engine})", flush=True)
        started = time.perf_counter()
        with out.open("a", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=a.concurrency) as pool:
            jobs = [pool.submit(predict, g, root, a.engine, a.api, a.timeout, a.points) for g in todo]
            for i, future in enumerate(as_completed(jobs), 1):
                p = future.result()
                preds.append(p)
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
                f.flush()
                if i % 100 == 0 or i == len(todo):
                    print(f"{i}/{len(todo)} predictions ({time.perf_counter() - started:.1f}s)", flush=True)
    report, details = evaluate(gold, preds)
    report["_run"] = config
    score_path = Path(str(out) + ".score.json")
    score_path.write_text(json.dumps(report, indent=2) + "\n")
    Path(str(out) + ".details.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in details), encoding="utf-8")
    for key, b in report.items():
        if not key.startswith("_"):
            print(f"{key:30s} n={b['n']:6d} accuracy={b['accuracy']:7.2%} coverage={b['coverage']:7.2%}")
    print(f"Saved {score_path}")


if __name__ == "__main__":
    main()
