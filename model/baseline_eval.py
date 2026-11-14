"""M4 (and M8, M12): score the prior baseline and any served Gemma on the held-out split.

  python -m model.baseline_eval --models prior                       # runs offline, now
  python -m model.baseline_eval --models prior,gemma-base            # once the box is up (M4)
  python -m model.baseline_eval --models gemma-ft --out results/run1.json   # M8
  python -m model.baseline_eval --models gemma-ft --label gemma-ft-run2 --points   # M12: run 2 is ALSO served as
      # gemma-ft, so it needs its own label or it reuses run 1's cached predictions
  python -m model.report                                             # prior vs base vs ft table

Question sets
- "heldout_raster": a fixed, stratified ~1,000-question sample of held-out CubiCasa + swiss
  questions (data/splits/raster_eval.jsonl, created on first run, seed 7). Everyone uses the
  same file: baselines, run 1/2, the model sweep and Harry's run_eval --sources.
- "heldout_all_prior": the prior on EVERY held-out question (free, so no sampling).
- "judge": data/splits/judge_questions.jsonl, if present.

The prior: for each question, the most common training answer for the exact same question text
(templates in this dataset are exact strings per language), backing off to the digit-normalised
template, then to (source, type, unit). Counts use the mode; areas/lengths/volumes use the median.

Model predictions are cached in results/preds/<model>__<set>.jsonl, so a crashed run resumes.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .common import (
    REPO_ROOT,
    SPLITS_DIR,
    abs_path,
    guess_lang,
    is_heldout,
    load_jsonl,
    load_questions,
    prints_areas,
    source_of,
    template_of,
    write_jsonl,
)
from .scoring import score, summarize

RESULTS = REPO_ROOT / "results"
RASTER_EVAL = SPLITS_DIR / "raster_eval.jsonl"
JUDGE = SPLITS_DIR / "judge_questions.jsonl"


def raster_image_path(path: str) -> str:
    """Question path -> the image the raster model sees (swiss PDF -> PNG twin)."""
    return path[:-4] + ".png" if path.endswith(".pdf") and "/swiss_dwellings/" in path else path


# --------------------------------------------------------------------------- eval sets

def make_raster_eval(questions: list[dict], n: int = 1000, seed: int = 7) -> list[dict]:
    """Stratified by (source, question template). CubiCasa gets ~60%, swiss ~40%; per template,
    at most 2 questions per drawing so a few drawings can't dominate."""
    ho = [q for q in questions if is_heldout(q["path"]) and source_of(q["path"]) in ("cubicasa5k", "swiss_dwellings")]
    rng = random.Random(seed)
    share = {"cubicasa5k": 0.6, "swiss_dwellings": 0.4}
    out = []
    for src, frac in share.items():
        pool = [q for q in ho if source_of(q["path"]) == src]
        by_t = collections.defaultdict(list)
        for q in pool:
            by_t[template_of(q["question"]) if src == "cubicasa5k" else _swiss_family(q)].append(q)
        target = round(n * frac)
        keys = sorted(by_t)
        per = max(1, target // len(keys))
        picked = []
        for k in keys:
            items = by_t[k][:]
            rng.shuffle(items)
            picked.extend(items[:per])
        rest = [q for q in pool if q not in picked]
        rng.shuffle(rest)
        picked.extend(rest[: max(0, target - len(picked))])
        out.extend(picked[:target])
    for i, q in enumerate(out):
        q = dict(q)
        out[i] = {"id": f"re_{i:04d}", **q, "source": source_of(q["path"]), "lang": guess_lang(q["question"]),
                  "image": raster_image_path(q["path"])}
    return out


def _swiss_family(q: dict) -> str:
    """Swiss templates collapse room names / numbers / languages into a few families."""
    s = q["question"].lower()
    for fam, keys in [
        ("apartments", ("apartment", "wohnung", "appartement", "appartament")),
        ("doors", ("door", "tür", "porte", "porta", "porte")),
        ("windows", ("window", "fenster", "fenêtre", "finestr")),
        ("toilets", ("toilet", "wc")),
        ("basins", ("washbasin", "lavabo", "lavabi")),
        ("baths", ("bathtub", "badewanne", "baignoire", "vasch")),
        ("showers", ("shower", "dusche", "douche", "docc")),
    ]:
        if any(k in s for k in keys) and q["type"] == "count" and "label" not in s and "bezeichnung" not in s \
                and "dénomination" not in s and "denominazione" not in s:
            return f"count_{fam}"
    if q["type"] == "count":
        return "count_rooms_by_label"
    printed = "printed" if prints_areas(q["path"]) else "unprinted"
    if "room" in s or "raum" in s or "pièce" in s or "local" in s:
        return f"area_room_{printed}"
    return f"area_total_or_unit_{printed}"


def load_set(name: str, questions: list[dict]) -> list[dict]:
    if name == "heldout_raster":
        if not RASTER_EVAL.exists():
            write_jsonl(RASTER_EVAL, make_raster_eval(questions))
            print(f"wrote {RASTER_EVAL}")
        return load_jsonl(RASTER_EVAL)
    if name == "heldout_all_prior":
        return [{"id": f"ho_{i:05d}", **q, "source": source_of(q["path"]), "lang": guess_lang(q["question"]),
                 "image": raster_image_path(q["path"])} for i, q in enumerate(q for q in questions if is_heldout(q["path"]))]
    if name == "judge":
        if not JUDGE.exists():
            return []
        rows = load_jsonl(JUDGE)
        for r in rows:
            r.setdefault("image", raster_image_path(r["path"]))
            r.setdefault("source", source_of(r["path"]))
        return rows
    raise ValueError(name)


# --------------------------------------------------------------------------- prior

class Prior:
    def __init__(self, questions: list[dict]):
        train = [q for q in questions if not is_heldout(q["path"])]
        self.by_q = self._fit(train, lambda q: q["question"])
        self.by_t = self._fit(train, lambda q: template_of(q["question"]))
        self.by_st = self._fit(train, lambda q: (source_of(q["path"]), q["type"], q["unit"]))

    @staticmethod
    def _fit(rows, key):
        vals = collections.defaultdict(list)
        units = {}
        for q in rows:
            if q["type"] == "text":
                continue
            vals[key(q)].append(q["answer"])
            units[key(q)] = q["unit"]
        out = {}
        for k, v in vals.items():
            nums = [x for x in v if isinstance(x, (int, float))]
            if not nums:
                continue
            if all(isinstance(x, int) for x in nums):
                ans = collections.Counter(nums).most_common(1)[0][0]
            else:
                ans = round(statistics.median(nums), 2)
            out[k] = (ans, units[k], len(nums))
        return out

    def predict(self, q: dict):
        for table, k in ((self.by_q, q["question"]), (self.by_t, template_of(q["question"])),
                         (self.by_st, (source_of(q["path"]), q.get("type"), q.get("unit")))):
            if k in table:
                return {"answer": table[k][0], "unit": table[k][1], "abstained": False, "confidence": None}
        return {"answer": None, "unit": None, "abstained": True, "confidence": None}


# --------------------------------------------------------------------------- model runs

def run_model(model: str, rows: list[dict], set_name: str, workers: int, with_points: bool = False,
              label: str | None = None, crop_swiss: bool = False) -> list[dict]:
    """label names the cache file (default: the model). Run 1 and run 2 are both served as gemma-ft, so
    run 2 MUST pass a label, or it would silently reuse run 1's cached predictions."""
    from .client import ask  # only needed for model runs

    cache_path = RESULTS / "preds" / f"{label or model}__{set_name}.jsonl"
    done = {r["id"]: r for r in load_jsonl(cache_path)} if cache_path.exists() else {}
    todo = [r for r in rows if r["id"] not in done]
    print(f"{model} on {set_name}: {len(done)} cached, {len(todo)} to run")
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    def one(r):
        img = abs_path(r["image"])
        if not Path(img).exists() or not str(img).lower().endswith((".png", ".jpg", ".jpeg")):
            return {"id": r["id"], "answer": None, "unit": None, "abstained": True, "confidence": None,
                    "error": f"no raster image for {r['image']}", "latency_ms": 0}
        box = None
        if crop_swiss and r.get("source") == "swiss_dwellings":
            from .crop import cropped  # plan-only image; points are mapped back to the sheet below
            img, box = cropped(r["image"])
        for attempt in range(3):
            try:
                out = ask(img, r["question"], model=model, with_points=with_points)
                if box is not None and out.get("points"):
                    from .crop import crop_to_sheet
                    out["points"] = [crop_to_sheet(p, box) for p in out["points"]]
                return {"id": r["id"], **{k: out[k] for k in ("answer", "unit", "points", "confidence", "abstained", "raw", "latency_ms")},
                        "completion_tokens": out["usage"].get("completion_tokens"), "prompt_tokens": out["usage"].get("prompt_tokens")}
            except Exception as e:  # noqa: BLE001
                err = str(e)
                time.sleep(2 * (attempt + 1))
        return {"id": r["id"], "answer": None, "unit": None, "abstained": True, "confidence": None, "error": err, "latency_ms": 0}

    t0 = time.time()
    with open(cache_path, "a", encoding="utf-8") as f, ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(one, r) for r in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            p = fut.result()
            done[p["id"]] = p
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
            f.flush()
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}  {i / (time.time() - t0):.2f} q/s")
    wall = time.time() - t0
    if todo:
        print(f"  throughput {len(todo) / wall:.2f} q/s with {workers} workers")
    return [done[r["id"]] for r in rows]


