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

The UI is **Clár** (`src/ui/clar/`): the screen is a drawing sheet.

- **Sheet:** zone references (1–8 across, A–F down) pan and zoom with the drawing, and the title block shows the zone under the cursor. Drag to pan, scroll to zoom, double-click or **Fit** to fit.
- **Title strip** (right): the drawing, the question, the answer, the questions on file for this drawing, and a register of questions asked (Q01, Q02…). Click a register row to reopen that answer.
- **Evidence:** yellow highlighter on the sheet. The line style shows the source: solid is measured from geometry, dashed is estimated by the model, dotted is read from the sheet's text. Hover a row to show its mark in red; click a row to centre on it.
- **Region:** **Cloud a region**, then drag a box. The next question covers only that cloud. Esc cancels, and **Whole sheet** clears it. For area questions, choose **Whole rooms** or **Exact cut**. Scoped answers are not compared with the whole-sheet dataset answers.
- **Takeoff:** **Room areas** gives floor area by room. **Slab areas** groups slab area by thickness and bars (whole sheet only). Bars come only from reinforcement in the model or a linked schedule.
- **Checked by** (title block): the engine. Automatic, geometry only, sheet reader only, fine-tuned Gemma or base Gemma.
- **Drawing register:** search and filter all drawings, and add your own. Drop PDF, PNG, JPEG, DXF or IFC files of up to 25 MB on the register. Files with the same name are paired, so plan.pdf with plan.dxf is checked against the DXF.

State, pan/zoom, shape helpers, the catalogue, uploads and the breakdown tables are in `src/core/`. The Archivo font is bundled, so nothing is fetched from a CDN.

## What it talks to

- `GET /drawings`: the drawing register (drawings with questions and something renderable).
- `POST /drawings/upload?filename=…`: raw single-file upload; returns the new drawing.
- `POST /upload?name=…[&group=…]`: raw upload of one file in a set; the same group pairs twins.
- `GET /drawing?path=…`: the sheet image. Falls back to an SVG render of the DXF twin when the PNG/PDF is not available locally.
- `POST /ask` `{path, question, type?, engine, region?, area_mode?, room_breakdown?}`: returns an `Answer` (`src/types.ts` mirrors `backend/app/schema.py`).
- `GET /health`: connection and Gemma status, polled every 15 s.
- `GET /voice/status`, `POST /voice/transcribe`, `POST /voice/speak`: dictation and read-aloud, shown only when the backend has a voice key.

Evidence shapes (`point`, `bbox`, `polygon`) are normalized 0–1 on the rendered sheet, origin top left, and drawn in `src/ui/clar/ClarSheet.tsx`.
