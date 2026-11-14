# Léargas

Léargas answers questions about construction drawings. Léargas is the Irish word for insight.
It shows the evidence for each answer on the drawing.
If it cannot find the evidence, it tells you. It does not guess.

We made Léargas for the Stoa track at Junction 2026.

## What it does

1. You select a drawing, or you upload your own drawing.
2. You ask a question. You can type it or say it.
3. Léargas gives an answer, a status and the evidence.
4. The evidence shows on the drawing as boxes, outlines or points.

Example questions:

- "How many windows are on this floor plan?"
- "What is the floor area of the library?"
- "How many metres of skirting board does the fitness room need?"
- "How many pipe supports are on this sheet?"
- "What is the slab area by type?"

## The answer status

Each answer has one of four statuses.

| Status | What it means |
|---|---|
| Verified | One reliable source gave the answer, or two sources gave the same answer. |
| Partial | There is an answer, but it is an estimate. Check the evidence. |
| Disagreement | Two sources gave different answers. Check the drawing. |
| Cannot verify | No source is sure. Léargas gives no answer. |

## Features

### Answers from CAD and BIM files

If a drawing has a DXF file or an IFC model, Léargas reads the geometry from that file.
It counts items and measures areas from the real lines and shapes.
These answers are the most reliable.

### Sheet reader for large drawing sheets

Many drawings are large sheets with small text, such as a PDF page or a large scan.
The sheet reader reads the text and the lines on the full sheet. It does not make the sheet smaller first.

The sheet reader can:

- Read values that are printed on the sheet, for example a table of floor areas.
- Count equipment tags, for example pumps (FP-1, FP-2) or pipe supports (PS-1, PS-2).
- Count room labels, for example all rooms with the name "Group Room".
- Find the drawing scale from a scale bar, a scale ratio (1:200) or a chain of dimensions.
- Measure the floor area of a room from its walls and the drawing scale.
- Measure skirting board length: the room perimeter minus the door openings.
- Count door and window openings in the walls.
- Find slab callouts (thickness, bar size and spacing) and the area near each callout.
- Find the largest printed dimension, for example the overall length of a building.

Measured values (areas, lengths and openings) are estimates. They have the status "Partial".
A value that is printed on the sheet and read clearly can have the status "Verified".

### Vision model for floor plan images

For small floor plan images, a vision model reads the image.
The model is Gemma 4. We fine-tuned it on the training part of the challenge dataset.
The model also gives a confidence value. We measured where that value is reliable.
Below that level, the answer becomes "Partial" or "Cannot verify".

### Questions in many languages

You can ask questions in the languages of the dataset, for example English, German, French and Finnish.
A language model reads questions that do not match a known pattern.

### Other features

- Upload: add your own PNG, JPG, PDF, DXF or IFC file (maximum 60 MB).
- Region: draw a box on the sheet to ask about one part of the drawing only.
- Voice: say your question and hear the answer (needs an ElevenLabs key).

## Limits

- The sheet reader uses text recognition (OCR). It can miss text or read it incorrectly.
- Room areas need closed walls. If a room is open to a corridor, the result can include the corridor. Léargas then tells you that the rooms can be merged.
- Door and window counts on large sheets are estimates. Double doors count as one opening.
- Slab areas can include only one panel of a slab. Always check the highlighted regions.
- The vision model is weak on door and window counts in small images. These answers often get "Cannot verify".

## How to run it

All commands start from the repository root.

1. Get access to the private dataset on Hugging Face. Ask to join the `leargas` organisation.
2. Download the dataset:

   ```bash
   hf download leargas/junction-dataset --repo-type=dataset --local-dir datasets/junction-dataset
   ```

3. Install the backend:

   ```bash
   pip install -r backend/requirements-dxf.txt -r backend/requirements-ifc.txt -r backend/requirements-sheet.txt
   ```

4. Build the question templates (do this one time on each machine):

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

7. Optional: to use the vision model, set `MODEL_BASE_URL` and `MODEL_API_KEY` in `.env`. See `.env.example`.
   If port 8000 is in use (for example by an SSH tunnel to the model server), start the backend on port 8100.
   Then set `LEARGAS_API=http://127.0.0.1:8100` before you start the frontend.

## How to deploy it

The frontend runs on Vercel. The backend runs on the Verda GPU box, next to the model server.
Caddy gives the backend an https address. The address uses the box IP, for example `1-2-3-4.sslip.io` for the IP 1.2.3.4.

1. On the box, run the backend script. It installs the backend, downloads the dataset and starts the services.
   The services start again after a crash or a reboot. Ports 80 and 443 must be open.

   ```bash
   ssh <box> "LEARGAS_DOMAIN=<box-ip-with-dashes>.sslip.io bash -s" < infra/serve_backend.sh
   ```

2. On Vercel, import this repository. Set the root directory to `frontend`.
   Add the environment variable `VITE_API_BASE=https://<box-ip-with-dashes>.sslip.io`, then deploy.

To update the backend, run the script again. The address does not change.

### Other option: Hugging Face Docker Space (paid plan)

The Space downloads the dataset from the private dataset at startup.

1. On Hugging Face, create a new Space with the Docker SDK (blank template). The CPU upgrade makes OCR faster.
   Optional: add persistent storage, so the Space does not download the dataset again after each restart.
2. In the Space settings, add these secrets:
   - `HF_TOKEN`: a read token from a member of the `leargas` organisation.
   - Optional: `MODEL_BASE_URL` and `MODEL_API_KEY` for the vision model, `ELEVENLABS_API_KEY` for voice.
3. Push the backend code to the Space (log in first with `hf auth login`):

   ```bash
   deploy/push_space.sh <owner>/<space-name>
   ```

4. Wait until the Space shows "Running". Check `https://<owner>-<space-name>.hf.space/health`.
5. On Vercel, import this repository. Set the root directory to `frontend`.
   Add the environment variable `VITE_API_BASE=https://<owner>-<space-name>.hf.space`, then deploy.

Users can browse the dataset drawings and upload their own files in the app. The dataset files stay private.

## Where the code is

| Folder | What it contains |
|---|---|
| `backend/` | The API, the question parser, the router and the engines (DXF, IFC, sheet reader). |
| `backend/app/sheet/` | The sheet reader. |
| `frontend/` | The web interface (React). |
| `model/` | Training and evaluation of the vision model. |
| `infra/` | Scripts for the GPU server that runs the model. |
| `eval/` | Scoring scripts. |
| `contracts/` | The answer format as JSON Schema. |

## Data licence

The challenge dataset is for non-commercial use at Junction only.
Do not commit dataset files to this repository.
Keep all models and files made from the dataset private on Hugging Face.
