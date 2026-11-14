"""Model soup: a weighted sum of merged checkpoints that share one base model.

    python -m model.soup --out ~/merged/soup  ~/merged/run1:0.5 ~/merged/run2:0.5
    python -m model.soup --out ~/merged/super ~/merged/spec-cc:1 ~/merged/run2:0.5 ~/merged/run1:-0.5

The second form is task arithmetic: spec-cc + 0.5 * (run2 - run1), i.e. the run1/run2 soup with the
specialist's own delta on top. Weights should sum to 1 so the frozen (identical) tensors stay unchanged.
Runs on the box (needs torch + safetensors); every input dir needs a single model.safetensors.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path


def main() -> None:
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help="dir:weight, e.g. ~/merged/run1:0.5")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    parts = []
    for spec in args.inputs:
        d, w = spec.rsplit(":", 1)
        parts.append((Path(d).expanduser(), float(w)))
    total = sum(w for _, w in parts)
    if abs(total - 1.0) > 1e-6:
        raise SystemExit(f"weights sum to {total}, not 1")

    handles = [safe_open(str(d / "model.safetensors"), framework="pt") for d, _ in parts]
    keys = set(handles[0].keys())
    for (d, _), h in zip(parts[1:], handles[1:]):
        if set(h.keys()) != keys:
            raise SystemExit(f"{d} has different tensor names from {parts[0][0]}")

    t0 = time.time()
    out, changed = {}, 0
    for i, k in enumerate(sorted(keys)):
        ts = [h.get_tensor(k) for h in handles]
        if all(torch.equal(ts[0], t) for t in ts[1:]):
            out[k] = ts[0]  # frozen tensor: identical everywhere, keep it bit-exact
            continue
        acc = sum(w * t.float() for (_, w), t in zip(parts, ts))
        out[k] = acc.to(ts[0].dtype).contiguous()
        changed += 1
        if i % 500 == 0:
            print(f"  {i}/{len(keys)} tensors, {changed} changed, {time.time() - t0:.0f}s", flush=True)

    dst = Path(args.out).expanduser()
    dst.mkdir(parents=True, exist_ok=True)
    for f in parts[0][0].iterdir():  # config, tokenizer, chat template, ...
        if f.is_file() and f.name not in ("model.safetensors", "bt_merge_info.json"):
            shutil.copy2(f, dst / f.name)
    save_file(out, str(dst / "model.safetensors"), metadata={"format": "pt"})
    info = {"soup": [[str(d), w] for d, w in parts], "changed_tensors": changed,
            "total_tensors": len(keys), "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    (dst / "bt_merge_info.json").write_text(json.dumps(info))
    print(f"wrote {dst}: {changed}/{len(keys)} tensors mixed, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