def score_rows(rows: list[dict], preds: list[dict]) -> list[dict]:
    out = []
    for r, p in zip(rows, preds):
        if r.get("expected") == "cannot_verify":  # judge/demo "should abstain" items
            outcome = "correct" if p.get("abstained") or p.get("answer") is None else "wrong"
        else:
            outcome = score(p.get("answer"), p.get("unit"), r, abstained=bool(p.get("abstained")))
        typ = r.get("type")
        if r["source"] == "swiss_dwellings" and typ == "area":  # split: is the m² printed on the drawing?
            typ = "area_printed" if prints_areas(r["path"]) else "area_unprinted"
        out.append({"id": r["id"], "source": r["source"], "type": typ, "lang": r.get("lang"),
                    "outcome": outcome, "confidence": p.get("confidence")})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="prior", help="comma list: prior, gemma-base, gemma-ft, gemma-e2b, ...")
    ap.add_argument("--sets", default="heldout_raster,judge")
    ap.add_argument("--out", default=None, help="default results/baseline.json (prior/base) or results/<model>.json")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0, help="first N questions per set (smoke runs)")
    ap.add_argument("--points", action="store_true", help="ask for points (run 2 models)")
    ap.add_argument("--crop-swiss", action="store_true",
                    help="show the model swiss sheets cropped to the plan (model/crop.py); cache/report label gets -crop")
    ap.add_argument("--sources", default="", help="comma list to restrict sets, e.g. swiss_dwellings (quick experiments)")
    ap.add_argument("--label", default=None,
                    help="results/cache name when a served name is reused: --models gemma-ft --label gemma-ft-run2")
    a = ap.parse_args()

    questions = load_questions()
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    if a.label and (len(models) != 1 or models[0] == "prior"):
        raise SystemExit("--label needs exactly one served model in --models")
    def label_for(m: str) -> str | None:
        if a.crop_swiss and m != "prior":
            return a.label if a.label and "crop" in a.label else f"{a.label or m}-crop"
        return a.label
    plain = set(models) <= {"prior", "gemma-base"} and not a.crop_swiss
    out_path = Path(a.out) if a.out else RESULTS / ("baseline.json" if plain else f"{label_for(models[-1]) or models[-1]}.json")
    report = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    prior = Prior(questions) if "prior" in models else None

    sets = [s.strip() for s in a.sets.split(",") if s.strip()]
    if "prior" in models and "heldout_all_prior" not in sets:
        sets.append("heldout_all_prior")
    for set_name in sets:
        rows = load_set(set_name, questions)
        if a.sources:
            rows = [r for r in rows if r.get("source") in a.sources.split(",")]
        if a.limit:
            rows = rows[: a.limit]
        if not rows:
            print(f"skip {set_name}: empty")
            continue
        for m in models:
            if set_name == "heldout_all_prior" and m != "prior":
                continue
            if m == "prior":
                preds = [prior.predict(r) for r in rows]
            else:
                preds = run_model(m, rows, set_name, a.workers, a.points, label=label_for(m), crop_swiss=a.crop_swiss)
            scored = score_rows(rows, preds)
            summ = summarize(scored)
            lat = [p.get("latency_ms") for p in preds if p.get("latency_ms")]
            report.setdefault((label_for(m) if m != "prior" else None) or m, {})[set_name] = {
                "n": len(rows),
                "by_source_type": summ,
                "by_lang": summarize(scored, key=lambda r: f"lang/{r['lang']}"),
                "median_latency_ms": statistics.median(lat) if lat else None,
            }
            print(f"\n== {m} on {set_name} (n={len(rows)})")
            for k, v in summ.items():
                print(f"  {k:28s} n={v['n']:5d} acc={v['acc']}  answered-acc={v['acc_answered']}  abstain={v['abstain_rate']}")

    report["_meta"] = {"generated": time.strftime("%Y-%m-%d %H:%M"), "scorer": "harry" if score.__module__ and _uses_harry() else "local"}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path}")


def _uses_harry() -> bool:
    from . import scoring
    return scoring._HARRY is not None


if __name__ == "__main__":
    main()
