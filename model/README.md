# model/: the vision model

Everything here trains, serves, evaluates and calibrates the vision model: **Gemma 4 E4B** fine-tuned with LoRA
to answer questions about floor-plan images. Run every command from the repository root as
`python -m model.<name>`.

Code the backend imports (`common`, `prompt`, `client`, `scoring`, `gemma_engine`) uses only the standard library
and Pillow, so the backend needs no machine-learning packages.

## What is live

| Served name | Weights | Answers |
|---|---|---|
| `gemma-ft` | **The augmented model**: run 1, then 500 more steps on the CubiCasa-focused mix with half the images randomly damaged (`augment_sft.py`) | All uploads and every other image question |
| `gemma-ft-cc` | The CubiCasa specialist: the same mix without the damage | Dataset CubiCasa windows, doors, sinks and showers |
| `gemma-base` | Gemma 4 E4B, not fine-tuned | Comparison, and the question parser's fallback |

The backend uses each model's own calibration file (`results/calibration_<label>.json`). For `gemma-ft` the label
is set with `LEARGAS_GEMMA_FT_LABEL=gemma-ft-cc-aug`.

## Results

1,000 fixed held-out questions (`data/splits/raster_eval.jsonl`: 600 CubiCasa, 400 Swiss). "Scan", "photo" and
"low-res" are the same images damaged by `robustness.py`.

| Model | Clean | Scan | Photo | Low-res | Notes |
|---|---:|---:|---:|---:|---|
| Prior (most common answer) | 40.0% | | | | |
| Gemma 4 E4B, base | 33.0% | | | | |
| Gemma 4 E2B, base | 35.0% | | | | |
| E2B fine-tuned, run 1 recipe | 58.0% | | | | $0.040 per 1,000 answers |
| E4B run 1 | 61.0% | 60.2% | 58.9% | 56.4% | $0.046 per 1,000 answers |
| E4B run 2 (reweighted + reworded questions) | 59.1% | | | | dropped |
| E4B CubiCasa specialist | **62.4%** | 60.3% | 59.4% | 57.8% | |
| **E4B augmented (live `gemma-ft`)** | 61.6% | **61.6%** | **60.3%** | **58.2%** | |
| Model soups (weight averages) | 60.5%, 61.1% | | | | dropped |

Also tried and dropped: twice the image detail (1,120 image tokens: 33.7% vs 33.0% for the base model, at double
the cost), cropping Swiss sheets to the plan, and zero-shot point-then-count and tiling for doors and windows.

Through the hosted app, on held-out drawings uploaded as unknown files: **54% right, 77% right when it answers**.
The full table is `results/table.md` (`python -m model.report`).

## Pipeline

| Step | Command |
|---|---|
| Split by drawing (twins stay together) | `python -m model.make_split` (also `make_demo_set`, `make_judge_set`) |
| Training data | `python -m model.build_sft --out data/sft/run1.jsonl --n 20000` (`--focus <regex> --focus-frac 0.6` for a specialist mix, `--paraphrase-frac 0.25` for reworded questions, `--preview 12` to look at the images) |
| Damage half the images | `python -m model.augment_sft --data data/sft/spec_cc.jsonl --out data/sft/spec_cc_aug.jsonl --img-dir ~/aug/spec_cc --frac 0.5` |
| Train | `python -m model.train_lora --model ~/merged/run1 --data <file> --run <name> --max-steps 500` (about 50 min on an A100), then `--merge-only --run <name>` |
| Serve | `bash infra/serve.sh model <served-name> <port> ~/merged/<name> 0.25` |
| Score | `python -m model.baseline_eval --models <served-name> --out results/<name>.json` |
| Calibrate | `python -m model.calibrate --label <name>` (the confidence where 95% of answers are right, per source and question type) |
| Report | `python -m model.report` → `results/table.md`; `python eval/sweep_chart.py` → accuracy-versus-cost chart |

`infra/aug_chain.sh`, `infra/spec_chain.sh` and `infra/soup_chain.sh` run whole experiments unattended on the GPU
server. Train and serve must use the same image budget: `prompt.MAX_SOFT_TOKENS` = `serve.sh SOFT_TOKENS` = 560,
with images resized to a 1,600 px long side.

Never train on a held-out drawing: `common.is_heldout(path)` is true for every twin of one (`augment_sft` refuses
them too).

## Test batteries

| Command | What it measures |
|---|---|
| `python -m model.robustness --out ~/degraded` + `infra/robust_chain.sh` | The held-out set as scans, phone photos and low-resolution copies |
| `python -m model.hosted_battery build` / `run --base https://<host>` | The live app on held-out drawings renamed and uploaded as PNG, JPG, PDF and phone photo, plus Stoa's sheets and the judge set |
| `python -m model.stoa_battery --base https://<host>` | Hand-checked facts on Stoa's four example sheets, each asked 3–6 ways |
| `python -m model.routed_eval` | The generalist plus the specialist, combined by the router rule, from cached predictions |
| `python -m model.synthetic_data` + `synthetic_eval` | A synthetic benchmark with DXF twins and no dataset use (below) |

Battery outputs are written to `results/battery/`, which is not in git (they contain dataset content).

## Using the model from code

```python
from model.client import ask          # reads MODEL_BASE_URL / MODEL_API_KEY from .env
out = ask("data/cubicasa5k/colorful-10052.png", "How many windows?", model="gemma-ft")
# {"answer": 7, "unit": "count", "confidence": 0.93, "abstained": False, "latency_ms": 840, ...}

from model.gemma_engine import answer  # returns a backend Answer, with a calibrated status
a = answer("data/cubicasa5k/colorful-10052.png", "How many windows?", engine="gemma_ft")
```

- `confidence` is the mean probability of the answer's tokens (vLLM logprobs).
- Swiss questions point at the PDF; the model reads its PNG twin. Any other PDF is rendered to a page-1 PNG twin.
- Gemma writes points as `[y, x]` on a 0–1000 grid; `prompt.parse_output` converts them to `[x, y]` in 0–1.
  The live models are not trained to give points.

## Splits (`data/splits/`, not in git)

| File | What |
|---|---|
| `heldout_drawings.txt` | Every file in a held-out drawing group (PDF, DXF and PNG twins, and all views of an IFC model): 299 groups, about 5% of each source. All of `opening_design` is held out. |
| `raster_eval.jsonl` | The fixed 1,000 held-out image questions every model is scored on. |
| `judge_questions.jsonl` | 30 judge-style questions: paraphrases in several languages, new questions on held-out drawings, and questions on unlabelled archive drawings. |
| `demo_questions.jsonl` | 50 held-out questions across sources and types, plus 3 that should be held back. |
| `swiss_printed_areas.json` | Whether each Swiss render prints room areas (307 of 1,040 do). Area questions on the others go to the DXF engine. |

## Synthetic benchmark

`synthetic_data` makes 600 floor-plan layouts with clean and scan images, DXF twins and 36,000 gold questions,
without the challenge dataset or a model. All variants of a layout stay in the same split; use its `split` field.

```bash
python -m model.synthetic_data --out data/synthetic --plans 600
python -m model.synthetic_eval --data data/synthetic --engine gemma-ft --limit 100 --out results/synthetic/ft.jsonl
python -m model.synthetic_eval --data data/synthetic --engine geometry --category geometry --out results/synthetic/geometry_test.jsonl
```

Synthetic accuracy does not prove accuracy on real drawings; use `raster_eval.jsonl` for that.

## Tests

```bash
python tests/test_prompt.py && python tests/test_splits.py && python tests/test_point_eval.py && python tests/test_gemma_engine.py
```
