# model/: Mark's raster track

Everything runs from the repo root with `python -m model.<name>`. Code that Harry imports is stdlib-only (Pillow is needed only for images).

## What Harry uses

### C1: splits (`data/splits/`)

| File | What |
|---|---|
| `heldout_drawings.txt` | Every file on disk in a held-out drawing group: pdf/dxf/png twins, and all views of a held-out IFC model. 299 groups, about 5% per source. All of `opening_design` is held out (eval only). |
| `demo_questions.jsonl` | 50 held-out questions across every source and type, plus 3 that should abstain (`"expected": "cannot_verify"`). `beat` links rows to the demo script. |
| `judge_questions.jsonl` | 30 judge-style questions: 15 paraphrases (sv/fr/nl/de/fi/casual en; gold copied from `questions.jsonl`), 10 new questions on held-out drawings, and 5 on unlabelled Finna/HABS drawings. `kind` and `answer_check` say where each answer came from. |
| `raster_eval.jsonl` | The fixed ~1,000 held-out raster questions (600 CubiCasa, 400 swiss) that every model run is scored on. Use it for `run_eval.py --sources` too, so the numbers compare. |
| `swiss_printed_areas.json` | `{stem: bool}`: does the swiss render print room m²? Only 307 of 1,040 do. |

```python
from model.common import is_heldout, group_key, load_questions
is_heldout("data/swiss_dwellings/site2297_bldg3392_floor15123.dxf")   # True: twins collapse
```
Export C4 point labels for drawings where `not is_heldout(path)` only.

### C3: prompt builder, parser and client

```python
from model.prompt import build_text_messages, extract_json      # question -> query parsing
msgs = build_text_messages(SYSTEM, question, few_shot=[("How many windows…", {"op": "count", "target": "window"})])

from model.client import chat, ask                               # reads MODEL_BASE_URL / MODEL_API_KEY from .env
resp = chat(msgs, "gemma-base", temperature=0, max_tokens=128)
query = extract_json(resp["choices"][0]["message"]["content"])

out = ask("data/cubicasa5k/colorful-10052.png", "How many windows?", model="gemma-ft")
# {"answer": 7, "unit": "count", "points": [[x, y], …] | None, "confidence": 0.93, "abstained": False,
#  "reason": None, "ok": True, "raw": "...", "latency_ms": 840, ...}
```
- `points` are already in C2 convention: `[x, y]`, normalised 0–1. The model writes `[y, x]` on a 0–1000 grid (Gemma's native detection format) and `parse_output` converts.
- `confidence` is the mean token probability of the answer's tokens (vLLM `logprobs`). It is `None` if logprobs weren't requested.
- Swiss questions point at the PDF. The raster model sees the PNG twin (`baseline_eval.raster_image_path`).

### The frontend's expectations of C5 (please check these, Harry)
- `GET /drawing/{path}/image`: the frontend URL-encodes each path segment (`opening_design` paths contain spaces), e.g. `/drawing/data/opening_design/Sports_Complex/Sheets%20-%20Current%20Set/A-801….pdf/image`. A FastAPI route `/drawing/{path:path}/image` handles it.
- `POST /ask` JSON: `{"path", "question", "model"?}`. Uploads are sent as **multipart** with fields `upload` (file), `question` and `model`. `model` is omitted for "Auto".
- `POST /feedback`: `{"answer_id", "added": [[x, y], …], "removed": ["e3", …]}`. It is sent on every change with the **full current state** for that answer, so the server should keep the latest per `answer_id` (or append; the last line wins).
- CORS: allow `http://localhost:5173` in dev.

## Mark's runbook

| Step | Command |
|---|---|
| M1 split / demo / judge | `python -m model.make_split && python -m model.make_demo_set && python -m model.make_judge_set` |
| M2 box | see `infra/verda.md` |
| M3 check on real outputs | `python -m model.smoke_test --model gemma-base --n 20 && python tests/test_prompt.py` |
| M4 baselines | `python -m model.baseline_eval --models prior,gemma-base && python -m model.report` |
| M4b CubiCasa points | `python -m model.cubicasa_points --root ~/cubicasa/cubicasa5k --inspect 5`, then without `--inspect`, then `--check 5` |
| M5 SFT data | `python -m model.build_sft --out data/sft/run1.jsonl --n 20000` (`--preview 12` to eyeball resolution) |
| M6 train | `python -m model.train_lora --check-processor`, then a `--max-steps 5 --no-push` smoke run, then the real run (see the docstring) |
| M8 eval run 1 | `python -m model.baseline_eval --models gemma-ft --out results/run1.json && python -m model.report` |
| M12 eval run 2 (served as `gemma-ft` too, so **`--label` is required** or run 1's cached predictions are reused) | `python -m model.baseline_eval --models gemma-ft --label gemma-ft-run2 --points && python -m model.report` |
| M12 point accuracy | `python -m model.cubicasa_points --root ~/cubicasa/cubicasa5k --heldout-eval` (once, eval-only labels), then `python -m model.point_eval --preds results/preds/gemma-ft-run2__heldout_raster.jsonl --overlays 6` → `results/points.json` + slide images in `results/points_overlays/` |
| M9 run 2 data | `python -m model.build_sft --out data/sft/run2.jsonl --n 60000 --points` |
| M11b sweep | `python -m model.throughput --model <m> --usd-per-hour <rate>` per model, then `python eval/sweep_chart.py` |
| Tests | `python tests/test_prompt.py && python tests/test_splits.py` |
