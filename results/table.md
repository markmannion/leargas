**heldout_raster**: acc (n per row from the first model)

| source / type | n | prior | gemma-base |
|---|---:|---:|---:|
| cubicasa5k/count | 600 | **56.2%** | 35.8% |
| swiss_dwellings/area_printed | 66 | 1.5% | **22.7%** |
| swiss_dwellings/area_unprinted | 68 | **2.9%** | 0.0% |
| swiss_dwellings/count | 266 | 22.6% | **37.6%** |
| **ALL** | 1000 | **40.0%** | 33.0% |
| median latency | | – | 1.2s |

**judge**: acc (n per row from the first model)

| source / type | n | prior | gemma-base |
|---|---:|---:|---:|
| cubicasa5k/area | 2 | 0.0% | **100.0%** |
| cubicasa5k/count | 8 | 12.5% | **62.5%** |
| finna/area | 1 | **100.0%** | 0.0% |
| finna/count | 2 | 0.0% | **100.0%** |
| habs/count | 1 | **0.0%** | **0.0%** |
| habs/length | 1 | **0.0%** | **0.0%** |
| ifc_models/count | 2 | **0.0%** | **0.0%** |
| swiss_dwellings/area_printed | 5 | 0.0% | **20.0%** |
| swiss_dwellings/count | 8 | 37.5% | **62.5%** |
| **ALL** | 30 | 16.7% | **50.0%** |
| median latency | | – | 0.4s |

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
