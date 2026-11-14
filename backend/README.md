# backend

FastAPI app, answer schema and scorer.

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
LEARGAS_QUESTIONS=datasets/junction-dataset/questions.jsonl .venv/bin/uvicorn app.main:app --app-dir backend --reload
cd backend && ../.venv/bin/pytest -q
```

## Endpoints

- `POST /ask` `{path, question, type?, engine?}` → `Answer`. **Mock for now**: returns the gold answer with placeholder evidence if the question is in `LEARGAS_QUESTIONS`, otherwise `cannot_verify`.
- `GET /schema` — JSON Schema for the request and `Answer`.
- `GET /health`

## Temporary Gemma outages

`/health` keeps `ok: true` while the API is serving geometry and cached answers.
Its `gemma` boolean now means the fine-tuned model is reachable, rather than just
configured. `gemma_status` includes `status`, `available`, and per-model states
for `gemma-ft` and `gemma-base`: `available`, `unavailable`, `checking`, or
`unconfigured` (`disabled` in mock mode). Readiness is checked using authenticated
`GET <MODEL_BASE_URL>/models`, cached for 10 seconds, and rechecked automatically.
Inference failures put the affected model into the same cooldown. The UI polls
health every 15 seconds and shows which model is offline.

Auto still compares geometry with Gemma when the model responds promptly. Once
geometry has a valid answer, it waits at most one additional second for the
comparison, then returns geometry with its evidence and an explanation that
model confirmation was unavailable. Raster-only and explicit model requests have
a 15-second overall wait budget and return `cannot_verify` on failure, without
inventing an answer. The number of outstanding model jobs is bounded; additional
requests fall back instead of building an unbounded queue. Demo-cache hits still
return before any readiness check or model request.

Optional environment settings (seconds): `LEARGAS_GEMMA_CHECK_TIMEOUT=3`,
`LEARGAS_GEMMA_CHECK_INTERVAL=10`, `LEARGAS_GEMMA_COMPARE_WAIT=1`,
`LEARGAS_GEMMA_TIMEOUT=15`. The separately configured question-parser endpoint
also uses readiness/cooldown checks; local templates and rules run first and
continue working during outages. `LEARGAS_LLM_TIMEOUT` defaults to 5 seconds.

The model proxy probes its upstream model lists concurrently, so an offline
model does not delay readiness checks for all of the others. Restart the proxy
with the updated `infra/model_proxy.py` when bringing the Gemma server back up.

## Answer contract (`app/schema.py`, exported to `contracts/`)

- `path`, `question`, `answer`, `unit`, `type` match `questions.jsonl`, so API output can be scored directly.
- `status`: `verified` | `partial` | `disagreement` | `cannot_verify` (then `answer` is `null`).
- `source`: `geometry_dxf` | `geometry_ifc` | `gemma_ft` | `gemma_base` | `mock`. `sources[]` holds each engine's answer when the router ran more than one.
- `evidence[]`: `{shape, page, label?, value?, source?}`, where `shape` is one of
  `{"kind":"polygon","points":[[x,y],...]}`, `{"kind":"bbox","bbox":[x0,y0,x1,y1]}` or `{"kind":"point","point":[x,y]}`.
  Coordinates are **normalized 0–1 on the rendered image** (PNG, or PDF page `page`), with the origin at the top left and y pointing down.

Regenerate `contracts/` after schema changes: `cd backend && ../.venv/bin/python export_schema.py`.

## Region questions

`POST /ask` accepts an optional `region` in normalized coordinates on the sheet served by `/drawing`:

```json
{"path": "data/swiss_dwellings/floor.pdf", "question": "How many windows in this region?", "engine": "auto", "region": {"bbox": [0.2, 0.1, 0.8, 0.7], "page": 0}}
```

The answer echoes `region`. DXF counts include items whose polygon centers fall inside the box;
room area sums require complete rooms and refuse selections that cut through a relevant room.
Geometry must register confidently to the displayed sheet. IFC geometry currently has no 2D
registration, so region questions can use the raster model instead. The raster model receives only
the crop of the displayed image/PDF page, and its evidence points are mapped back onto the full sheet.
Whole-sheet demo-cache and mock gold answers are never used for region requests.

`GET /drawings` supports `limit` (up to 5000) and `offset`; `total` is the full catalogue count.

## Scorer

```bash
.venv/bin/python backend/score.py --gold questions.jsonl --pred preds.jsonl [--split heldout.txt] [--tol 0.02] [--json out.json]
```

- Counts must be exact. Area, length and volume must be within `--tol` (default **2%**, the dataset's official rule); accuracy at 1% is also reported. ft/ft²/ft³ are converted to metric.
- `text` answers are not in the headline number. A normalized exact match is reported separately.
- `cannot_verify` or a missing prediction counts as wrong. `coverage` is the share answered and `prec` is accuracy among answered.
- `--split` matches drawings by `data/<source>/<stem>`, so holding out a `.pdf` also holds out its `.dxf`/`.png` twin.
- Breaks results down by type, source and extension. Use `from score import score_one` to score in-process.

## End-to-end eval

```bash
.venv/bin/python backend/eval_run.py --gold datasets/junction-dataset/questions.jsonl --split heldout.txt --out runs/auto.jsonl
```

- Sends every gold question on the held-out drawings to `POST /ask` (`--api`, default `http://127.0.0.1:8000`, or `LEARGAS_API`) with `--concurrency` requests in flight (default 16), then prints the `score.py` report.
- `--engine auto|geometry|gemma_ft|gemma_base` picks the router path, so base vs fine-tuned is one flag.
- Answers are appended as they arrive, so `--resume` continues an interrupted run. Failed requests go to `<out>.errors.jsonl` and score as missing.
- `--types count,area` and `--limit N` are for smoke tests. The gold `type` is only sent with `--type-hint`.
- Scores and run stats (wall time, p50/p95 latency, errors) are written to `<out>.score.json`.

