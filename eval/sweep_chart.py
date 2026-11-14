"""M11b: the model sweep chart. Accuracy against $ per 1,000 questions, one dot per Gemma model.

  python eval/sweep_chart.py                      # -> results/sweep.json + results/sweep.svg
  python eval/sweep_chart.py --demo               # fake numbers, to check the layout before the sweep

Accuracy comes from Harry's results/e2e_<model>.json when present (key path: by_source_type.ALL.acc,
or a top-level "acc"), else Mark's results/<model>.json / results/baseline.json (heldout_raster, ALL).
Cost comes from results/throughput.json (model/throughput.py).

Pure stdlib: writes a standalone SVG (light surface, slide-ready), plus <title> hover tooltips per dot.
Fine-tuned models are blue (slot 1); base models are orange (slot 2). Every dot is direct-labelled.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"
LABELS = {
    "gemma-ft": "Gemma 4 E4B fine-tuned",
    "gemma-ft-run2": "E4B fine-tuned (run 2)",
    "gemma-base": "Gemma 4 E4B base",
    "gemma-e2b": "Gemma 4 E2B base",
    "gemma-ft-e2b": "Gemma 4 E2B fine-tuned",
    "gemma-26b": "Gemma 4 26B A4B base",
}
FT_COLOR, BASE_COLOR = "#2a78d6", "#eb6834"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0", "#fcfcfb"


def accuracy(model: str, set_name: str) -> float | None:
    for p in (RESULTS / f"e2e_{model}.json", RESULTS / f"{model}.json", RESULTS / "baseline.json"):
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if "acc" in d and isinstance(d["acc"], (int, float)):
            return d["acc"]
        node = d.get(model, d)
        node = node.get(set_name, node) if isinstance(node, dict) else None
        try:
            return node["by_source_type"]["ALL"]["acc"]
        except (KeyError, TypeError):
            continue
    return None


def collect(set_name: str) -> list[dict]:
    tp_path = RESULTS / "throughput.json"
    tp = json.loads(tp_path.read_text(encoding="utf-8")) if tp_path.exists() else {}
    pts = []
    for model, rec in tp.items():
        acc = accuracy(model, set_name)
        if acc is None:
            print(f"skip {model}: no accuracy for {set_name}")
            continue
        pts.append({"model": model, "label": LABELS.get(model, model), "acc": acc, "usd_per_1k": rec["usd_per_1k"],
                    "qps": rec.get("qps"), "gpu": rec.get("gpu"), "fine_tuned": model.startswith("gemma-ft")})
    return pts


def nice_max(x: float) -> float:
    if x <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 2.5, 5, 10):
        if x <= m * e:
            return m * e
    return 10 * e


def svg(points: list[dict], title: str, subtitle: str) -> str:
    W, H = 880, 520
    L, R, T, B = 80, 40, 92, 64
    pw, ph = W - L - R, H - T - B
    xmax = nice_max(max(p["usd_per_1k"] for p in points) * 1.15)
    x = lambda v: L + v / xmax * pw  # noqa: E731
    y = lambda v: T + (1 - v) * ph  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           f'font-family="Inter, Segoe UI, Helvetica, Arial, sans-serif" role="img" aria-label="{title}">',
           f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
           f'<text x="{L}" y="36" font-size="20" font-weight="600" fill="{INK}">{title}</text>',
           f'<text x="{L}" y="60" font-size="13" fill="{INK2}">{subtitle}</text>']
    for i in range(0, 6):  # y grid every 20%
        v = i / 5
        out.append(f'<line x1="{L}" x2="{L + pw}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{L - 10}" y="{y(v) + 4:.1f}" font-size="12" fill="{MUTED}" text-anchor="end">{int(v * 100)}%</text>')
    for i in range(0, 6):
        v = xmax * i / 5
        out.append(f'<text x="{x(v):.1f}" y="{T + ph + 22}" font-size="12" fill="{MUTED}" text-anchor="middle">${v:.2f}</text>')
    out.append(f'<line x1="{L}" x2="{L + pw}" y1="{T + ph}" y2="{T + ph}" stroke="{MUTED}" stroke-width="1"/>')
    out.append(f'<text x="{L + pw / 2}" y="{H - 16}" font-size="13" fill="{INK2}" text-anchor="middle">'
               f'$ per 1,000 questions (measured throughput × Verda $/h)</text>')
    out.append(f'<text x="22" y="{T + ph / 2}" font-size="13" fill="{INK2}" text-anchor="middle" '
               f'transform="rotate(-90 22 {T + ph / 2})">Accuracy on held-out raster questions</text>')
    prior = accuracy("prior", "heldout_raster")
    if prior is not None:  # reference line: "always answer the most common training answer"
        out.append(f'<line x1="{L}" x2="{L + pw}" y1="{y(prior):.1f}" y2="{y(prior):.1f}" stroke="{MUTED}" '
                   f'stroke-width="1.5" stroke-dasharray="5 4"/>')
        out.append(f'<text x="{L + pw}" y="{y(prior) + 17:.1f}" font-size="12" fill="{INK2}" text-anchor="end">'
                   f'prior baseline (most common answer): {prior * 100:.0f}%</text>')
    labels = []
    for p in points:
        cx, cy = x(p["usd_per_1k"]), y(p["acc"])
        anchor, dx = ("end", -14) if cx > L + pw * 0.75 else ("start", 14)
        labels.append({"p": p, "cx": cx, "cy": cy, "anchor": anchor, "lx": cx + dx, "ly": cy - 2})
    labels.sort(key=lambda d: d["ly"])  # nudge overlapping labels apart (2 lines = ~34 px tall)
    for i, d in enumerate(labels):
        for e in labels[:i]:
            if abs(d["lx"] - e["lx"]) < 220 and d["ly"] - e["ly"] < 36:
                d["ly"] = e["ly"] + 36
    for d in sorted(labels, key=lambda d: d["p"]["fine_tuned"]):  # fine-tuned drawn last (on top)
        p, cx, cy, anchor = d["p"], d["cx"], d["cy"], d["anchor"]
        c = FT_COLOR if p["fine_tuned"] else BASE_COLOR
        out.append(f'<g><title>{p["label"]}: {p["acc"] * 100:.1f}% at ${p["usd_per_1k"]:.3f} per 1k '
                   f'({p.get("qps") or "?"} q/s on {p.get("gpu") or "?"})</title>'
                   f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="16" fill="transparent"/>'
                   f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="7" fill="{c}" stroke="{SURFACE}" stroke-width="2"/></g>')
        out.append(f'<text x="{d["lx"]:.1f}" y="{d["ly"]:.1f}" font-size="13" font-weight="600" fill="{INK}" text-anchor="{anchor}">{p["label"]}</text>')
        out.append(f'<text x="{d["lx"]:.1f}" y="{d["ly"] + 16:.1f}" font-size="12" fill="{INK2}" text-anchor="{anchor}">'
                   f'{p["acc"] * 100:.1f}% · ${p["usd_per_1k"]:.3f}/1k</text>')
    # legend (2 series)
    lx = L + pw - 250
    out.append(f'<circle cx="{lx}" cy="{T - 16}" r="6" fill="{FT_COLOR}"/><text x="{lx + 12}" y="{T - 12}" font-size="12" fill="{INK2}">fine-tuned</text>')
    out.append(f'<circle cx="{lx + 100}" cy="{T - 16}" r="6" fill="{BASE_COLOR}"/><text x="{lx + 112}" y="{T - 12}" font-size="12" fill="{INK2}">base (no fine-tune)</text>')
    out.append("</svg>")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="heldout_raster")
    ap.add_argument("--demo", action="store_true", help="placeholder numbers to preview the layout")
    a = ap.parse_args()
    if a.demo:
        pts = [
            {"model": "gemma-e2b", "label": LABELS["gemma-e2b"], "acc": 0.31, "usd_per_1k": 0.12, "fine_tuned": False},
            {"model": "gemma-base", "label": LABELS["gemma-base"], "acc": 0.38, "usd_per_1k": 0.19, "fine_tuned": False},
            {"model": "gemma-26b", "label": LABELS["gemma-26b"], "acc": 0.47, "usd_per_1k": 0.61, "fine_tuned": False},
            {"model": "gemma-ft", "label": LABELS["gemma-ft"], "acc": 0.71, "usd_per_1k": 0.19, "fine_tuned": True},
        ]
        name = "sweep_demo"
    else:
        pts = collect(a.set)
        name = "sweep"
        if not pts:
            raise SystemExit("no models with both accuracy and throughput yet")
    title = "A small fine-tuned Gemma beats bigger base models for less" if not a.demo else "DEMO LAYOUT: placeholder numbers"
    sub = f"{len(pts)} Gemma 4 models · same questions, prompt and image budget · Verda GPUs, EU"
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{name}.svg").write_text(svg(pts, title, sub), encoding="utf-8")
    (RESULTS / f"{name}.json").write_text(json.dumps(pts, indent=2) + "\n", encoding="utf-8")
    print(f"wrote results/{name}.svg and results/{name}.json")
    for p in pts:
        print(f"  {p['label']:28s} acc {p['acc'] * 100:5.1f}%   ${p['usd_per_1k']:.4f}/1k")


if __name__ == "__main__":
    main()
