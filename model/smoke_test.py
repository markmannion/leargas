"""M2 done-when check + M3 round-trip data collection.

  python -m model.smoke_test --model gemma-base                          # one default question
  python -m model.smoke_test --model gemma-base --n 20                   # 20 held-out demo questions
  python -m model.smoke_test --image some.png --question "How many doors?"

Every raw reply is appended to data/model_outputs/raw.jsonl; tests/test_prompt.py replays that
file through parse_output (M3's "round-trips 20 real model outputs").
"""
from __future__ import annotations

import argparse

from .client import ask
from .common import SPLITS_DIR, load_jsonl


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma-base")
    ap.add_argument("--image", default="data/cubicasa5k/colorful-10052.png")
    ap.add_argument("--question", default="How many windows are shown on this floor plan?")
    ap.add_argument("--n", type=int, default=0, help="run the first N demo questions instead")
    ap.add_argument("--points", action="store_true")
    a = ap.parse_args()

    jobs = [(a.image, a.question, None)]
    if a.n:
        demo = [r for r in load_jsonl(SPLITS_DIR / "demo_questions.jsonl") if r["source"] in ("cubicasa5k", "swiss_dwellings")]
        jobs = [((r["path"][:-4] + ".png") if r["path"].endswith(".pdf") else r["path"], r["question"], r["answer"]) for r in demo[: a.n]]

    ok = 0
    for img, q, gold in jobs:
        out = ask(img, q, model=a.model, with_points=a.points, log_raw=True)
        ok += out["ok"]
        print(f"[{out['latency_ms']:5d} ms] {img.rsplit('/', 1)[-1][:40]:40s} -> {out['answer']!r:>8} {out['unit']} "
              f"conf={out['confidence']} gold={gold!r} | raw={out['raw'][:80]!r}")
    print(f"parsed {ok}/{len(jobs)}")


if __name__ == "__main__":
    main()
