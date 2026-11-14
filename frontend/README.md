# frontend

Léargas UI: pick a drawing, ask a question in any language, get the answer with its evidence marked on the sheet.

```bash
npm install
npm run dev          # http://localhost:5173, proxies /api → http://127.0.0.1:8000
```

Run the backend alongside it (from the repo root):

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --port 8000 --reload
```

Point the proxy at another backend with `LEARGAS_API=http://host:port npm run dev`, or build against a deployed API with `VITE_API_BASE=https://host npm run build`.

## Layouts

There are three UIs on the same backend. Choose one with `?ui=`:

| URL | Layout |
|---|---|
| `/` | The original: floating panels over the drawing (`src/App.tsx`, `src/components/`). |
| `/?ui=clar` | **Clár**: the screen is a drawing sheet. Zone references (1–8 across, A–F down) pan and zoom with the drawing. A title strip on the right holds the question, the answer and a register of questions asked. Yellow highlighter marks the evidence; a red revision cloud marks a region. The line style shows the source: solid is measured, dashed is estimated, dotted is read from text. |
| `/?ui=solas` | **Solas**: dark. The question and its answer read as one line across the top. When an answer comes back, the sheet goes dark except the evidence. A sharp edge means the evidence was measured, a soft edge means it was estimated. Nothing accepted, nothing lit. Typing in the question box filters the suggested questions. You can drop files anywhere on the window to upload them. |

Both new layouts share `src/core/`: session state (`session.ts`), pan/zoom/region drawing (`viewport.ts`), shape and zone helpers, the drawing catalogue, uploads, and the breakdown tables. Only markup and CSS differ. Each loads its own fonts (Archivo, Atkinson Hyperlegible), which are bundled, so nothing is fetched from a CDN.

## What it talks to

Use **Upload plans**, or drop files on the upload area in the plan library.
PDF, PNG, JPEG, DXF and IFC files up to 25 MiB each are supported. Select matching
PDF and DXF files together to pair a sheet with its geometry. Upload progress and
validation errors appear in the library. A successful upload clears library
filters, opens the plan, and stays in the **uploads** collection after refresh.
PDFs display page one; ask questions using the existing engine controls.

- `GET /drawings`: drawing register (drawings with questions and something renderable).
- `POST /drawings/upload?filename=…`: raw file upload; returns the new drawing.
- `GET /drawing?path=…`: the sheet image. Falls back to an SVG render of the DXF twin when the PNG/PDF is not available locally; the status bar says "Rendered from DXF twin" when that happens.
- `POST /ask` `{path, question, type?, engine}`: returns an `Answer` (`src/types.ts` mirrors `backend/app/schema.py`). The top-bar engine toggle sets `engine`.
- `GET /health`: `mode: "mock"` shows the amber *Mock API* badge. Polled every 15 s.

Evidence shapes (`point`, `bbox`, `polygon`) are normalized 0–1 on the rendered sheet and drawn in `src/components/SheetViewer.tsx`, coloured by source: blue for geometry, orange for Gemma, violet for the mock.

Choose **Draw a region** in the question panel or viewer toolbar, then drag a box on the plan.
The next typed, suggested, or spoken question is limited to that selection. **Redraw region** replaces
the box, **Use whole plan** clears it, and Escape cancels drawing. The selection follows pan/zoom;
switching plans clears the selection and any pending answer. Counts use item centers; include entire
rooms when asking for their areas. Scoped answers are not compared against whole-sheet dataset answers.
# Slab specifications

Use **Show slab area by specification**, or ask **Show slab area grouped by
thickness and reinforcement**. The answer shows grouped totals and expandable
slab records with type, area, thickness, reinforcement, warnings and source-sheet
links. Unknown specifications retain measured area. IFC queries cover the model
unless a named level is requested; drawings require scaled slab zones and linked
structural schedule/detail sheets (see the backend's structural drawing profile).
