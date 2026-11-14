# Léargas

**Ask a question about a construction drawing. Get the answer, and see the proof on the sheet.**

Léargas is the Irish word for insight. You open a drawing (a PDF, a scan, a photo, a CAD file or a BIM model)
and ask, "How many doors are on this floor?" or "What is the area of the library?".
Léargas answers, marks the evidence on the drawing, and tells you how sure it is.
If it cannot find evidence, it says **Cannot verify**. It does not guess.

We made Léargas for the Stoa track at Junction 2026.

**Try it:** https://leargas-blue.vercel.app/

---

## What you see

1. Open a drawing from the register, or upload your own (PNG, JPG, PDF, DXF or IFC, up to 60 MB).
   You can also drop files on the sheet.
2. Type a question or say it.
3. Léargas gives the answer, its status, and the evidence. The evidence is highlighted on the sheet:
   solid lines are measured, dashed lines are estimates, dotted lines are read from the sheet's text.
4. When two engines answer the same question, the cross-check shows both answers side by side.
5. Each answer shows how long it took and what 1,000 answers like it cost to compute.

Example questions:

- "How many windows are on this floor plan?"
- "What is the floor area of the library?"
- "How many metres of skirting board does the fitness room need?"
- "How many pipe supports are on this sheet?"
- "What is the slab area by type?"

## How sure is the answer?

Every answer has one of four statuses.

| Status | What it means |
|---|---|
| **Verified** | A reliable source measured or read the answer, or two sources agree. |
| **Partial** | There is an answer, but it is an estimate. Check the evidence. |
| **Disagreement** | Two confident sources gave different answers. Check the drawing. |
| **Cannot verify** | No source is sure enough. Léargas holds the answer back and shows its best guess, greyed out. |

A wrong answer is worse than "I don't know". The thresholds are measured, not guessed (see Results).

## How it works

```
 question ──► parser ──► router ──┬─► CAD/BIM geometry (DXF, IFC)   exact counts, areas, lengths
                                  ├─► sheet reader (large sheets)    printed text, tags, scale, rooms
                                  └─► vision model (images, scans)   fine-tuned Gemma 4
                                              │
                                  reconcile: verified / partial / disagreement / cannot verify
                                              │
                                  answer + evidence on the sheet + time + cost
```

1. **Parser** (`backend/app/query/`): turns the question into a structured query, for example
   `count windows` or `area of room "Küche"`. It uses a table of the dataset's question patterns
   in every language, then English keyword rules, then a language model for unusual wording.
2. **Router** (`backend/app/router.py`): picks the engines that can answer this drawing.
   - A drawing with a DXF file or an IFC model goes to the **geometry engines**. They count and measure the real
     lines, shapes and building elements. These answers are exact.
   - A large sheet (an image 3,500 px or larger, or a PDF of A2 size or larger) goes to the **sheet reader** first.
     It reads the sheet at full size, so small text stays readable.
   - Everything else goes to the **vision model**: smaller images, small PDFs, phone photos, and sheets that the
     sheet reader cannot answer. A PDF is turned into an image of its first page.
3. **Cross-check:** when geometry and the vision model both answer, the router compares them.
   If they agree, the answer is verified. If the vision model is confident and disagrees, the status is
   Disagreement. An unsure model estimate does not overrule exact geometry.
4. **Evidence:** every engine returns shapes (points, boxes or outlines) in the drawing's coordinates.
   The frontend draws them over the sheet like a highlighter.

### The engines

- **Geometry, DXF** (`backend/app/dxf.py`): counts doors, windows, fixtures and rooms, and measures room and
  apartment areas from the CAD layers. The shapes are registered onto the PDF or PNG, so the evidence lands on the
  sheet you see.
- **Geometry, IFC** (`backend/app/ifc.py`): reads counts, areas, lengths and volumes from the BIM model's
  quantities, by storey or for the whole model, and slab takeoffs by thickness and reinforcement.
- **Sheet reader** (`backend/app/sheet/`): reads the text (the PDF text layer, or OCR), finds the drawing scale
  (scale bar, ratio or dimension chain), and then reads printed values and tables, counts equipment tags
  (FP-1, PS-2 …) and room labels, measures room areas and skirting lengths, finds door and window openings,
  slab callouts and overall dimensions. Printed values can be verified; measured values are partial.
- **Vision model** (`model/`): Gemma 4 E4B, fine-tuned with LoRA on the training split of the challenge dataset.
  The live model was also trained on images we damaged on purpose (scan noise, skew, blur, paper tint, low
  resolution, JPEG), so it copes with real scans and photos. Its confidence is calibrated: we measured the
  confidence level above which 95% of its answers are right.

## Results

All numbers come from drawings that were never used for training (a held-out split by drawing, so the PDF, PNG
and CAD versions of one drawing are always on the same side). Numbers count as right within 2%, the official
tolerance. Counts must be exact.

**Geometry (CAD and BIM drawings)**

| Test | Result |
|---|---|
| 2,512 held-out Swiss and IFC questions | **98.2% right, 100% precision**: every miss is a Cannot verify, never a wrong number |
| All 3,062 `ifc_models` questions | 3,062 right |

**Vision model (images)**, 1,000 held-out questions on floor-plan images

| Model | Clean | Scanned | Phone photo | Low resolution |
|---|---:|---:|---:|---:|
| Gemma 4 E4B, not fine-tuned | 33.0% | | | |
| Fine-tuned, run 1 | 61.0% | 60.2% | 58.9% | 56.4% |
| **Fine-tuned with damaged images (live)** | **61.6%** | **61.6%** | **60.3%** | **58.2%** |

