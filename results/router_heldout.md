# Router on the held-out split (engine=auto, geometry only)

Held-out drawings from `model.make_split` (seed 1337) that are on disk locally: 2,646 questions over
72 drawings. No Gemma endpoint was configured, so this is the geometry track alone (DXF + IFC).
CubiCasa and opening_design held-out drawings are not on disk here and are not included.

    python backend/eval_run.py --gold datasets/junction-dataset/questions.jsonl \
        --split data/runs/heldout_paths.txt --out data/runs/auto.jsonl --api http://127.0.0.1:8000

| bucket | n | v1 accuracy | **v2 accuracy** | v2 precision |
|---|---:|---:|---:|---:|
| **overall (scored)** | 2,512 | 93.1% | **98.2%** | **100.0%** |
| ifc_models | 598 | 100.0% | 100.0% | 100.0% |
| swiss_dwellings | 1,914 | 90.9% | 97.6% | 100.0% |
| area | 1,012 | 91.1% | 95.8% | 100.0% |
| count | 1,456 | 94.2% | 99.7% | 100.0% |
| length | 14 | 100.0% | 100.0% | 100.0% |
| volume | 30 | 100.0% | 100.0% | 100.0% |

Tolerance 2% (official); identical at 1%. Zero wrong answers in either version: every miss is a
`cannot_verify`. ifc_bench free-text questions (134) are answered `cannot_verify` and are not scored.

## v1 → v2: recovering DXF refusals without losing precision

All rules were developed against the 35,670 **train** Swiss questions (88.7% → 97.7%, zero wrong at
every step) and the held-out set was run once at the end.

- **Fixtures.** An unclassified fixture outline used to block every fixture count on the drawing.
  Now it blocks a count only if it contains that fixture's hallmark stroke (69-point tub bowl,
  48-point WC/basin oval, 5-point shower tray; a lone drain circle for tubs/showers). Empty
  rectangles and cooktop circles no longer block WC/basin/tub counts.
- **Indoor/outdoor.** Numbered rooms without a name are classified indoor when ≥97% of their
  outline borders other rooms within a wall's width (60 cm); balconies sit on the facade and
  don't. Anything less enclosed stays unclassified. Added arcade-type outdoor labels
  (Arkade, portico, Laubengang, coursive, ...).
- **Unit fragments.** Unlabelled unit outlines only block apartment areas when a numbered room
  lies inside them; shaft-sized fragments no longer do.

Remaining Swiss abstentions on held-out: 30 indoor/outdoor, 12 unit fragments, 4 fixtures.

Throughput ~18 q/s at concurrency 8 on a laptop; latency p50 9 ms, p95 1.2 s (first parse of a DXF/IFC).
