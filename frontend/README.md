# Léargas frontend

The web app: open or upload a drawing, ask a question in any language, and see the answer with its evidence
marked on the sheet. React 19, TypeScript and Vite. Live at https://leargas-blue.vercel.app/.

## Run it

```bash
npm install
npm run dev        # http://localhost:5173; /api is proxied to http://127.0.0.1:8000
npm run build      # type check (tsc -b) and production build
npm run lint
```

Start the backend too, from the repository root: `uvicorn app.main:app --app-dir backend --port 8000`.

- Another local backend: `LEARGAS_API=http://127.0.0.1:8100 npm run dev`.
- A deployed backend: `VITE_API_BASE=https://<host> npm run build`. Vercel sets `VITE_API_BASE` for production.

## The screen (Clár)

The interface is called **Clár** (Irish for a plan or board), in `src/ui/clar/`. The whole screen is one drawing
sheet, like a printed A1 sheet with a title strip on the right.

**The sheet**
- Zone references (1–8 across, A–F down) move with the drawing, so any mark can be quoted as "D4".
- Drag to pan, scroll to zoom, double-click or **Fit** to fit. The title block shows the zone under the cursor,
  the zoom, the format and the engine (**Checked by**).
- Drop files anywhere on the sheet to upload them.

**The title strip**
- **Model lights** (top right): one light per engine, in its pencil colour, with Ready / Checking / Offline.
- **Drawing**: the open drawing, **Upload a drawing** (PNG, JPG, PDF, DXF or IFC, up to 60 MB) and the
  **Drawing register** (search and filter every drawing and upload).
- **Question box**: type, or press **Speak** and ask aloud in any language. Press `/` to jump to the box.
  Spoken questions are answered aloud.
- **More ways to ask** (folded): **Cloud a region** to ask about one part of the sheet only (with **Whole rooms**
  or **Exact cut** for areas), and the **Room areas** and **Slab areas** takeoffs.
- **The answer**: the value and its status, the cross-check lanes (blue for geometry, violet for Gemma),
  numbered notes that explain the status, the evidence table, the time, and the cost per 1,000 answers like it.
- **Questions to try** for the open drawing, and the **register of questions** asked (Q01, Q02 …).
  Click a row to reopen that answer.

**Evidence on the sheet** uses checking-print conventions: yellow highlighter for what was counted or measured,
red pen for the item in focus and for clouded regions. The line style shows the source: solid is measured
geometry, dashed is a model estimate, dotted is read from the sheet's text. Hover a row to show its mark;
click a row to centre on it.

**Type and accessibility**: Barlow, Barlow Semi Condensed and Barlow Condensed (DIN-style lettering, bundled with
`@fontsource`, so nothing is fetched from a CDN). Text contrast is at least 4.5:1, text is at least 11 px, every
control has a visible focus ring, and animations stop when the system asks for reduced motion.

## Code map

| Path | What |
|---|---|
| `src/ui/clar/ClarApp.tsx` | Layout, title strip, question box, answer, suggestions, register of questions |
| `src/ui/clar/ClarSheet.tsx` | The sheet, rulers, evidence marks, region cloud |
| `src/ui/clar/ClarRegister.tsx` | The drawing register dialog |
| `src/ui/clar/CrossCheck.tsx` | Geometry-versus-Gemma lanes and the verdict |
| `src/core/` | Session state, pan and zoom, shapes, the catalogue, uploads, breakdown tables, explanations, cost |
| `src/api.ts`, `src/types.ts` | API calls; `types.ts` mirrors `backend/app/schema.py` by hand |
| `src/voice.ts` | Dictation and read-aloud |

## What it talks to

- `GET /drawings`: the drawing register (drawings with dataset questions, and uploads first).
- `POST /drawings/upload?filename=…`: one file as the raw request body; returns the new drawing.
- `POST /upload?name=…[&group=…]`: one file of a set; the same `group` pairs twins (`plan.pdf` + `plan.dxf`).
- `GET /drawing?path=…&page=0`: the sheet image (or an SVG render of the DXF twin).
- `POST /ask` `{path, question, engine, region?, area_mode?, room_breakdown?, slab_breakdown?}` → `Answer`.
- `GET /health`: connection and model status, polled every 15 s.
- `GET /voice/status`, `POST /voice/transcribe`, `POST /voice/speak`: shown only when the backend has a voice key.

Evidence shapes (`point`, `bbox`, `polygon`) are normalized 0–1 on the rendered sheet, origin top left, y down.
If you change the answer format, update `backend/app/schema.py`, `contracts/` and `src/types.ts` together.
