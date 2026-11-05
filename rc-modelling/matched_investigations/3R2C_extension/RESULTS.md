# 3R2C sensitivity result

The symmetric 3R2C extension does not improve the selected 24-hour validation or test RMSE over the matched 2R1C model. All models below are selected by validation error, not by test results.

| Model | lambda_value | interzone_edges | states | independent_fitted_parameters | validation_24h_C | test_1h_C | test_6h_C | test_24h_C | test_72h_C |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1R | 0 | 0 | 15 | 46 | 0.69093 | 0.39321 | 0.50404 | 0.64253 | 0.64367 |
| 2R1C | 0.01 | 9 | 45 | 65 | 0.60697 | 0.28624 | 0.39503 | 0.53602 | 0.55144 |
| 3R2C | 0.1 | 0 | 57 | 57 | 0.6329 | 0.28763 | 0.3811 | 0.54498 | 0.5616 |

Relative to 2R1C, 3R2C changes 24-hour test RMSE by +0.008954 C (+1.67%). State count rises from 45 to 57. Six-hour test RMSE improves from 0.395030 to 0.381101 C; one-hour and 72-hour test errors are slightly higher. There is no consistent improvement across horizons.

## Regularisation path

For Savitzky-Golay, lambda=0 retains 11 interzone branches / 79 states with 0.648981 C validation RMSE. Lambda=0.01 retains 10 / 77 with 0.647900 C; lambda=0.031623 retains 8 / 73 with 0.648384 C; lambda=0.1 retains zero / 57 with 0.632899 C. The minimum-error and complexity-selected choices coincide in this extension. Zero interzone branches does not mean there is no storage: the selected model has 21 active boundary-storage branches with two masses each, plus 15 air states.

## What this does and does not show

- This tests equal R/3 sections and equal Ctotal/2 masses while preserving each branch's total resistance and capacitance assumptions. It does not fit arbitrary resistance ratios, capacity ratios, or additional independent parameters.
- The 57 versus 65 independently fitted parameters in the selected 3R2C versus 2R1C models reflect their different retained supports. For an identical retained support, their independent parameter counts would match.
- All storage categories change, and topology is rediscovered. This is not evidence specifically against 3R2C interzone walls or against all higher-order RC models.
- The known representative-wall area-bound mismatch remains unchanged. Changing storage order alone cannot repair that assumption.
- The 3R2C wall's clamped-endpoint fast mode is about 6.42 minutes, shorter than the 10-minute sampling interval. Limited temporal resolution is a possible limitation, not an established cause of the measured error.
- Known future heat inputs and boundary temperatures, reused test periods, and fixed air capacities are shared with the previous comparison. This is conditional predictive validation, not a control experiment or a statistical significance claim.
- These results provide no 24-hour prediction-based reason to replace the tested 2R1C formulation with this particular 3R2C configuration. They do not by themselves show that 2R1C is optimal for MPC.

The notebook and PDF/SVG/PNG figures are in `02_branch_complexity`. Full branch parameters include total R/C, per-section R/C and reference/modal time scales. No MPC model was changed.
