# Léargas backend

The FastAPI app that answers questions about drawings: the question parser, the router, the geometry engines
(DXF and IFC), the sheet reader, uploads, voice, the answer format and the scorer.

```bash
pip install -r requirements.txt -r requirements-dxf.txt -r requirements-ifc.txt -r requirements-sheet.txt
python -m app.query.build_templates --questions ../datasets/junction-dataset/questions.jsonl   # once per machine
uvicorn app.main:app --app-dir . --port 8000 --reload
pytest -q
```

| Path | What |
|---|---|
| `app/main.py` | Endpoints |
| `app/router.py` | Picks the engines for a drawing and reconciles their answers |
| `app/query/` | Question → structured query (templates, rules, LLM) |
| `app/dxf.py`, `app/openings.py`, `app/floor_areas.py` | DXF geometry (layer rules in `DXF.md`) |
| `app/ifc.py`, `app/slab_ifc.py`, `app/slabs.py` | IFC geometry and slab takeoffs |
| `app/sheet/` | The sheet reader for large sheets: text, scale, rooms, openings, slabs |
| `app/register.py` | Lines DXF shapes up with the PNG/PDF sheet |
| `app/uploads.py`, `app/upload_groups.py` | Uploads |
| `app/schema.py` | The answer format (exported to `../contracts/`) |
| `score.py`, `eval_run.py` | Scoring and end-to-end evaluation |

## Routing (`app/router.py`)

1. **Geometry first.** A drawing with a DXF twin or an IFC model is answered by the geometry engines.
2. **Sheet reader for large sheets** with no twin: an image with a long side of at least `LEARGAS_SHEET_MIN_PX`
   (3,500) or a PDF whose page renders at least that size at 150 dpi (about A2 and up). If it cannot answer,
   the normal flow continues.
3. **Gemma for images**, including small PDFs (rendered to a page-1 PNG twin on demand) and anything the sheet
   reader could not answer. CubiCasa windows, doors, sinks and showers go to the specialist
   (`LEARGAS_GEMMA_SPECIALIST`), everything else to `gemma-ft`.
