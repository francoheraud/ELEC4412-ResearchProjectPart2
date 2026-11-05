# Reproducing the selected research

## Review the saved evidence

Open the RC Overview and MPC demonstration notebooks linked in the root README.
All cached notebook figures and summary tables are included. For the branch-order
study, use the `3R2C_extension/02_branch_complexity/Review.ipynb` notebook; the
original two-family comparison is also retained. `best_accuracy` is the minimum
validation-error selection; `sparse` is a separate complexity-based selection.

## Offline identification

The prepared ten-minute arrays are in `rc-modelling/results/prepared_data.npz`.
They retain their original bytes and SHA256. The source preparation code is
`rc-modelling/rc_workflow/` and `run_workflow.py`. The final matched experiment
is `rc-modelling/matched_investigations/rc_engine.py` with
`run_investigations.py`; the extension has its own corresponding engine.

To repeat fitting without overwriting archived results, from the repository root:

```sh
python tools/rerun_rc.py --label repeat_rc
python tools/rerun_rc.py --label repeat_3r2c --extension
```

These commands make isolated working copies under `reruns/`, reuse supplied
inputs, and invoke the original fitting routines. The extension retains the
saved 1R/2R1C comparators and fits only 3R2C. Existing result labels are rejected.
Fitting uses QR compression, constrained least squares, conditional-bound
coordinate search where applicable, and exact matrix-exponential discretisation.

Prior inputs are in each experiment's `inputs/`. They come from IDF zone
volumes, assumed air properties, and one representative construction. The small
original prior records under `physical_priors/` are prerequisites used by the
runner; this directory is not a complete archive of earlier prior experiments.

## EnergyPlus control reruns

Install EnergyPlus 25.2. From `mpc/fair_control_comparison`, run:

```sh
python run_fair.py --band original --controller reactive --label repeat_reactive --energyplus-root "C:/EnergyPlusV25-2-0"
python run_fair.py --band original --controller hvac_mpc --label repeat_hvac_mpc --energyplus-root "C:/EnergyPlusV25-2-0"
python run_fair.py --band original --controller coordinated --label repeat_coordinated --energyplus-root "C:/EnergyPlusV25-2-0"
```

The default implementation root is this checkout. `--implementation` can select
another complete copy. `--energyplus-root` or the `ENERGYPLUS_ROOT` environment
variable selects the installation. The default installation remains
`C:/EnergyPlusV25-2-0`. Paths containing spaces must be quoted.

Each command uses a fresh label and retains the saved thesis results. It creates
its own instrumented plant, source snapshot, protocol, component measurements
and summary. `model/thermal_model.npz` is copied unchanged into each run.
The 80% NMC source IDF has approximately 207 kWh; the study runner applies the
recorded capacity multiplier of two, giving approximately 413 kWh at 50 kW.
The already-expanded `_2x.idf` is included for inspection; do not double it again.

The final controller is `MatchedRun` in `fair_control.py`, inheriting the
shared-system candidate rollout in `advanced_control.py`. It combines finite
HVAC-policy evaluation with the battery LP in `bess_mpc.py`; the LP uses SciPy
HiGHS. `mpc_workflow/thermal.py` contains the frozen RC predictor and heat-bias
observer. Local EnergyPlus HVAC control remains active.

`mpc/results/` and `results_v2/electrical_model.json` contain the shared forecast
and calibration prerequisites referenced by setup. The final shared-system
electrical coefficients are `extended_electrical_model.json`. These are frozen
calibrations; the repository does not include the entire earlier calibration
simulation archive. Supplied future profiles are a benchmark assumption.

The source `analyse_fair.py --partial` can analyse completed fresh case folders
when their EnergyPlus databases exist. It updates local aggregate CSVs; back up
the saved aggregates first if using it in this checkout. Archived SQL databases
are omitted, so SQL-dependent re-audits require new plant runs.

## Figures

The MPC notebook can regenerate thesis figures from the distributed principal
traces. The original plotting scripts require Times New Roman; install it
locally or explicitly choose another font in the plotting source. No rerun is
needed to read the exported PNG/PDF figures. The original ten-case audit CSVs
are retained, while figures select only the three original-bound cases.

## Packaging changes

- Only entry-point path handling, report links and notebook launch/help text were adapted.
  The numerical RC engines, thermal model arrays, controller algorithms,
  objective weights and archived outputs were not retuned.
- Original `.py` bytes and model hashes are preserved except the documented
  portability edits to `run.py`, `run_fair.py`, `mpc_workflow/config.py` and
  notebook/report packaging in `write_fair_report.py`.
- Notebook outputs and local kernel metadata were cleared for a clean checkout.
- Original provenance JSON may contain historical absolute paths. These identify
  where a saved experiment ran; they are not all current executable paths.
- `publication_manifest.json` records current file hashes and the source hash
  for copied files. Full exploratory histories remain in the earlier archive.

## Numerical checks

```sh
cd rc-modelling/matched_investigations
python -m unittest test_engine -v
cd ../../mpc/fair_control_comparison
python -m unittest test_fair test_battery_feedback test_export_pricing test_advanced -v
```

These are numerical and implementation checks, not a new full EnergyPlus run
or independent replication of all thesis findings. The publication preparation
also compiles Python/notebook cells and executes the cached review cells
sequentially with IPython display objects (without launching a Jupyter kernel).
See `PUBLICATION_CHECKS.json` for the recorded checks.