**The live app, end to end** (questions sent to the hosted app like a user would)

| Test | Result |
|---|---|
| 100 held-out dataset questions, PDF and PNG | PDFs 50/50 right. PNGs 38/50 right, 10 held back, 2 wrong (both shown as Partial). No wrong answer was marked Verified. |
| Held-out drawings uploaded as unknown files (PNG, JPG, PDF, phone photo) | 54% right overall; **77% right when it answers** |
| Stoa's example sheets, 48 questions worded the way judges might ask | 39 right. No wrong answer was marked Verified. |

Details: `results/table.md`, `results/router_heldout.md`, `model/README.md`.

## Cost

| Engine | Cost per 1,000 answers | Basis |
|---|---:|---|
| Geometry (DXF, IFC) | under $0.0001 | CPU only, under 3 s per answer |
| Sheet reader | under $0.0001, plus about $0.0008 once per new sheet for OCR | CPU only |
| Vision model, Gemma 4 E4B | **$0.046** | Measured: 14 answers a second on one shared A100 at $2.38/h |
| Vision model, Gemma 4 E2B | $0.040 | Measured; 3 points less accurate |

There is no setup cost per drawing: no indexing or embedding step before the first question.

## How Léargas meets the judging criteria

| Criterion | What to look at |
|---|---|
| **Accuracy** | Exact geometry where a CAD or BIM file exists; a full-size sheet reader for large sheets; a fine-tuned, scan-robust vision model for images. Measured on held-out drawings (see Results). |
| **Visual reasoning** | Evidence highlighted on the sheet with line styles by source, the geometry-versus-model cross-check, the reason for every status, room and slab breakdown tables, and a numbered register of questions. |
| **Creativity** | The screen is a drawing sheet: zone references, a title block, a highlighter and revision clouds. Ask about a clouded region only. Ask by voice, or type. Honest "Cannot verify" with the held-back guess. |
| **Low inference cost** | Most answers need no GPU. The vision model costs about $0.05 per 1,000 answers, shown next to every answer. |

## Limits

- The vision model does not mark its evidence on the sheet yet. Its answers show the cross-check and the
  explanation, but no highlights.
- Door and window counts from images alone are weak (about 25% right). The model usually holds them back.
- The sheet reader uses OCR. It can miss text or misread it, and some wordings of a question are not understood
  (for example "How big is the library?").
- Room areas need closed walls. A room that is open to a corridor can include the corridor.
- Only the first page of a multi-page PDF is read.
- TIFF, HEIC and WebP files cannot be uploaded yet. Convert them to PNG or JPG first.

## Run it yourself

All commands start from the repository root.

1. Get access to the private dataset on Hugging Face: ask to join the `leargas` organisation.
2. Download the dataset:

   ```bash
   hf download leargas/junction-dataset --repo-type=dataset --local-dir datasets/junction-dataset
   ```

3. Install the backend:

   ```bash
   pip install -r backend/requirements-dxf.txt -r backend/requirements-ifc.txt -r backend/requirements-sheet.txt
   ```

4. Build the question templates (once per machine):

   ```bash
   cd backend && python -m app.query.build_templates --questions ../datasets/junction-dataset/questions.jsonl
   ```

5. Start the backend:

   ```bash
   uvicorn app.main:app --app-dir backend --port 8000
   ```

6. Start the frontend in a second terminal, then open http://localhost:5173:

   ```bash
   cd frontend && npm install && npm run dev
   ```

7. Optional: for the vision model, set `MODEL_BASE_URL` and `MODEL_API_KEY` in `.env` (see `.env.example`).
   If port 8000 is taken (for example by an SSH tunnel to the model server), start the backend on port 8100 and
   set `LEARGAS_API=http://127.0.0.1:8100` before you start the frontend.

Tests: `cd backend && pytest -q`, and `cd frontend && npm run build && npm run lint`.

## Deploy it

The frontend runs on Vercel. The backend runs on the GPU server, next to the models. See `infra/README.md`.

1. On the server, run the backend script. It installs the backend, downloads the dataset and starts the services
   (they start again after a crash or a reboot). Ports 80 and 443 must be open.

   ```bash
   ssh <server> "LEARGAS_DOMAIN=<server-ip-with-dashes>.sslip.io bash -s" < infra/serve_backend.sh
   ```

2. On Vercel, import this repository with the root directory `frontend`, set
   `VITE_API_BASE=https://<server-ip-with-dashes>.sslip.io`, and deploy.

Run the script again to update the backend. A Hugging Face Docker Space is also possible: see `deploy/push_space.sh`.

## Where the code is

| Folder | What it contains |
|---|---|
| `backend/` | The API, the question parser, the router, and the DXF, IFC and sheet-reader engines. |
| `frontend/` | The web app (React). |
| `model/` | Training, evaluation and calibration of the vision model, and the test batteries. |
| `infra/` | The GPU server: model serving, the model proxy, backend deployment. |
| `deploy/` | Backend start script and the Docker option. |
| `eval/` | Charts. |
| `contracts/` | The answer format as JSON Schema. |
| `results/` | Scores and calibration files. |

## Data licence

The challenge dataset is for non-commercial use at Junction only.
Do not commit dataset files to this repository.
Keep all models and files made from the dataset private on Hugging Face.

## Team

Harry Kennedy (geometry engines, sheet reader, router, API) and Mark Mannion (vision model, infrastructure, interface).