4. **Reconcile.** Geometry and Gemma agree → verified. They differ and Gemma is above its calibrated verified bar
   → disagreement (geometry's value reported). They differ and Gemma is below its bar → geometry verified, with
   Gemma's estimate in the explanation. Gemma alone → verified, partial or cannot_verify by its calibrated
   confidence; on uploads or free-form questions it tops out at partial.

## Endpoints

- `POST /ask` `{path, question, type?, engine?, region?, area_mode?, room_breakdown?, slab_breakdown?}` → `Answer`, through the router (`app/router.py`). `LEARGAS_MOCK=1` returns the gold answer with placeholder evidence instead.
- `POST /upload?name=<file>[&group=<id>]`, raw file bytes as the body → `{group, drawing}`. PNG/JPG/PDF/DXF/IFC, up to 60 MB. Stored as `uploads/<group>/<stem><ext>` under the data root, so `drawing.path` works with `/ask` and `/drawing`, and uploads are listed first in `/drawings`. Send twins (`plan.pdf` + `plan.dxf`) with the first upload's `group` and they pair like dataset twins. A PDF gets a PNG twin for Gemma if PyMuPDF is installed.
- Gemma is `verified` only on dataset drawings asked a question that matches a dataset template (where its threshold was calibrated). On uploads or free-form questions it tops out at `partial`. `LEARGAS_GEMMA_CALIBRATED_ONLY=0` turns this off. `/health` reports `query_templates`: if that's 0, run `build_templates`.
- `POST /drawings/upload?filename=<file>`: one plan as the raw body (see Uploading plans below).
- `GET /drawings`, `GET /drawing?path=…&page=0`: the catalogue and the sheet image.
- `GET /schema`: JSON Schema for the request and `Answer`.
- `GET /health`: connection, model status and template count.
- `GET /voice/status`, `POST /voice/transcribe`, `POST /voice/speak`: voice, when `ELEVENLABS_API_KEY` is set.

## Answer contract (`app/schema.py`, exported to `contracts/`)

- `path`, `question`, `answer`, `unit`, `type` match `questions.jsonl`, so API output can be scored directly.
- `status`: `verified` | `partial` | `disagreement` | `cannot_verify` (then `answer` is `null`).
- `source`: `geometry_dxf` | `geometry_ifc` | `sheet_reader` | `gemma_ft` | `gemma_base` | `mock`. `sources[]` holds each engine's answer when the router ran more than one.
- `evidence[]`: `{shape, page, label?, value?, source?}`, where `shape` is one of
  `{"kind":"polygon","points":[[x,y],...]}`, `{"kind":"bbox","bbox":[x0,y0,x1,y1]}` or `{"kind":"point","point":[x,y]}`.
  Coordinates are **normalized 0–1 on the rendered image** (PNG, or PDF page `page`), with the origin at the top left and y pointing down.

Regenerate `contracts/` after schema changes: `cd backend && ../.venv/bin/python export_schema.py`.

## Question → query (`app/query/`)

`parse(question)` turns a question in any dataset language into a structured `Query`, for example `{op: count, target: window, scope: plan}`, which the DXF and IFC engines execute. It tries these in order:

1. **template**: an exact match in the multilingual template table. Confidence 0.99.
2. **rules**: keyword rules for English questions, which also cover paraphrases. Confidence 0.85.
3. **llm**: Gemma over an OpenAI-compatible endpoint. It runs whenever `LEARGAS_LLM_BASE_URL` or, failing that, `MODEL_BASE_URL` is set (key: `LEARGAS_LLM_API_KEY`, else `MODEL_API_KEY`; `LEARGAS_LLM_MODEL` defaults to `gemma-base`, so gemma-base must be served). Confidence 0.7.
4. **none**: the caller should answer `cannot_verify`.

The template table is built from the dataset, so it is gitignored. Build it once per machine:

```bash
cd backend && ../.venv/bin/python -m app.query.build_templates --questions ../datasets/junction-dataset/questions.jsonl
../.venv/bin/python -m app.query.eval_parse --questions ../datasets/junction-dataset/questions.jsonl   # coverage report
```

On the full dataset, without the LLM, 100% of count, area, length and volume questions parse, except 24 bespoke `opening_design` schedule questions. Translations parse to the same query as their English original in every case. `POST /parse` is available as `app.query.api.router`, but it isn't mounted in `main.py` yet.

## Uploading plans

The plan library accepts PDF, PNG, JPEG and DXF files up to **60 MB** each.
Install `backend/requirements.txt` for image/PDF support, and
`backend/requirements-dxf.txt` for DXF rendering.

`POST /drawings/upload?filename=Floor.pdf` takes the file's raw bytes as the
request body (`Content-Type: application/octet-stream`) and returns a drawing
record with HTTP 201. Files are decoded before publication; empty, corrupt,
password-protected and unsupported files are rejected. Over-limit requests return
413, and unavailable rendering/storage returns 503.

Uploads persist in `data/uploads/<unique-id>/` beneath `LEARGAS_DATA_ROOT`
(default `datasets/junction-dataset/`), with a `plan.json` manifest. Keep that
directory on persistent storage when deploying. `GET /drawings` includes uploaded
plans independently of the reference-question catalogue; uploads have no reference
questions. Identical filenames receive separate directories and previews.

PDFs open on page one. A PNG of that page is saved beside the original PDF so the
viewer and raster model use the same framing. Questions use the existing answer
engines and their availability; DXF geometry answers require a supported drawing
profile. Uploading a plan does not manufacture reference answers.

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

## Floor-area breakdowns and selection modes

The inspector's **Show floor areas by room** action requests a geometry-backed
takeoff. Each `room_areas` row contains the room ID/name, area in m², quantity
basis (`printed`, `geometry`, or IFC `quantity`), completeness, and indices into
the answer's sheet evidence. Rows can be clicked to highlight their polygons.
IFC rows also include the storey; they have no sheet highlights until 2D
registration is available. Ordinary geometry-backed room-area questions return
the same breakdown, including existing room/apartment filters.

```json
{"path":"data/swiss_dwellings/floor.pdf","question":"Show floor areas by room","room_breakdown":true,"area_mode":"whole_rooms"}
```

With a `region`, `area_mode` controls how floor areas are measured:

- `whole_rooms` (default): sum complete rooms using printed m² where available,
  otherwise CAD floor geometry. If the selection cuts a relevant room, refuse
  the entire measurement and explain how to redraw it or switch modes.
- `intersection`: measure the intersection of the selected box and the actual
  numbered-room CAD floor polygons in metres. Cut rooms are marked
  `complete: false`; enclosed voids are removed. Printed areas are never
  prorated. This measures floor space inside the box, not the box itself or
  space outside known floor polygons. A selection containing no room floor
  space returns 0 m².

`intersection` requires a region, a floor-area question, supported metre-based
DXF geometry, and confident registration to the displayed sheet. IFC region
measurement and uncalibrated raster-only measurement return `cannot_verify`.
Explicit breakdown/intersection requests require Auto or Geometry and bypass
scalar demo answers and model inference. Polygon evidence can contain `holes`
for voids and multiple polygons for disconnected selected portions. The total
is rounded to 0.01 m²; row quantities retain up to six decimal places.

`GET /drawings` supports `limit` (up to 5000) and `offset`; `total` is the full catalogue count.

## Slab geometry and specifications

Ask **“Show slab area grouped by thickness and reinforcement”** using Auto or
Geometry, or use the inspector's **Show slab area by specification** action.
`POST /ask` also accepts `slab_breakdown: true` with a slab-area question.
The response has `slab_areas` (one slab/zone per row: area, mark, type, thickness
in mm, reinforcement, quantity/geometry basis, warnings, and source references)
and `slab_groups` (area totals grouped by thickness/reinforcement with member IDs).
The numeric `answer` is total measured slab area in m². Groups sum unrounded
areas. A missing or conflicting thickness/reinforcement stays `null`, appears as
**Unknown specification**, and makes the answer `partial` while retaining area.
An unmeasurable slab prevents a misleading partial area sum. Scalar model,
mock and demo-cache responses cannot substitute for this takeoff.

IFC takes `NetArea` base quantities, falling back to footprint geometry. Length,
area and explicit property/quantity units are converted independently. Own
occurrence properties/material layers take precedence over type defaults.
The extractor inspects slab thickness/width quantities and properties, complete
`IfcMaterialLayerSet` / `IfcMaterialLayerSetUsage` layers, reinforcement property
sets, `IfcReinforcementDefinitionProperties` cross sections, and bars/meshes
explicitly linked through decomposition, nesting, product assignments, element
connections or a group containing only this slab. Nearby reinforcement is not
assigned by proximity. These structures must actually be populated in the export;
concrete material and the presence of a slab do not establish reinforcement.
See [buildingSMART's slab definition](https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/HTML/schema/ifcsharedbldgelements/lexical/ifcslab.htm).
Unscoped IFC questions cover the model. Add `on level 'Ground Floor'` to the
grouped question to restrict it to a named storey. IFC has no sheet overlays yet.

The structural drawing profile uses DXF closed polylines on `SLAB_OUTLINE`,
cutouts on `SLAB_OPENING`, and TEXT/MTEXT slab marks on `SLAB_MARK` inside each
zone. `$INSUNITS` must declare drawing units. Overlapping or invalid zones are
refused. Unmarked zones retain their area with an unknown specification.
Schedules and details can be on other sheets uploaded into the **same group**
with `/upload?name=structure.pdf&group=<first-upload-group>`. Outside uploads,
only same-stem twins are inspected. Schedule text comes from DXF layers
`SLAB_SCHEDULE` / `SLAB_DETAIL`, text-based PDF pages, or native PDF tables with
Mark, Type, Thickness (mm), Reinforcement and Detail columns. For example:

```text
Mark | Type | Thickness | Reinforcement | Detail
S1 | RC | 200 mm | - | D1
S2 | RC | 250 mm | T16 @ 200 EW | -
Detail D1 | Reinforcement: T12 @ 200 EW top and bottom
```

Keyed rows such as `S1 | Type: RC | Thickness: 200 mm | Detail: D1` also work.
Thickness requires explicit units in the value or column header. Matching marks
link geometry → schedule → detail; references retain file, page and source text.
Conflicting entries or unresolved detail links leave reinforcement unknown.
Aligned DXF outlines can be highlighted from the slab inventory. This profile
does not OCR scanned schedules, infer slab zones from room outlines, or measure
raster-only plans. Selected-region/intersection slab takeoffs are not supported.

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
