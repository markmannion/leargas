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

## Layout

The UI is **Clár** (`src/ui/clar/`): the screen is a drawing sheet. Zone references (1–8 across, A–F down) pan and zoom with the drawing. A title strip on the right holds the question, the answer and a register of questions asked. Yellow highlighter marks the evidence, and a red revision cloud marks a region. The line style shows the source: solid is measured, dashed is estimated, dotted is read from text. The **Drawing register** link opens the plan list and uploads.

`/?ui=classic` loads the earlier floating-panel UI (`src/App.tsx`, `src/components/`) as a fallback. Both use the same backend calls. Clár's state, pan/zoom and table code is in `src/core/`. The Archivo font is bundled, so nothing is fetched from a CDN.

The sections below describe the classic UI's controls. Clár has the same features under different names: "Cloud a region" for Draw a region, "Takeoff: Room areas / Slab areas", and "Checked by" for the engine.

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
