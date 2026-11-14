"""Build the demo answer cache that `/ask` serves when LEARGAS_DEMO_CACHE=1 (see app/demo_cache.py).

    .venv/bin/python backend/demo_cache.py                                  # in-process router
    .venv/bin/python backend/demo_cache.py --api http://127.0.0.1:8012      # through a running /ask
    .venv/bin/python backend/demo_cache.py --questions my_demo.jsonl --engines auto,geometry

Questions come from `--questions` (JSON list or JSONL of {path | drawing, question, engine?, answer?,
type?, expected?}), by default data/splits/demo_questions.jsonl from model/make_demo_set.py. If that file
is missing, a built-in set of Swiss DXF and IFC questions (counts and areas, en/de/it/fr/da) is used.

Each question is asked once per engine (a row's own `engine` overrides `--engines`) and the full Answer
JSON is stored under (normalized path, normalized question, engine). By default `cannot_verify` answers are
not stored, so a question the model could answer live is not pinned to an abstention; rows with
expected="cannot_verify" (deliberately unanswerable) are stored either way. An existing answered entry is
never replaced by a cannot_verify. Where the row has a gold answer, it is scored and the result printed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app import demo_cache
from app.drawings import REPO
from score import score_one

DEFAULT_QUESTIONS = REPO / "data" / "splits" / "demo_questions.jsonl"

SWISS_A = "data/swiss_dwellings/site2297_bldg3392_floor15123.pdf"
MOLIO = "data/ifc_models/bsc-molio_molio-with-uris_plan-"
FRIGENTO = "data/ifc_models/bimspeed-frigento-palazzo-testa-cipriano_plan-01-solaio-interrato.pdf"

# Fallback demo set: drawings the geometry engines answer with the gold value (checked against
# questions.jsonl). Swiss answers carry polygon evidence; IFC answers carry none yet.
DEFAULT_SET: List[Dict[str, Any]] = [
    {"path": SWISS_A, "question": "How many windows are drawn on this floor plan?",
     "answer": 12, "unit": "count", "type": "count"},
    {"path": SWISS_A, "question": ("Wie gross ist die gesamte Nettogeschossfläche in m² aller nummerierten Innenräume dieses Geschosses "
                         "(ohne Balkone, Loggien, Terrassen und andere Aussenräume, Schächte und Lufträume)?"),
     "answer": 314.29, "unit": "m2", "type": "area"},
    {"path": SWISS_A, "question": "Wie viele Wohnungen sind auf diesem Grundriss dargestellt?",
     "answer": 2, "unit": "count", "type": "count"},
    {"path": SWISS_A, "question": "How many rooms labelled 'Zimmer' are there on this floor?",
     "answer": 5, "unit": "count", "type": "count"},
    {"path": "data/swiss_dwellings/site10965_bldg15906_floor41165.pdf",
     "question": "What is the net floor area of room 1.09 ('Bad') in m²?", "answer": 8.79, "unit": "m2", "type": "area"},
    {"path": "data/swiss_dwellings/site1051_bldg2157_floor9751.pdf",
     "question": "Quelle est la surface nette de la pièce 4.10 (« Pièce ») en m² ?", "answer": 14.06, "unit": "m2", "type": "area"},
    {"path": "data/swiss_dwellings/site1054_bldg2164_floor9776.pdf",
     "question": "Quanti locali con la denominazione «Ripostiglio» ci sono in questo piano?",
     "answer": 1, "unit": "count", "type": "count"},
    {"path": MOLIO + "08-5-sal.pdf", "question": "Hvad er det samlede nettoareal af alle rum på '5. Sal' i m²?",
     "answer": 523.09, "unit": "m2", "type": "area"},
    {"path": MOLIO + "06-3-sal.pdf", "question": "Hvor mange søjler er vist på plantegningen for '3. Sal'?",
     "answer": 2, "unit": "count", "type": "count"},
    {"path": MOLIO + "02-klder.pdf", "question": "Hvad er nettoarealet af rummet 'Affald (Rum nr. K03)' på 'Kælder' i m²?",
     "answer": 17.61, "unit": "m2", "type": "area"},
]


def load_questions(path: Optional[Path]) -> List[Dict[str, Any]]:
    if path is None:
        if not DEFAULT_QUESTIONS.exists():
            print(f"{DEFAULT_QUESTIONS} not found; using the built-in demo set", file=sys.stderr)
            return [dict(r) for r in DEFAULT_SET]
        path = DEFAULT_QUESTIONS
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("["):
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    for r in rows:
        if "path" not in r and "drawing" in r:
            r["path"] = r["drawing"]
        if "path" not in r or "question" not in r:
            raise SystemExit(f"row needs path (or drawing) and question: {r}")
    return rows


def in_process() -> Callable[[dict], dict]:
    from app import router
    from app.schema import AskRequest

    def ask(body: dict) -> dict:
        return router.route(AskRequest(**body)).model_dump(mode="json")

    return ask


def over_http(api: str, timeout: float) -> Callable[[dict], dict]:
    import httpx

    client = httpx.Client(base_url=api, timeout=timeout)

    def ask(body: dict) -> dict:
        r = client.post("/ask", json=body)
        r.raise_for_status()
        if r.headers.get("x-leargas-cache") == "hit":
            print("  warning: the server answered from its demo cache; build against a live server",
                  file=sys.stderr)
        return r.json()

    return ask


def _gold(row: dict) -> Optional[dict]:
    if row.get("answer") is None or row.get("type") not in ("count", "area", "length", "volume", "text"):
        return None
    return {"answer": row["answer"], "unit": row.get("unit"), "type": row["type"]}


def build(rows: List[dict], ask: Callable[[dict], dict], out: Path, engines: List[str], *,
          keep_cannot_verify: bool = False, fresh: bool = False) -> Dict[str, Any]:
    data = {"version": demo_cache.VERSION, "entries": {}} if fresh else demo_cache.read(out)
    entries = data["entries"]
    stats = {"asked": 0, "stored": 0, "skipped": 0, "errors": 0, "correct": 0, "scored": 0}
    for row in rows:
        for engine in ([row["engine"]] if row.get("engine") else engines):
            body = {"path": row["path"], "question": row["question"], "engine": engine}
            stats["asked"] += 1
            try:
                a = ask(body)
            except Exception as e:
                stats["errors"] += 1
                print(f"  ERROR {engine:10s} {row['path']} :: {row['question'][:50]}: {e}", file=sys.stderr)
                continue
            k = demo_cache.key_str(demo_cache.make_key(row["path"], row["question"], engine))
            cv = a.get("status") == "cannot_verify"
            mark = ""
            if (g := _gold(row)) is not None:
                s = score_one(g, a)
                stats["scored"] += 1
                stats["correct"] += s["correct"]
                mark = "ok" if s["correct"] else s["outcome"]
            elif row.get("expected") == "cannot_verify":
                mark = "ok" if cv else "answered?"
            store = not cv or keep_cannot_verify or row.get("expected") == "cannot_verify"
            prev = entries.get(k)
            if cv and prev and prev["answer"].get("status") != "cannot_verify":
                store = False  # never downgrade an answered entry
            if store:
                entries[k] = {"path": row["path"], "question": row["question"], "engine": engine,
                              "id": row.get("id"), "cached_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "answer": a}
                stats["stored"] += 1
            else:
                stats["skipped"] += 1
            print(f"  {'stored ' if store else 'skipped'} {engine:10s} {a.get('status', '?'):13s} "
                  f"{str(a.get('answer'))[:14]:>14s} ev={len(a.get('evidence') or []):<3d} {mark:10s} "
                  f"{row['path'].rsplit('/', 1)[-1][:40]} :: {row['question'][:50]}")
    data["version"] = demo_cache.VERSION
    data["built_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    demo_cache.write(out, data)
    stats["total_entries"] = len(entries)
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", type=Path, help=f"JSON/JSONL demo questions (default {DEFAULT_QUESTIONS})")
    ap.add_argument("--default-set", action="store_true", help="use the built-in Swiss + IFC demo set")
    ap.add_argument("--api", help="POST /ask on this server (e.g. http://127.0.0.1:8012); default: in-process router")
    ap.add_argument("--out", type=Path, default=demo_cache.cache_path(),
                    help="cache file (default LEARGAS_DEMO_CACHE_PATH or data/demo_cache.json)")
    ap.add_argument("--engines", default="auto", help="comma list of engines to cache each question under")
    ap.add_argument("--keep-cannot-verify", action="store_true", help="also store cannot_verify answers")
    ap.add_argument("--fresh", action="store_true", help="start an empty cache instead of merging")
    ap.add_argument("--timeout", type=float, default=180.0)
    a = ap.parse_args(argv)

    rows = [dict(r) for r in DEFAULT_SET] if a.default_set else load_questions(a.questions)
    engines = [e.strip() for e in a.engines.split(",") if e.strip()]
    ask = over_http(a.api, a.timeout) if a.api else in_process()
    print(f"{len(rows)} questions x {engines} via {a.api or 'in-process router'} -> {a.out}")
    t0 = time.perf_counter()
    st = build(rows, ask, a.out, engines, keep_cannot_verify=a.keep_cannot_verify, fresh=a.fresh)
    print(f"asked {st['asked']}, stored {st['stored']}, skipped {st['skipped']} (cannot_verify), "
          f"errors {st['errors']}; gold-correct {st['correct']}/{st['scored']}; "
          f"{st['total_entries']} entries in {a.out} ({time.perf_counter() - t0:.1f}s)")
    return 1 if st["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
