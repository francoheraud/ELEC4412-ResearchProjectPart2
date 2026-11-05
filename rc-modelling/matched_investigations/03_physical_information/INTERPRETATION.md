# 03 Physical Information

The free-air and air-only configurations share the same broad bounds and interzone tau grid. The wall-prior configuration additionally ties G and C through a representative construction, fixes interzone tau, and imposes conditional conductance bounds. Improved agreement with imposed values is not independent recovery of physical properties.

## Matched results

| case | selection | interzone_edges | states | independent_fitted_parameters | validation_24h_C | test_24h_C | test_72h_C |
| --- | --- | --- | --- | --- | --- | --- | --- |
| local_2R1C_free_air | best_accuracy | 13 | 50 | 83 | 0.5959 | 0.53 | 0.54459 |
| local_2R1C_free_air | sparse | 0 | 37 | 72 | 0.61294 | 0.54514 | 0.55631 |
| local_2R1C_air_only | best_accuracy | 11 | 47 | 67 | 0.6017 | 0.53615 | 0.55061 |
| local_2R1C_air_only | sparse | 0 | 37 | 57 | 0.6135 | 0.54463 | 0.55511 |
| local_2R1C_wall | best_accuracy | 9 | 45 | 65 | 0.60697 | 0.53602 | 0.55144 |
| local_2R1C_wall | sparse | 0 | 37 | 57 | 0.6135 | 0.54463 | 0.55511 |

For the minimum-validation-error models, the final listed variant changes 24-hour test RMSE by +0.00602 C relative to the first listed variant. This is descriptive exploratory evidence, not a significance test. The sparse selection is a different result and must not be labelled the minimum-error model.

## Interpretation limits

- Training and evaluation episodes are identical across variants; test periods have been used in earlier experiments.
- Report full lambda paths, not just one selected model. Supports need not be nested as lambda increases.
- Zero direct interzone edges does not imply zero physical heat exchange; measured boundary temperatures and supplied heat inputs can explain shared variation.
- Predictions use realized future heat inputs and boundary temperatures, with no observer during each rollout. This does not demonstrate response to new HVAC commands.
- State count is a computational proxy, not measured MPC solve time. These models are not installed in the MPC.
- Parameter count excludes imposed capacitances and derived storage capacitances. A validation-selected common time constant is an additional hyperparameter.
- Boundary and slab parameters retain broad bounds; interior-wall information is not transferred to slabs or outdoor constructions.

Plot zones are ['PERIMETER_BOT_ZN_3', 'PERIMETER_MID_ZN_1'], selected from the shared reference model's validation errors. The same first February and August test episodes are used throughout.
