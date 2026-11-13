# leargas

Repo for the Junction 26 Stoa Track — **BlueprintTrace**, *"Ask the building. See the proof."*

A voice-first, citation-backed Q&A assistant for construction drawings: ask a question, get an answer with a highlighted region on the actual sheet it came from, and an honest refusal when the evidence isn't there.

## Workstreams

| Track | People | Goal |
|---|---|---|
| App build | Person 1, Person 2 | Ingest drawings → retrieve evidence → answer with Gemini, citations, and a highlighted region; voice via ElevenLabs |
| Hugging Face model training | Task A, Task B | Train a quantity-takeoff model on the challenge's Hugging Face drawing dataset (~14k drawings, ~120k questions), split in parallel by file format: **Task A** — raster (PDF/PNG/JPEG/SVG), **Task B** — structured CAD/BIM (DWG/DXF/IFC) |

Full build spec, architecture, and task breakdown live outside version control (see below).

## Getting the dataset

The dataset is a private Hugging Face dataset: [leargas/junction-dataset](https://huggingface.co/datasets/leargas/junction-dataset). Ask to be added to the `leargas` org.

```powershell
pip install -U huggingface_hub
hf auth login   # Read token from https://huggingface.co/settings/tokens
hf download leargas/junction-dataset --repo-type=dataset --local-dir datasets/junction-dataset
```

`datasets/` is gitignored. Don't commit dataset files.

## Docs

Planning and task docs are kept locally in `explainer_docs/` (git-ignored — not pushed to this repo):

- `blueprint-trace-plan.md` — the three original architecture options considered.
- `blueprint-trace-combined-plan.md` — the final build plan: resequenced architecture, Task A/Task B split for the Hugging Face track, hour-by-hour schedule, eval plan, demo script.
- `blueprint-trace-explainer.md` — plain-language walkthrough of the approach.

Share these with teammates directly (Slack/Drive/etc.) since they won't come through on `git clone`.

## Data license note

The Hugging Face dataset used for model training is **non-commercial, Junction-challenge use only**. Any dataset snapshots, checkpoints, or derived artifacts pushed to the Hugging Face Hub must be kept **private** for the duration of the challenge.
