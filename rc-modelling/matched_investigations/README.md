# Three matched RC identification investigations

These are **offline identification and prediction experiments using the existing
DOE Medium Office EnergyPlus dataset**. They do not rerun the EnergyPlus plant,
change the IDF, replace the MPC model, or implement 3R2C branches.

Start with `Overview.ipynb`, then open the `Review.ipynb` in each numbered folder.
The notebooks display cached results and figures and do not launch fitting jobs.

## Experiments

| Folder | Controlled question | Variants |
|---|---|---|
| `01_candidate_connectivity` | Effect of candidate connectivity with fixed branch dynamics and priors | Unrestricted versus same-floor/local-plenum; both use 2R1C storage, fixed air C and one wall prior |
| `02_branch_complexity` | Effect of branch representation under the same local geometry | 1R versus 2R1C; fixed air C and matching interzone resistance bounds |
| `03_physical_information` | Effect of limited engineering information | Estimated air C/no wall prior; fixed air C/no wall prior; fixed air C plus one wall prior |

The `local_2R1C_wall` case is the **same fitted reference** in all three
experiments. Five unique model variants generate three distinct comparisons;
the reference is not independently refitted three times.

## Model structure and what is held constant

- Fifteen occupied zones are dynamic states. Outdoor, three plenum and monthly
  IDF ground temperatures remain prescribed measured/supplied boundary inputs.
- Interzone branches are reciprocal. The local mask allows 30 same-floor pairs
  and 25 physically bordering zone/plenum pairs. It does not provide the actual
  within-floor shared-wall adjacency to the optimiser.
- The unrestricted mask allows all 105 zone pairs and 45 zone/plenum pairs.
  In this new matched experiment, a candidate path to a plenum on a lower floor
  uses a slab-type storage branch. Remote paths remain deliberately eligible.
  This is different from the old unrestricted experiment with all-1R plenums.
- The 2R1C family includes interzone storage, parallel direct/storage outdoor
  paths, and lower-plenum slab storage. Upper/other plenum and ground paths are
  1R. Outdoor and ground candidate eligibility is identical across masks;
  the mask is not a complete physical restriction on every boundary path.
- For the 1R comparison, all designated storage branches become direct links.
  Parallel outdoor paths are merged into one total conductance to avoid
  indistinguishable fitting columns. This evaluates total storage complexity,
  not just interzone wall order. Topology discovery repeats for each family.
- The one-wall prior supplies total G and C with effective-area factor 0.5--2.
  The wall was inferred from the IDF, not measured in a real building.
  Symmetric branch half-resistances are R_total/2; storage C=4G*tau.
  The prior fixes tau=C_ref/(4G_ref)=approximately 0.481192 hours. It applies
  only to interzone branches. In 1R, only its resistance bounds apply.
- No-wall variants select common interzone tau from 0.25, 1, 4 and 12 hours,
  using validation only. Adding the wall prior restricts the admissible
  time constant as well as G/C ranges: it is not just a change in the solver.
- Outdoor and slab tau are fixed at 12 hours, inherited from previous
  exploratory validation, across all 2R1C variants. They are assumptions,
  not independently recovered construction values.
- Estimated air C has broad bounds 0.01--1000 kWh/K; fixed air C uses zone
  volume, rho=1.2 kg/m3 and cp=1006 J/(kg K). These reference-condition values
  are not exact variable moist-air capacities. Other G bounds are 0--100
  kW/K, and two radiant/solar heat-input gains are bounded between 0 and 2.

## Common data and evaluation

Training uses days 1--14 of January, April, July and October. Validation uses
days 15--21 of those months. Test uses days 15--21 of February, May, August
and November. Every seasonal block supplies 72 hours of causal conditioning
before fitting/evaluation. Therefore its first three days are not scored.
Forecasts begin at daily intervals; each uses 1, 6, 24 or 72 hours.

Trapezoidal fitting uses a secant derivative and averages both interval
endpoints for temperatures and heat inputs. Savitzky--Golay uses degree two
and seven samples (60-minute span at ten-minute sampling). Both methods use
the exact same valid training indices. Filters do not cross calendar splits
or time gaps. Branch storage initialisation is causal within each split.

