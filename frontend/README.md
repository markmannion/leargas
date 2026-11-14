# frontend

BlueprintTrace UI: pick a drawing, ask a question in any language, get the answer with its evidence marked on the sheet.

```bash
npm install
npm run dev          # http://localhost:5173, proxies /api → http://127.0.0.1:8000
```

Run the backend alongside it (from the repo root):

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --port 8000 --reload
```

Point the proxy at another backend with `LEARGAS_API=http://host:port npm run dev`, or build against a deployed API with `VITE_API_BASE=https://host npm run build`.

## What it talks to

- `GET /drawings`: drawing register (drawings with questions and something renderable).
- `GET /drawing?path=…`: the sheet image. Falls back to an SVG render of the DXF twin when the PNG/PDF is not available locally; the status bar says "Rendered from DXF twin" when that happens.
- `POST /ask` `{path, question, type?, engine}`: returns an `Answer` (`src/types.ts` mirrors `backend/app/schema.py`). The top-bar engine toggle sets `engine`.
- `GET /health`: `mode: "mock"` shows the amber *Mock API* badge. Polled every 15 s.

Evidence shapes (`point`, `bbox`, `polygon`) are normalized 0–1 on the rendered sheet and drawn in `src/components/SheetViewer.tsx`, coloured by source: blue for geometry, orange for Gemma, violet for the mock.

Choose **Draw a region** in the question panel or viewer toolbar, then drag a box on the plan.
The next typed, suggested, or spoken question is limited to that selection. **Redraw region** replaces
the box, **Use whole plan** clears it, and Escape cancels drawing. The selection follows pan/zoom;
switching plans clears the selection and any pending answer. Counts use item centers; include entire
rooms when asking for their areas. Scoped answers are not compared against whole-sheet dataset answers.
