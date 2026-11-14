# Router on the held-out split (engine=auto, geometry only)

Run on Sat 14 Nov, held-out drawings from `model.make_split` (seed 1337) that are on disk locally:
2,646 questions over 72 drawings. No Gemma endpoint was configured, so this is the geometry track
alone (DXF + IFC). CubiCasa and opening_design held-out drawings are not on disk here and are not included.

    python backend/eval_run.py --gold datasets/junction-dataset/questions.jsonl \
        --split data/runs/heldout_paths.txt --out data/runs/auto.jsonl --api http://127.0.0.1:8000

| bucket | n | accuracy | coverage | precision |
|---|---:|---:|---:|---:|
| **overall (scored)** | 2,512 | **93.1%** | 93.1% | **100.0%** |
| ifc_models | 598 | 100.0% | 100.0% | 100.0% |
| swiss_dwellings | 1,914 | 90.9% | 90.9% | 100.0% |
| area | 1,012 | 91.1% | 91.1% | 100.0% |
| count | 1,456 | 94.2% | 94.2% | 100.0% |
| length | 14 | 100.0% | 100.0% | 100.0% |
| volume | 30 | 100.0% | 100.0% | 100.0% |

Tolerance 2% (official); identical at 1%. Zero wrong answers: every miss is a `cannot_verify`.
ifc_bench free-text questions (134) are answered `cannot_verify` and are not scored.

The 174 Swiss abstentions are all deliberate refusals by the DXF engine:

| reason | n |
|---|---:|
| Unclassified fixture symbols could affect this count (WC, washbasin, bathtub counts) | 84 |
| Indoor/outdoor classification is incomplete (numbered-indoor and apartment areas) | 70 |
| Unlabelled unit fragments could belong to the requested apartment | 20 |

Throughput 20 q/s at concurrency 8 on a laptop; latency p50 9 ms, p95 1.9 s (first parse of a DXF/IFC).
