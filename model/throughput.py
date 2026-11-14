"""M11b: measured throughput -> $ per 1,000 questions, per served model.

  python -m model.throughput --model gemma-ft --usd-per-hour 2.00 --gpu "L40S 48GB"
  python -m model.throughput --model gemma-26b --usd-per-hour 2.81 --gpu "RTX PRO 6000" --n 128 --workers 32

Sends n raster eval questions with `workers` concurrent requests (saturating the batcher, like a busy
service) and records questions/second. $/1k = usd_per_hour / (q/s * 3600) * 1000.
Results merge into results/throughput.json, which eval/sweep_chart.py reads.

Caveat to state on the slide: when two models share one GPU, each was measured while the other
was idle, so it's the throughput of the whole box spent on that model.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from .baseline_eval import RASTER_EVAL, RESULTS
from .client import ask
from .common import abs_path, load_jsonl


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--usd-per-hour", type=float, default=float(os.environ.get("MODEL_USD_PER_HOUR", 0) or 0))
    ap.add_argument("--gpu", default="")
    ap.add_argument("--n", type=int, default=96)
    ap.add_argument("--workers", type=int, default=24)
    a = ap.parse_args()
    if not a.usd_per_hour:
        raise SystemExit("--usd-per-hour (or MODEL_USD_PER_HOUR) is required: read it off the Verda dashboard")

    rows = load_jsonl(RASTER_EVAL)[: a.n]
    ask(abs_path(rows[0]["image"]), rows[0]["question"], model=a.model)  # warm-up
    lat = []

    def one(r):
        out = ask(abs_path(r["image"]), r["question"], model=a.model)
        lat.append(out["latency_ms"])
        return out

    t0 = time.perf_counter()
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, rows))
    wall = time.perf_counter() - t0
    qps = len(rows) / wall
    rec = {
        "model": a.model, "gpu": a.gpu, "usd_per_hour": a.usd_per_hour, "n": len(rows), "workers": a.workers,
        "qps": round(qps, 3), "usd_per_1k": round(a.usd_per_hour / (qps * 3600) * 1000, 4),
        "median_latency_ms": statistics.median(lat), "measured": time.strftime("%F %T"),
    }
    path = RESULTS / "throughput.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[a.model] = rec
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rec, indent=2))


if __name__ == "__main__":
    main()
