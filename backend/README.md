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

## Answer contract (`app/schema.py`, exported to `contracts/`)

- `path`, `question`, `answer`, `unit`, `type` match `questions.jsonl`, so API output can be scored directly.
- `status`: `verified` | `partial` | `disagreement` | `cannot_verify` (then `answer` is `null`).
- `source`: `geometry_dxf` | `geometry_ifc` | `gemma_ft` | `gemma_base` | `mock`. `sources[]` holds each engine's answer when the router ran more than one.
- `evidence[]`: `{shape, page, label?, value?, source?}`, where `shape` is one of
  `{"kind":"polygon","points":[[x,y],...]}`, `{"kind":"bbox","bbox":[x0,y0,x1,y1]}` or `{"kind":"point","point":[x,y]}`.
  Coordinates are **normalized 0–1 on the rendered image** (PNG, or PDF page `page`), with the origin at the top left and y pointing down.

Regenerate `contracts/` after schema changes: `cd backend && ../.venv/bin/python export_schema.py`.

## Scorer

```bash
.venv/bin/python backend/score.py --gold questions.jsonl --pred preds.jsonl [--split heldout.txt] [--tol 0.02] [--json out.json]
```

- Counts must be exact. Area, length and volume must be within `--tol` (default **2%**, the dataset's official rule); accuracy at 1% is also reported. ft/ft²/ft³ are converted to metric.
- `text` answers are not in the headline number. A normalized exact match is reported separately.
- `cannot_verify` or a missing prediction counts as wrong. `coverage` is the share answered and `prec` is accuracy among answered.
- `--split` matches drawings by `data/<source>/<stem>`, so holding out a `.pdf` also holds out its `.dxf`/`.png` twin.
- Breaks results down by type, source and extension. Use `from score import score_one` to score in-process.

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
