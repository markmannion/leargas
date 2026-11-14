"""Prior vs base vs fine-tuned table (M4/M8/M12 "before/after"), from results/*.json.

  python -m model.report                    # prints markdown, writes results/table.md
  python -m model.report --set judge

Columns appear in this order when present: prior, gemma-base, gemma-e2b, gemma-26b, gemma-ft (run1), run2.
"""
from __future__ import annotations

import argparse
import json

from .baseline_eval import RESULTS

ORDER = ["prior", "gemma-e2b", "gemma-ft-e2b", "gemma-base", "gemma-ft", "gemma-ft-run2", "gemma-26b"]


def load_all() -> dict:
    merged: dict = {}
    for p in sorted(RESULTS.glob("*.json")):
        if p.name in ("sweep.json", "points.json", "sweep_demo.json") or p.name.startswith("calibration"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for model, sets in data.items():
            if model.startswith("_") or not isinstance(sets, dict):
                continue
            merged.setdefault(model, {}).update(sets)
    return merged


def table(set_name: str, metric: str = "acc") -> str:
    data = load_all()
    models = [m for m in ORDER if m in data and set_name in data[m]] + \
             sorted(m for m in data if m not in ORDER and set_name in data[m])
    if not models:
        return f"(no results for {set_name})"
    groups = sorted({g for m in models for g in data[m][set_name]["by_source_type"]}, key=lambda g: (g == "ALL", g))
    lines = [f"**{set_name}**: {metric} (n per row from the first model)", "",
             "| source / type | n | " + " | ".join(models) + " |",
             "|---|---:|" + "---:|" * len(models)]
    for g in groups:
        first = next(data[m][set_name]["by_source_type"].get(g) for m in models if g in data[m][set_name]["by_source_type"])
        cells = []
        vals = []
        for m in models:
            v = data[m][set_name]["by_source_type"].get(g, {}).get(metric)
            vals.append(v)
            cells.append("–" if v is None else f"{100 * v:.1f}%")
        best = max((v for v in vals if v is not None), default=None)
        cells = [f"**{c}**" if v is not None and v == best and len(models) > 1 else c for c, v in zip(cells, vals)]
        lines.append(f"| {'**ALL**' if g == 'ALL' else g} | {first['n']} | " + " | ".join(cells) + " |")
    lat = [data[m][set_name].get("median_latency_ms") for m in models]
    if any(lat):
        lines.append("| median latency | | " + " | ".join("–" if x is None else f"{x / 1000:.1f}s" for x in lat) + " |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=None)
    a = ap.parse_args()
    sets = [a.set] if a.set else ["heldout_raster", "judge", "heldout_all_prior"]
    md = "\n\n".join(table(s) for s in sets)
    print(md)
    (RESULTS / "table.md").write_text(md + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