## Demo answer cache (`demo_cache.py`, `app/demo_cache.py`)

With `LEARGAS_DEMO_CACHE=1`, `/ask` first looks the request up in a cache of stored answers, so the demo still works when the Gemma endpoint is down. A hit returns the stored `Answer` unchanged, with the response header `X-Leargas-Cache: hit`. A miss (header `miss`) goes to the live router as usual. `/health` reports the cache path and its entry count.

```bash
# build it against a live backend (no cache enabled), or drop --api to run the router in-process
.venv/bin/python backend/demo_cache.py --api http://127.0.0.1:8012 --engines auto,geometry
# serve it
LEARGAS_DEMO_CACHE=1 .venv/bin/uvicorn app.main:app --app-dir backend --port 8012
```

- Questions come from `--questions` (a JSON list or JSONL of `{path | drawing, question, engine?}`). The default is `data/splits/demo_questions.jsonl` from `model/make_demo_set.py`. If that file is missing, or with `--default-set`, the tool uses 10 built-in Swiss and IFC count and area questions in five languages.
- Entries are keyed on (path, question, engine). Paths drop any prefix before `data/`, questions are NFKC, casefolded and whitespace-collapsed, and a missing engine counts as `auto`. Cache each engine the toggle can send (`--engines`).
- `cannot_verify` answers are not stored, so a cache built while Gemma was down doesn't pin those questions to an abstention. The exception is rows with `expected: "cannot_verify"`, the deliberately unanswerable ones. A rebuild merges into the existing file (unless you pass `--fresh`) and never replaces an answer with a `cannot_verify`.
- The file is `data/demo_cache.json` (gitignored) or `LEARGAS_DEMO_CACHE_PATH`. The server reloads it when it changes, so a rebuild needs no restart. Rows that have a gold answer are scored as they are cached.

## Question → query (`app/query/`)

`parse(question)` turns a question in any dataset language into a structured `Query`, for example `{op: count, target: window, scope: plan}`, which the DXF and IFC engines execute. It tries these in order:

1. **template**: an exact match in the multilingual template table. Confidence 0.99.
2. **rules**: keyword rules for English questions, which also cover paraphrases. Confidence 0.85.
3. **llm**: Gemma over an OpenAI-compatible endpoint. It only runs if `LEARGAS_LLM_BASE_URL` is set (`LEARGAS_LLM_MODEL` defaults to `gemma-base`). Confidence 0.7.
4. **none**: the caller should answer `cannot_verify`.

The template table is built from the dataset, so it is gitignored. Build it once per machine:

```bash
cd backend && ../.venv/bin/python -m app.query.build_templates --questions ../datasets/junction-dataset/questions.jsonl
../.venv/bin/python -m app.query.eval_parse --questions ../datasets/junction-dataset/questions.jsonl   # coverage report
```

On the full dataset, without the LLM, 100% of count, area, length and volume questions parse, except 24 bespoke `opening_design` schedule questions. Translations parse to the same query as their English original in every case. `POST /parse` is available as `app.query.api.router`, but it isn't mounted in `main.py` yet.

## IFC engine (`app/ifc.py`)

`answer(path, query)` resolves the IFC model and runs a parsed `Query`. The path can be a `.ifc` file or a plan rendered from one (`<model>_plan-NN-<level>.pdf`).

- **Counts:** element occurrences by IFC class, either for the whole model or for one storey. Nested parts are not counted; ArchiCAD, for example, exports stair risers as `IfcStair` parts.
- **Areas, lengths and volumes:** taken from the base quantity sets (`BaseQuantities` / `Qto_*`), with each value scaled by its own unit type. Where no quantity is stored, they are computed from geometry: space footprint area, or element volume.
- **Failures:** a missing storey, an ambiguous space name, or an element with no quantity raises `CannotVerify`. The engine never returns a partial sum.

```bash
.venv/bin/pip install -r backend/requirements-ifc.txt
cd backend && ../.venv/bin/python eval_ifc.py   # all IFC-backed gold questions: parser -> engine -> scorer
```

Current result: **3,062 of 3,062 `ifc_models` questions correct**, without the LLM. All `ifc_bench` questions are free text, which is the stretch task.
