"""End-to-end eval: send a held-out split through POST /ask concurrently, then score it.

    python backend/eval_run.py --gold questions.jsonl --split heldout.txt --out runs/preds.jsonl
    python backend/eval_run.py --gold questions.jsonl --split heldout.txt --engine gemma_ft --out runs/ft.jsonl --resume

Each `Answer` is appended to `--out` as it arrives, so an interrupted run continues with `--resume`.
Requests that fail (HTTP error, timeout, invalid JSON) are logged to `<out>.errors.jsonl` and score
as missing. The gold `type` is not sent unless `--type-hint` is given, so the router has to infer it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from score import OFFICIAL_TOL, drawing_key, print_report, read_jsonl, score

Key = Tuple[str, str]


def select_gold(gold: List[Dict[str, Any]], split: Optional[List[str]], types: Optional[Set[str]],
                limit: Optional[int]) -> List[Dict[str, Any]]:
    keep = {drawing_key(s) for s in split} if split is not None else None
    out = [g for g in gold
           if (keep is None or drawing_key(g["path"]) in keep) and (types is None or g["type"] in types)]
    return out[:limit] if limit else out


def _done_keys(path: str) -> Set[Key]:
    if not os.path.exists(path):
        return set()
    return {(p["path"], p["question"]) for p in read_jsonl(path)}


async def run(items: List[Dict[str, Any]], api: str, out_path: str, *, engine: str, concurrency: int,
              timeout: float, type_hint: bool) -> Dict[str, Any]:
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    stats = {"ok": 0, "err": 0, "latencies": []}
    total, t0 = len(items), time.perf_counter()

    with open(out_path, "a", encoding="utf-8") as out, open(out_path + ".errors.jsonl", "a", encoding="utf-8") as errf:
        async with httpx.AsyncClient(base_url=api, timeout=timeout,
                                     limits=httpx.Limits(max_connections=concurrency)) as client:

            async def one(g: Dict[str, Any]) -> None:
                body = {"path": g["path"], "question": g["question"], "engine": engine}
                if type_hint:
                    body["type"] = g["type"]
                async with sem:
                    t = time.perf_counter()
                    try:
                        r = await client.post("/ask", json=body)
                        r.raise_for_status()
                        ans, err = r.json(), None
                    except (httpx.HTTPError, ValueError) as e:
                        detail = getattr(getattr(e, "response", None), "text", "")[:500]
                        ans, err = None, {**body, "error": f"{type(e).__name__}: {e}", "detail": detail}
                    dt = time.perf_counter() - t
                async with lock:
                    if ans is not None:
                        # key on the gold pair so a server that rewrites path/question still scores
                        ans["path"], ans["question"] = g["path"], g["question"]
                        out.write(json.dumps(ans, ensure_ascii=False) + "\n")
                        stats["ok"] += 1
                        stats["latencies"].append(dt)
                    else:
                        errf.write(json.dumps(err, ensure_ascii=False) + "\n")
                        stats["err"] += 1
                    done = stats["ok"] + stats["err"]
                    if done % 50 == 0 or done == total:
                        out.flush()
                        rate = done / max(time.perf_counter() - t0, 1e-9)
                        print(f"\r{done}/{total}  errors={stats['err']}  {rate:.1f} q/s", end="", file=sys.stderr, flush=True)

            await asyncio.gather(*(one(g) for g in items))
    print(file=sys.stderr)
    lat = sorted(stats["latencies"])
    return {
        "sent": total,
        "ok": stats["ok"],
        "errors": stats["err"],
        "wall_s": time.perf_counter() - t0,
        "latency_p50_s": lat[len(lat) // 2] if lat else None,
        "latency_p95_s": lat[int(len(lat) * 0.95)] if lat else None,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", required=True, help="questions.jsonl")
    ap.add_argument("--split", help="file of held-out drawing paths, one per line (default: all of --gold)")
    ap.add_argument("--out", required=True, help="predictions JSONL to write")
    ap.add_argument("--api", default=os.environ.get("LEARGAS_API", "http://127.0.0.1:8000"))
    ap.add_argument("--engine", default="auto", choices=["auto", "geometry", "gemma_ft", "gemma_base"])
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--timeout", type=float, default=120.0, help="per-request timeout, seconds")
    ap.add_argument("--types", help="comma-separated question types to send, e.g. count,area")
    ap.add_argument("--limit", type=int, help="only the first N selected questions (smoke test)")
    ap.add_argument("--type-hint", action="store_true", help="send the gold question type to /ask")
    ap.add_argument("--resume", action="store_true", help="keep --out and skip questions already answered")
    ap.add_argument("--tol", type=float, default=OFFICIAL_TOL)
    ap.add_argument("--json", help="write scores + run stats JSON here (default: <out>.score.json)")
    a = ap.parse_args(argv)

    split = None
    if a.split:
        with open(a.split, encoding="utf-8") as f:
            split = [l for l in f if l.strip()]
    types = set(a.types.split(",")) if a.types else None
    gold = select_gold(read_jsonl(a.gold), split, types, a.limit)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    if not a.resume:
        for p in (a.out, a.out + ".errors.jsonl"):
            if os.path.exists(p):
                os.remove(p)
    done = _done_keys(a.out)
    todo = [g for g in gold if (g["path"], g["question"]) not in done]
    print(f"{len(gold)} questions selected, {len(done)} already answered, sending {len(todo)} to {a.api} "
          f"(engine={a.engine}, concurrency={a.concurrency})", file=sys.stderr)

    stats = asyncio.run(run(todo, a.api, a.out, engine=a.engine, concurrency=a.concurrency,
                            timeout=a.timeout, type_hint=a.type_hint)) if todo else {"sent": 0}

    # score exactly the selected questions; the split/type/limit filter is already applied
    res = score(gold, read_jsonl(a.out) if os.path.exists(a.out) else [], a.tol)
    res["_run"] = {**stats, "api": a.api, "engine": a.engine, "split": a.split, "types": a.types, "limit": a.limit}
    print_report(res)
    if stats.get("errors"):
        print(f"{stats['errors']} requests failed, see {a.out}.errors.jsonl", file=sys.stderr)
    with open(a.json or a.out + ".score.json", "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
