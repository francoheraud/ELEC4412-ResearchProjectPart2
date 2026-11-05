# 3R2C branch-storage sensitivity experiment

Open `02_branch_complexity/Review.ipynb` to review cached results. It displays
the same 1R/2R1C comparators as the original matched investigations alongside
a newly fitted 3R2C model. No historical results or MPC models are modified.

## Reproduce

From this directory, use a Python environment with `requirements.txt` installed:

```powershell
python run_3r2c.py --implementation "C:/Users/Franc/OneDrive/Desktop/Uni Documents/2026/Thesis/building_semantic/ornl_frp/implementation"
python -m unittest test_engine test_3r2c -v
```

Completed 3R2C fits are cached. The runner refuses to reuse its own fit if
the engine, data, configuration, lambda grid or differentiation methods have
changed. The copied 1R/2R1C cases intentionally retain their original contracts:
they are frozen comparisons, not new fits with this engine. The baseline-matrix
test confirms their state-space matrices are reproduced by the extension.
`run_investigations.py` supplies fitting functions; use `run_3r2c.py` as the entry point.

## Exact branch definition

The original symmetric 2R1C branch has two resistances `Rtotal/2` and one
capacitance `Ctotal`. The new 3R2C branch has three resistances `Rtotal/3`
and two capacitances `Ctotal/2`. Here `Rtotal = 1/G` and
`Ctotal = 4*G*tau_reference`, exactly matching the total resistance and
capacitance of the 2R1C branch for the same conductance.

For endpoints Ti and Tj and internal temperatures z1 and z2:

```
(Ctotal/2) dz1/dt = 3G(Ti - z1) + 3G(z2 - z1)
(Ctotal/2) dz2/dt = 3G(z1 - z2) + 3G(Tj - z2)
```

For a boundary branch Tj is a supplied boundary temperature. This symmetric
parameter tying leaves only G to be fitted per branch. Each retained storage
branch now adds two dynamic states, not two independently fitted capacitances.
The state count changes even when independent parameter count does not.

`tau_interzone_hours` / `tau_hours` in legacy-format CSVs mean the **reference
scale Ctotal/(4G)**. For 3R2C they are not branch modal time constants. With
fixed endpoints the slow and fast modes have time constants `2*tau_reference/3`
and `2*tau_reference/9`. For the representative wall these are approximately
19.25 and 6.42 minutes. Outdoor/slab reference tau remains 12 h, giving
clamped-endpoint modes of 8 and 2.667 h. Full-network modes differ.

## Matched protocol

- Same 15 zone-air capacitances fixed from IDF volumes, local geometric mask
  (30 candidate interzone and 25 zone/plenum branches), and wall prior.
- Same conditional wall G range, 0.5 to 2 times the reference G, or zero.
  Both storage masses scale together with this conductance.
- All designated storage branches change together: interzone, outdoor envelope,
  and lower-plenum slab. Direct outdoor, upper-plenum and ground paths stay 1R.
- Topology is rediscovered using 18 lambda values and both trapezoidal and
  Savitzky-Golay equations (36 new lambda evaluations). Retained parameters
  are refitted without the sparsity penalty.
- Same seasonal training/validation/test blocks, 72-hour conditioning,
  known future inputs, and 1/6/24/72-hour predictions as the original study.
- Minimum-error selection uses 24-hour **validation** RMSE, never test RMSE.
  The separate complexity selection uses fewest states within 0.02 C of the
  minimum validation RMSE, then active conductances and validation error.
- Historical baseline outputs are reused unchanged, not rerun or retuned.

## Interpretation boundaries

This is one symmetric, tied-parameter 3R2C sensitivity case. It does not test
all possible resistance/capacitance allocations, nor add more independently
adjustable RC parameters. Since topology is rediscovered, it is a model-family
comparison rather than a fixed-topology order comparison. The prior's known
area-transfer limitation remains: its effective-area range may exclude actual
small-wall properties. Increased order does not repair this constraint.

The faster wall mode is shorter than the sampling interval. Exact discretisation
avoids an explicit integration stability restriction, but cannot restore
information missing from sampled observations. Prediction error is not evidence
of material-property recovery or closed-loop MPC performance. Reused test
periods make this an exploratory comparison, not a fresh blind validation.

## Outputs

- `RESULTS.md`: numerical summary and interpretation.
- `02_branch_complexity/summary.csv`: aggregate metrics and complexity.
- `02_branch_complexity/per_zone_RMSE_24h.csv`: zone-by-zone RMSE.
- `02_branch_complexity/lambda_path.csv`: complete regularisation paths.
- `02_branch_complexity/all_branch_parameters.csv`: retained/excluded branches.
- `cases/local_3R2C_wall/branch_parameters.csv`: 3R2C-specific per-section
  R/C values, total branch R/C and clamped-endpoint modal times.
- `02_branch_complexity/figures`: graph, lambda and prediction figures
  exported as PDF, SVG and PNG. Use PDF in LaTeX for vector rendering.
- `extension_protocol.json`, `verification.json`, `delivery_verification.json`:
  provenance and numerical checks.

The fitted continuous/discrete matrices and selected parameter vectors are in
`cases/local_3R2C_wall/{best_accuracy,sparse}.npz`. In those files, zones come
first, followed by each retained branch's two internal states in branch order.
`storage_branch_indices` lists retained storage branches;
`storage_trace_columns` maps each dynamic storage state to reconstructed traces.