Each variant uses 18 lambda values: zero and 17 log-spaced values from 1e-6
to 100. The fitting objective is mean squared scalar heat-balance residual
(kW squared) plus lambda times the sum of total interzone conductances
(kW/K). Lambda therefore has units kW K under this convention. Boundary
conductances and gains are unpenalised. All discovered supports are refitted
without a sparsity penalty. A conductance tolerance of 1e-6 kW/K defines
absent branches consistently in figures and exported state matrices.

Without conditional wall bounds, fitting uses bounded least squares with a
linear-penalty target shift. With wall bounds, each interzone G belongs to
{0} union [0.5 G_ref, 2 G_ref]; multistart coordinate minimisation handles
this nonconvex feasible set. Zero-edge, full-edge and previous-lambda starts
are compared. The best converged training objective is retained. No global
optimality guarantee is made. QR compression preserves the objective,
including the constant residual component used in reported fit losses.

Two selections are exported for each variant:

1. `best_accuracy`: minimum 24-hour validation RMSE across lambda, method
   and available interzone time constants.
2. `sparse`: fewest states, then active conductances, then validation RMSE
   among candidates within 0.02 C of that variant's minimum validation RMSE.

Test predictions use exact matrix-exponential discretisation with supplied
interval-average future heat inputs and boundary temperatures. No temperature
reset or disturbance observer operates inside a forecast episode. Initial
storage temperatures use past measured temperatures, never future values.
The previous tests reused these seasonal periods, so findings are exploratory.

## Results and figures

Each numbered folder includes:

- `summary.csv`: selections, state/parameter counts, validation and test errors.
- `test_metrics.csv` and `per_zone_RMSE_24h.csv`: every zone and all horizons.
- `lambda_path.csv` and `edge_path.csv`: complete fits and branch evolution.
- `interzone_before_after.csv`: all 105 zone pairs, including forbidden pairs.
- `retained_edges.csv`: all retained branches, including boundaries.
- `all_branch_parameters.csv`, `air_capacitances.csv` and
  `simplified_RC_parameters.csv`: physical units and comparison references.
- `figures/`: PNG, PDF and SVG exports of sweep, graph and prediction figures.
- `INTERPRETATION.md`: scope, result summary and limitations.

All graph labels are offset above zone nodes and pink plenum boxes. Graphs
collapse storage branches to single lines and omit outdoor/ground paths for
legibility; those paths remain in the model and tables.

Two sets of four temperature panels compare best-accuracy and sparse models.
The same two zones are used throughout: lowest and highest **validation**
RMSE of the shared 2R1C reference. The same first February and August test
episodes are shown. These are representative seasonal plots, not plots
selected for favourable test performance.

`independent_fitted_parameters` counts active conductances, two estimated
gains, and fifteen air capacitances only when freely estimated. Derived
storage capacitances and imposed air values are not independent parameters.
A validation-selected common tau is recorded separately as a hyperparameter.
Active parameter count is not a proof of statistical identifiability.

## Reproduction

Install `numpy`, `scipy`, `pandas`, `matplotlib`; Jupyter and IPython are needed
only for the notebooks. Tested scientific runtime: Python shipped with
FreeCAD 1.0, numpy 1.26.4 and scipy 1.16.0.

From this directory:

```powershell
python -m unittest test_engine -v
python run_investigations.py
python run_investigations.py --report-only
```

The installed folder discovers `../../rc-modelling/results/prepared_data.npz`
through the implementation root. An explicit alternative is:

```powershell
python run_investigations.py --implementation 'C:/path/to/implementation'
```

Completed cases and variants are reused. Code/data/config contract hashes
prevent accidental mixing of changed settings with existing results. Use a
new copy/output directory for a changed experimental protocol. The inputs
folder freezes the air and wall reference tables; it does not duplicate the
annual prepared dataset. This directory must remain under `rc-modelling`, or
receive an explicit implementation path.

## Interpretation boundaries

Physical priors enforce some agreement by construction. Use the engineering
ratios and adjacency information to interpret remaining discrepancies; do not
call all parameters physically recovered. Exact shared-wall adjacency is
used after fitting for assessment only. Nonadjacent retained branches are
effective links, and missing branches do not establish zero physical exchange.

These experiments do not establish response to deliberately varied HVAC
commands, MPC runtime, or closed-loop superiority of the expanded models.
Future plenum values are supplied, not predicted. State count and RMSE inform
the model choice but do not by themselves validate deployment in the MPC.
