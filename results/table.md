**heldout_raster**: acc (n per row from the first model)

| source / type | n | prior | gemma-e2b | gemma-ft-e2b | gemma-base | gemma-ft | gemma-ft-run2 | gemma-base-1120 | gemma-base-crop | gemma-ft-cc | gemma-ft-routed | gemma-soup | gemma-super |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cubicasa5k/count | 600 | 56.2% | 43.5% | 72.5% | 35.8% | 74.3% | 73.3% | 36.3% | – | **77.0%** | 76.7% | 74.5% | 75.7% |
| swiss_dwellings/area_printed | 66 | 1.5% | 21.2% | 25.8% | 22.7% | 30.3% | **37.9%** | 25.8% | 27.3% | 28.8% | 30.3% | 31.8% | 34.8% |
| swiss_dwellings/area_unprinted | 68 | 2.9% | 2.9% | 1.5% | 0.0% | 0.0% | 0.0% | 1.5% | **4.4%** | 1.5% | 0.0% | 0.0% | 0.0% |
| swiss_dwellings/count | 266 | 22.6% | 27.4% | 47.7% | 37.6% | **54.1%** | 47.4% | 38.0% | 34.2% | 53.4% | **54.1%** | 51.5% | 50.4% |
| **ALL** | 1000 | 40.0% | 35.0% | 58.0% | 33.0% | 61.0% | 59.1% | 33.7% | 28.0% | **62.4%** | **62.4%** | 60.5% | 61.1% |
| median latency | | – | 1.0s | 0.9s | 1.2s | 1.0s | 1.1s | 6.5s | 0.9s | 1.2s | – | 1.1s | 1.1s |

**judge**: acc (n per row from the first model)

| source / type | n | prior | gemma-e2b | gemma-ft-e2b | gemma-base | gemma-ft | gemma-ft-run2 | gemma-ft-cc | gemma-ft-routed | gemma-soup | gemma-super |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cubicasa5k/area | 2 | 0.0% | 50.0% | **100.0%** | **100.0%** | **100.0%** | **100.0%** | **100.0%** | **100.0%** | **100.0%** | **100.0%** |
| cubicasa5k/count | 8 | 12.5% | 25.0% | 25.0% | **62.5%** | 50.0% | 50.0% | 50.0% | 50.0% | **62.5%** | **62.5%** |
| finna/area | 1 | **100.0%** | 0.0% | 0.0% | 0.0% | **100.0%** | 0.0% | **100.0%** | **100.0%** | **100.0%** | **100.0%** |
| finna/count | 2 | 0.0% | **100.0%** | **100.0%** | **100.0%** | **100.0%** | **100.0%** | **100.0%** | **100.0%** | **100.0%** | **100.0%** |
| habs/count | 1 | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** |
| habs/length | 1 | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** |
| ifc_models/count | 2 | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** |
| swiss_dwellings/area_printed | 5 | 0.0% | 40.0% | 40.0% | 20.0% | **60.0%** | 40.0% | 40.0% | **60.0%** | 40.0% | **60.0%** |
| swiss_dwellings/count | 8 | 37.5% | 37.5% | 62.5% | 62.5% | 50.0% | 50.0% | 50.0% | 50.0% | 50.0% | **75.0%** |
| **ALL** | 30 | 16.7% | 33.3% | 43.3% | 50.0% | 53.3% | 46.7% | 50.0% | 53.3% | 53.3% | **63.3%** |
| median latency | | – | 0.3s | 0.3s | 0.4s | 0.3s | 0.3s | 0.3s | – | 0.3s | 0.3s |

**heldout_all_prior**: acc (n per row from the first model)

| source / type | n | prior |
|---|---:|---:|
| cubicasa5k/count | 4232 | 56.0% |
| ifc_bench/text | 134 | 0.0% |
| ifc_models/area | 416 | 35.1% |
| ifc_models/count | 138 | 24.6% |
| ifc_models/length | 14 | 57.1% |
| ifc_models/volume | 30 | 0.0% |
| opening_design/area | 9 | 0.0% |
| opening_design/count | 39 | 0.0% |
| opening_design/text | 16 | 0.0% |
| swiss_dwellings/area_printed | 150 | 0.7% |
| swiss_dwellings/area_unprinted | 446 | 4.5% |
| swiss_dwellings/count | 1318 | 21.4% |
| **ALL** | 6942 | 41.2% |
