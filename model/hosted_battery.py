"""Judge-style battery against the HOSTED app: unknown files, mixed formats, known answers.

Judges upload their own PNGs, PDFs and JPGs. This re-creates that with answers we can score:
  A. held-out dataset drawings (never trained on), renamed to random ids so no DXF/IFC twin or
     dataset path rule can be found, each as png / jpg / pdf / phone-photo jpg, asked their gold
     questions;
  B. Stoa's 4 example sheets as pdf / jpg / photo / 3000 px png, asked reworded questions whose
     answers were checked by hand on Saturday (HANDOFF.md);
  C. the 30-question judge set, asked by dataset path.
Files go to a hidden folder on the box (data/battery/, not listed in the catalogue), so judges never
see them; `--clean` removes it.

    python -m model.hosted_battery build  --n-cc 24 --n-swiss 16     # writes files to scratch + manifest
    (scp the folder to the box, see the printed command)
    python -m model.hosted_battery run    --base https://<host>      # asks everything, writes results
    python -m model.hosted_battery report
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import json
import random
import statistics
import time
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

from .baseline_eval import JUDGE, RASTER_EVAL
from .common import REPO_ROOT, abs_path, load_jsonl
from .robustness import photo
from .scoring import score

Image.MAX_IMAGE_PIXELS = None
OUT = REPO_ROOT / "results" / "battery"
STOA = REPO_ROOT / "tricky_questions"

# Stoa sheets: question wordings a judge might use, with the values checked on Saturday.
# tol is relative. "checked": False marks values the sheet reader produced that nobody verified by hand.
STOA_QS = {
    "us_daf_dorm_sd_drawings_april_2026_p003.png": [
        ("What is the total gross area of the dorm in square feet?", 26562, "ft2", True),
        ("Total building area (SF)?", 26562, "ft2", True),
        ("How many dorm rooms are there?", 144, "count", True),
        ("How many dorm rooms are on the second floor?", 48, "count", True),
        ("What's the circulation area of the west wing?", 914, "ft2", True),
    ],
    "us_aw_078-24-28_march_2020_p096.png": [
        ("How many FP tags are on this piping plan?", 5, "count", True),
        ("How many control valves (CV) are shown?", 5, "count", True),
        ("What size is the suction header?", 16, "in", True),
    ],
    "us_aw_078-24-33_p056.png": [
        ("How long is the motor control center trench?", 4275, "mm", True),
        ("What is the overall length of the building in mm?", 27000, "mm", True),
    ],
    "uk_dfe_sen-dfe-xx-00-d-x-0201-special_school_plan_level_00-a-c01_p001.png": [
        ("What is the area of the hall in m2?", 247, "m2", False),
        ("How big is the library?", 26.8, "m2", False),
        ("How many group rooms are there?", 10, "count", False),
    ],
}


def _variants(im: Image.Image, big: bool) -> dict[str, tuple[Image.Image, str]]:
    im = im.convert("RGB")
    out = {"jpg": (im, "jpg"), "pdf": (im, "pdf"), "photo": (photo(im, random.Random(1)), "jpg")}
    if big:
        f = 3000 / max(im.size)
        out["png3000"] = (im.resize((int(im.width * f), int(im.height * f)), Image.LANCZOS), "png")
    else:
        out["png"] = (im, "png")
    return out


def _save(im: Image.Image, ext: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if ext == "jpg":
        im.save(dst, "JPEG", quality=85)
    elif ext == "pdf":
        im.save(dst, "PDF", resolution=150.0)
    else:
        im.save(dst, "PNG")


def build(a) -> None:
    stage = Path(a.stage).expanduser()
    rows = load_jsonl(RASTER_EVAL)
    by_img = collections.defaultdict(list)
    for r in rows:
        by_img[r["image"]].append(r)
    rng = random.Random(11)
    picks = []
    for src, n in (("cubicasa5k", a.n_cc), ("swiss_dwellings", a.n_swiss)):
        imgs = sorted(i for i in by_img if f"/{src}/" in i)
        picks += rng.sample(imgs, n)
    manifest = []
    for img in picks:
        im = Image.open(abs_path(img))
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            im = Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im)
        for var, (vim, ext) in _variants(im, big=False).items():
            rel = f"data/battery/{uuid.uuid4().hex[:12]}.{ext}"
            _save(vim, ext, stage / rel)
            manifest.append({"part": "A", "path": rel, "orig": img, "variant": var,
                             "questions": [{k: q[k] for k in ("id", "question", "answer", "unit", "type", "source")}
                                           for q in by_img[img]]})
    for name, qs in STOA_QS.items():
        im = Image.open(STOA / name)
        for var, (vim, ext) in _variants(im, big=True).items():
            rel = f"data/battery/{uuid.uuid4().hex[:12]}.{ext}"
            _save(vim, ext, stage / rel)
            manifest.append({"part": "B", "path": rel, "orig": name, "variant": var,
                             "questions": [{"question": q, "answer": v, "unit": u, "type": "count" if u == "count" else "measure",
                                            "checked": c, "source": "stoa"} for q, v, u, c in qs]})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    n_q = sum(len(m["questions"]) for m in manifest)
    print(f"{len(manifest)} files, {n_q} questions -> {stage}/data/battery")
    print(f"copy: scp -r {stage}/data/battery bt:leargas-data/junction-dataset/data/")


def _ask(base: str, path: str, question: str) -> dict:
    body = json.dumps({"path": path, "question": question}).encode()
    req = urllib.request.Request(f"{base}/ask", body, {"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            d = json.load(r)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200], "wall_s": time.perf_counter() - t0}
    d["wall_s"] = time.perf_counter() - t0
    return d


def _stoa_ok(ans, gold: float, tol: float = 0.02) -> bool:
    import re  # noqa: PLC0415
    m = re.search(r"-?\d[\d,]*\.?\d*", str(ans)) if ans is not None else None  # 16" / "26,562 SF"
    if not m:
        return False
    v = float(m.group().replace(",", ""))
    # unit slips (m vs mm, SF vs m2) are not the point here: accept the value in any common scale
    return any(abs(v * k - gold) <= tol * abs(gold) for k in (1, 1000, 0.001, 304.8, 10.7639, 1 / 10.7639))


def run(a) -> None:
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    jobs = [(m, q) for m in manifest for q in m["questions"]]
    for r in load_jsonl(JUDGE):  # part C: by dataset path
        jobs.append(({"part": "C", "path": r["path"], "orig": r["path"], "variant": "dataset"}, r))
    # Stoa first, one at a time per file, so each big sheet's OCR runs once and warms the cache
    first = {}
    for m, q in jobs:
        if m["part"] == "B" and m["path"] not in first:
            first[m["path"]] = (m, q)
    out = []

    def one(job):
        m, q = job
        d = _ask(a.base, m["path"], q["question"])
        if m["part"] == "B":
            ok = _stoa_ok(d.get("answer"), q["answer"])
        else:
            gold = {**q, "expected": q.get("expected")}
            ok = score(d.get("answer"), d.get("unit"), gold, abstained=d.get("status") == "cannot_verify") == "correct"
        return {"part": m["part"], "variant": m["variant"], "orig": m["orig"], "path": m["path"],
                "source_set": q.get("source"), "question": q["question"], "gold": q.get("answer"),
                "checked": q.get("checked", True), "answer": d.get("answer"), "unit": d.get("unit"),
                "status": d.get("status"), "engine": d.get("source"), "confidence": d.get("confidence"),
                "correct": ok, "wall_s": round(d["wall_s"], 2), "error": d.get("error")}

    with cf.ThreadPoolExecutor(4) as ex:  # warm the big sheets (OCR) 4 at a time
        out += list(ex.map(one, first.values()))
    rest = [j for j in jobs if (j[0]["path"], j[1]["question"]) not in {(m["path"], q["question"]) for m, q in first.values()}]
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for i, r in enumerate(ex.map(one, rest), 1):
            out.append(r)
            if i % 100 == 0:
                print(f"  {i}/{len(rest)}", flush=True)
    with open(OUT / "results.jsonl", "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(out)} answers -> {OUT / 'results.jsonl'}")
    report(a)


def report(a) -> None:
    rows = load_jsonl(OUT / "results.jsonl")

    def line(name, rs):
        n = len(rs)
        acc = sum(r["correct"] for r in rs) / n
        ver = [r for r in rs if r["status"] == "verified"]
        cv = sum(r["status"] == "cannot_verify" for r in rs) / n
        err = sum(bool(r["error"]) for r in rs)
        prec = f"{100 * sum(r['correct'] for r in ver) / len(ver):5.1f}%" if ver else "   –  "
        eng = collections.Counter(r["engine"] for r in rs).most_common(2)
        print(f"  {name:34s} n={n:4d}  acc={100 * acc:5.1f}%  verified={len(ver):3d} prec={prec}  "
              f"cannot_verify={100 * cv:4.1f}%  med={statistics.median(r['wall_s'] for r in rs):5.1f}s  "
              f"err={err}  {eng}")

    for part, title in (("A", "A. held-out dataset drawings as unknown uploads"), ("B", "B. Stoa sheets, reworded"),
                        ("C", "C. judge set by dataset path")):
        rs = [r for r in rows if r["part"] == part]
        if not rs:
            continue
        print(title)
        line("ALL", rs)
        for key in sorted({r["variant"] for r in rs}):
            line(f"variant={key}", [r for r in rs if r["variant"] == key])
        if part == "A":
            for s in sorted({r["source_set"] for r in rs}):
                line(f"source={s}", [r for r in rs if r["source_set"] == s])
        if part == "B":
            for o in sorted({r["orig"] for r in rs}):
                line(o[:34], [r for r in rs if r["orig"] == o])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "report"])
    ap.add_argument("--stage", default=str(REPO_ROOT / "results" / "battery" / "stage"))
    ap.add_argument("--n-cc", type=int, default=24)
    ap.add_argument("--n-swiss", type=int, default=16)
    ap.add_argument("--base", default="")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    {"build": build, "run": run, "report": report}[a.cmd](a)


if __name__ == "__main__":
    main()
