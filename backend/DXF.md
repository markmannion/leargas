# Swiss DXF engine

Task 2 implementation: `app/dxf.py`, with a command line interface in
`dxf_engine.py`. It operates independently of the FastAPI scaffold and scorer.

From the repository root:

```bash
.venv/bin/pip install -r backend/requirements-dxf.txt
.venv/bin/python backend/dxf_engine.py batch \
  datasets/junction-dataset/data/swiss_dwellings --expected-count 1040 \
  --output datasets/junction-dataset/derived/swiss-dxf.jsonl \
  --report datasets/junction-dataset/derived/swiss-dxf-report.json

.venv/bin/python backend/dxf_engine.py query \
  data/swiss_dwellings/site3387_bldg5238_floor23498.pdf \
  --dataset-root datasets/junction-dataset \
  '{"operation":"count","kind":"window"}'
```

The full dataset was downloaded from the private `leargas/junction-dataset`
repository at revision `f0143ac1b00cc14ecc0ba985eb438b36be32ca81`.
`datasets/junction-dataset/dxf-download-manifest.json` records all 1,040 paths.
Source files and derived JSONL/report files remain under gitignored `datasets/`.
The original preview archive is `/Users/harry/Downloads/junction-dataset-preview.zip`.

## Integration interface

With `backend` on the Python import path:

```python
from app.dxf import CannotVerify, Query, parse_dxf, resolve_twin

path = resolve_twin("data/swiss_dwellings/site3387_bldg5238_floor23498.png",
                    "datasets/junction-dataset")
drawing = parse_dxf(path)
windows = drawing.query(Query("count", "window"))
room = drawing.query(Query("area", "room", room_id="1.01"))
bedrooms = drawing.query(Query("count", "room", label="Schlafzimmer"))
net_apartment = drawing.query(Query("area", "room", unit_id="A", indoor_only=True))
printed_only = drawing.query(Query("area", "room", room_id="1.01", area_source="printed"))
```

`Result` supplies `value`, `unit`, `item_ids`, and `explanation`. `Drawing.to_dict()`
supplies serializable objects, original entity handles, layer/type inventories,
warnings, and source attribution. Object IDs resolve the result back to CAD
polygons. The caller should map `CannotVerify` to the shared answer contract's
`cannot_verify`; file I/O and DXF syntax errors also need handling at the boundary.

Queries support `count` for `room`, `unit`, `window`, `door`, `fixture`, `toilet`,
`washbasin`, `bathtub`, `shower`, `kitchen`, `stairs`, and `unknown_fixture`.
`washing_machine` is also exposed as a distinct fixture kind.
`area` supports rooms; `room_id`, exact `label` (Unicode normalized and case
insensitive), `unit_id`, and `indoor_only` filter room queries. A unit's net area
uses `kind="room", unit_id="A", indoor_only=True`. Other object types currently
support drawing-wide queries only; unsupported scopes refuse explicitly.
Natural-language translation is task 3 and is not implemented here.

## Extraction conventions

- `ROOM_OUTLINE`: valid closed outlines, excluding decorative two-point lines.
  Text is assigned to the smallest containing outline, so a lift inside a stair
  enclosure retains its own labels. Room number, name, printed m², polygon area,
  indoor/outdoor classification, and unit membership are retained separately.
  `interior_outline_ids` identifies smaller enclosed outlines (for example lift
  wells and shafts); polygon area subtracts their union. `points` retains the
  original exterior ring for future evidence registration.
- `ROOM_TEXT`: room numbers, names, decimal-point/comma m², and `App.`/`Whg.` unit
  labels. Commercial `Gewerbe` labels are not residential apartments.
- `UNIT_OUTLINE`: closed rings, including rings with repeated endpoints whose
  DXF closed flag is unset. Residential counts use labelled units; disconnected
  fragments and commercial outlines do not become extra apartments. Room
  membership requires a dominant polygon overlap, with ambiguous membership
  left unresolved. Apartment-area queries refuse when unlabelled unit fragments
  could make their totals incomplete.
- `WINDOW`: one closed outer outline per window; the two glazing lines are
  decoration. `DOOR`: one closed frame per door; leaves and swing arcs are
  decoration. Counts do not count raw entities.
- `FIXTURE`: outer outlines and contained components form symbols. Rounded tub
  bowls, oval WC/basin bowls, cistern lines, drains, shower trays, washing-machine
  diagonals, hobs, and stair treads distinguish supported fixture motifs, even
  when rotated.
  Unknown motifs and unassigned components remain visible in the extraction.
  Fixture counts refuse if unknown symbols could change the result.

Area queries default to `area_source="auto"`: prefer the printed m² and otherwise
calculate the room polygon area in metres. `printed` requires every selected
room to have an explicit label; `geometry` always uses the CAD polygon.
The result explanation identifies the basis. Totals are rounded only after summing.
Unlabelled numbered spaces cannot silently contribute to an indoor-only total.
The Swiss net-area convention also excludes gardens, patios, outdoor seating
areas and conservatories (`Wintergarten` / `Jardin d'hiver` / `Giardino d'inverno`).

This is a dataset-specific extractor: answering requires the Swiss Dwellings
attribution, known semantic layers, and metre units. Other DXFs expose their
layer inventory with `profile="unsupported"`. Curved, tilted, invalid, or unknown
semantic geometry refuses rather than being flattened or omitted silently.

Coordinates are **DXF world coordinates in metres, y up**. They are not normalized
image evidence. PNG/PDF registration and point-label export belong to task 4.
The current `/ask` endpoint is unchanged and does not invoke this engine yet.

Run checks with `.venv/bin/pytest backend/tests -q` from the repository root.

## Validation on the downloaded revision

- All **1,040 / 1,040 DXFs** parsed with the supported profile, with no file errors.
- Extracted **18,483 windows** and **31,928 doors**. Every drawing's English
  window and door count matched its dataset answer exactly.
- Development cross-check of the supported English question templates:
  **16,695 answers matched** (counts exact, areas within 2%); **2,097 refused**;
  no returned answer mismatched. This informed implementation and is **not a
  held-out benchmark** or validation of multilingual question translation.
- Two drawings have ambiguous unit labels and one has ambiguous room labels.
  Unknown fixture motifs remain in 375 drawings, where fixture queries refuse.
- **41 backend tests pass**, including 15 DXF tests.

Local artifacts: `datasets/junction-dataset/derived/swiss-dxf.jsonl`,
`swiss-dxf-report.json`, and `swiss-dxf-validation.json` in the same directory.
