# BlueprintTrace frontend (M7 + M11)

React 18, Vite 5 and TypeScript. No UI library.

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

- **Mock mode** (default, `VITE_API_BASE` empty in the repo-root `.env`): `/ask` answers come from `src/mock.ts`, which follows C2 and covers points, bboxes, polygons, working, cross-check and `cannot_verify`. Drawings are served straight from `datasets/junction-dataset` by a Vite dev middleware. Swiss PDFs show their PNG twin and `ifc_models` PDFs their SVG twin.
- **Real mode**: set `VITE_API_BASE=http://<harry-host>:8000` in `../.env` and restart `npm run dev`. The frontend then calls `POST /ask`, `GET /drawing/{path}/image` and `POST /feedback`. The exact shapes are listed in `model/README.md`.

## What's there
- Drawing viewer: drag to pan, wheel or +/− to zoom, Fit. Markers stay the same size on screen at any zoom.
- Evidence overlay for `polygon`, `bbox` and `point`, with a numbered marker (1…n) on every item. Hovering a marker or a list row highlights both.
- Answer card: the figure, source, confidence, how, working, cross-check, time and cost, and the dataset answer when the question comes from the demo or judge sets.
- `cannot_verify`: an amber card with the reason, and no number.
- Click-to-correct (count answers): click a marker to reject it, or click empty paper to add a missed item. The figure becomes "12 → 11" in redline, and each change is sent to `POST /feedback` (mock: `localStorage["bt.corrections"]` plus the console).
- Model toggle (Auto / Base Gemma / Fine-tuned Gemma): re-asks the same question with `model` set. This is demo beat 3.
- Picker over the demo script beats, the demo set by source and the judge set, plus "Upload your own drawing" (multipart to `/ask`).

## Demo links
`?q=demo:demo_01` (beat 1), `demo:demo_02` (beat 2), `demo:demo_11` (beat 3, Finnish; add `&model=gemma-base` to show the base model), `demo:demo_12` (beat 4, toilets), `demo:demo_08` (beat 5, A-801), `demo:demo_u2` (beat 7, abstain), `judge:judge_u01` (unlabelled Helsinki drawing).
Add `&theme=light` to pin light mode on a projector.
