# 01 Candidate Connectivity

Only candidate connectivity changes. Air/wall priors and branch dynamics are held constant. Local connectivity excludes cross-floor zone pairs and remote plenum paths; it does not supply exact within-floor adjacency.

## Matched results

| case | selection | interzone_edges | states | independent_fitted_parameters | validation_24h_C | test_24h_C | test_72h_C |
| --- | --- | --- | --- | --- | --- | --- | --- |
| unrestricted_2R1C_wall | best_accuracy | 0 | 37 | 61 | 0.6111 | 0.54599 | 0.55695 |
| unrestricted_2R1C_wall | sparse | 0 | 36 | 58 | 0.62602 | 0.55624 | 0.5684 |
| local_2R1C_wall | best_accuracy | 9 | 45 | 65 | 0.60697 | 0.53602 | 0.55144 |
| local_2R1C_wall | sparse | 0 | 37 | 57 | 0.6135 | 0.54463 | 0.55511 |

For the minimum-validation-error models, the final listed variant changes 24-hour test RMSE by -0.00997 C relative to the first listed variant. This is descriptive exploratory evidence, not a significance test. The sparse selection is a different result and must not be labelled the minimum-error model.

## Interpretation limits

- Training and evaluation episodes are identical across variants; test periods have been used in earlier experiments.
- Report full lambda paths, not just one selected model. Supports need not be nested as lambda increases.
- Zero direct interzone edges does not imply zero physical heat exchange; measured boundary temperatures and supplied heat inputs can explain shared variation.
- Predictions use realized future heat inputs and boundary temperatures, with no observer during each rollout. This does not demonstrate response to new HVAC commands.
- State count is a computational proxy, not measured MPC solve time. These models are not installed in the MPC.
- Parameter count excludes imposed capacitances and derived storage capacitances. A validation-selected common time constant is an additional hyperparameter.
- Boundary and slab parameters retain broad bounds; interior-wall information is not transferred to slabs or outdoor constructions.

Plot zones are ['PERIMETER_BOT_ZN_3', 'PERIMETER_MID_ZN_1'], selected from the shared reference model's validation errors. The same first February and August test episodes are used throughout.
