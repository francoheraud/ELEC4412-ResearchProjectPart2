> **Curated repository note:** This folder retains the preparation and estimation
> modules, prepared arrays, and matched investigations. Some older notebooks and
> raw simulator outputs mentioned in this historical README are omitted. Use
> the [repository guide](../README.md) for the supported review and rerun paths.

# Medium Office RC modelling workflow

This package turns the supplied PV-enabled EnergyPlus model into an offline reciprocal RC identification study. It provides reusable modules, an executed demonstration notebook, numerical checks and exported state-space models for a later MPC implementation. It does not implement MPC or assume that thermostat setpoints equal thermal power commands.

## Run and demonstrate

Place this directory at `implementation/rc-modelling`, beside `ep-data` and `mpc`. Open `RC_Modelling_Demonstration.ipynb` in a Jupyter environment with the packages in `requirements.txt`. The notebook reads the saved results by default and is fast to demonstrate. To repeat the complete experiment:

```powershell
python run_workflow.py
python -m unittest discover -s tests -v
```

The default EnergyPlus executable is `C:/EnergyPlusV25-2-0/energyplus.exe`. The input IDF and EPW are discovered in `../ep-data/with-pv`. An alternative parent directory can be supplied with `--implementation`. The earlier tested Python runtime `C:/Program Files/FreeCAD 1.0/bin/python.exe` can run the modelling scripts; it does not include Jupyter. Use a Jupyter kernel with the listed dependencies to interactively rerun notebook cells. No system Python environment has been modified.

`run_workflow.py` creates a reporting-only instrumented IDF under `results/instrumented_energyplus` and runs it there. Original `ep-data` files are never rewritten. A hash-based cache avoids rerunning the instrumented simulation unless the source, weather or requests change; `--force-energyplus` overrides that cache. Missing input signals are fatal rather than replaced by assumed zeros. Zero window gain is used only where IDF geometry contains no windows for the zone.

The installed demonstration includes prepared data, fitted models, tables, figures, the instrumented IDF and run diagnostics. Bulky `.sql`, `.eso` and `.mtr` simulator intermediates are retained in the Codex staging directory rather than copied into OneDrive. Consequently, the first full recomputation in this installed directory will regenerate its local EnergyPlus database; subsequent runs can reuse it. The notebook itself does not need those bulky intermediates. Recorded provenance paths describe the original execution location.

## Formulation and scope

There are 15 dynamic office nodes, with positive effective capacitances. Three distinct measured plenum temperatures, outdoor temperature and the IDF monthly ground temperature form five boundary inputs. Each office is a candidate for connection to every boundary. The discovery graph starts with all 105 undirected office-to-office edges, each with a single reciprocal nonnegative conductance. No adjacency mask is used in discovery.

In kW and hours, the balance is:

`C_i dT_i/dt + sum_j G_ij (T_i-T_j) + sum_b Gb_ib (T_i-Tb_b) = Q_HVAC_i + Q_conv_i + Q_outdoor_air_i + beta_r Q_radiant_filtered_i + beta_s Q_solar_filtered_i`.

Capacitances have units kWh/K and conductances kW/K. The two shared gain factors are dimensionless. HVAC input is delivered sensible heating minus cooling for each office, not shared air-system electricity. Outdoor-air heat transfer is a signed EnergyPlus balance input; it is not also added as a separate infiltration term. Surface convection is deliberately not used as a forcing shortcut that would bypass identifying the thermal network. Radiant plus visible internal gains and transmitted window solar are causal first-order filtered with fixed 2h and 3h time constants, as modelling assumptions inherited from the earlier workflow. The first training day is excluded for initialisation burn-in.

The monthly ground boundary is available from the model, not measured by a BAS. Conductance/capacitance bounds are broad feasibility limits, not estimates from material properties. Values hitting bounds are reported. Parameters and edges are effective, not automatically physically identifiable.

### Differentiation sensitivity

Both methods use identical continuous training blocks and the same valid centre indices, trimmed by half the seven-sample window. No differentiation window crosses a split boundary or a gap.

- `trapezoidal`: secant temperature rate and averages of both endpoint temperatures, boundaries and heat inputs; an interval heat-balance equation, not a Savitzky-Golay smoother or a pure forward-Euler point equation.
- `savgol`: seven-point quadratic local differentiation, spanning 60 minutes from first to last sample; all other regressors are evaluated at that centre.

The exported zone temperatures and rates are timestep averages, treated as collocated at interval centres. Validation therefore uses the average of adjacent known inputs over each centre-to-centre transition. This finite-reporting approximation is explicit; the original samples are not instantaneous ground truth.

### Discovery, estimation and selection

For each method, bounded convex least squares solves:

`min_theta mean(r_kW**2) + lambda * sum(G_interzone_kW_per_K)`.

Lambda has units kW K in this unnormalised-conductance penalty. It is not directly comparable across differently scaled objectives or datasets. Column scaling improves the solve without changing that physical objective. QR compression follows the earlier E.3 method; full rank is checked and no hidden ridge penalty is introduced. The solver reports convergence, projected-gradient residual, rank and conditioning. Bounds are C in [0.01, 1000] kWh/K, G in [0, 100] kW/K, beta in [0, 2].

The path is zero plus 17 logarithmically spaced lambdas from 1e-6 through 100. Conductances above 1e-6 kW/K define retained support. Each support is refitted without the sparsity penalty, fixing removed interzone conductances to zero. `edge_path.csv` distinguishes discovery support and nonzero refitted conductances. The method does not enforce nested supports: edges may re-enter along an L1 path.

Training: days 1–14 of January, April, July and October (except the first annual day). Validation: days 15–21 of those months. Test: days 15–21 of February, May, August and November. These are predeclared seasonal held-out blocks, not a chronological deployment forecast or cross-validation. No test RMSE enters selection. Within each differentiation method, select the fewest retained edges within 0.02 C of the best validation 24h RMSE. This is an engineering margin, not a one-standard-error statistical claim. Choose the differentiation method by its selected model's validation RMSE.

The primary outputs are the full lambda/support/error paths. Test comparisons include selected Laplacian, dense, no-interzone and manual direct-surface-adjacency models. All use the same boundaries and heat inputs. Manual edges are parsed from actual shared office surfaces; plenum-mediated floor paths are not invented as direct office-to-office edges. The manual construction is an automated geometry-informed comparator, not a measurement of human engineering effort.

The implemented estimator is constrained QP (bounded linear least squares), for both discovery and support refitting. Previous UKF/GA/ANN/PEM experiments are not silently relabelled as runs on this dataset; they are possible extensions behind the same model interface. Higher-order branch storage is also outside this initial implementation.

## State-space interface for MPC

Each model NPZ exports `A`, `B`, `Ad`, `Bd`, `L`, `theta`, `zones`, `input_names` and `dt_hours`. Continuous matrices use hours; discrete matrices use the 10-minute interval. Exact matrix-exponential discretisation avoids forward-Euler integration instability. Input columns are ordered and named: HVAC heat per zone (kW), known convective/outdoor-air gains per zone (kW), filtered radiant per zone (kW), filtered solar per zone (kW), then boundary temperatures (C).

Prediction is `x_next = Ad @ x + Bd @ u`. The HVAC block maps **delivered heat**, not setpoint temperatures, damper commands or electrical power. A future MPC layer must supply feasible heat delivery via an HVAC/actuator response model, model shared-system power, and forecast boundaries/disturbances. In particular, plenum temperatures and outdoor-air heat transfer respond to HVAC operation and are not exogenous known forecasts in deployment. Their measured use here is explicitly offline validation. The MPC folder remains untouched.

Rollouts initialise once from measured temperatures and run open-loop for 1, 6, 24 or 72h, with start points 24h apart and no resets within an episode. Overlapping 72h episodes are not independent uncertainty samples. Metrics exclude the initial state and include per-zone RMSE/MAE/bias and a persistence baseline. Known future measured thermal inputs are used, so these are not operational forecast errors or closed-loop performance claims.

## BES-H prices

`prices.py` audits all 8,760 supplied prices with mixed timestamp formats and preserves the stated USD/kWh units and negative values. Prices are not used in RC estimation. The supplied series actually has duplicate labels and missing clock hours around daylight-saving dates; all are retained and enumerated in `price_audit.json`. It is NOT currently ready for direct MPC use. The supplied header also says hour ending while labels run 00:00 through 23:00. No price alignment is silently adopted. `align_scenario` rejects duplicate/gapped series and requires the caller to choose `label_is_start` or `label_is_end`; missing year-boundary prices raise an error instead of wrapping or inventing values. The notebook displays the audit and identifies this as a remaining MPC decision.

The 2025 price year and EnergyPlus typical-year calendar differ. Month/day/clock matching is a hypothetical scenario and does not preserve a matched historical weather-price process or necessarily the same weekdays. Historical realised future prices would constitute perfect foresight. Export compensation, retail demand charges and forecast assumptions must be supplied before a bill or savings claim.

## Provenance and interpretation

This implementation adapts concepts from the previous E.3/E.4 modules (`e3_laplacian.py`, `e3_validation.py` and `e2_data.py`): reciprocal graph parameterisation, column scaling, QR-reduced QP, local differentiation, support refit and exact discretisation. It generalises zone/boundary mappings and deliberately does not reuse five-zone hard-coded geometry.

Inspect `results/SUMMARY.md`, `lambda_path.csv`, `edge_path.csv`, `parameters.csv`, `solver_diagnostics.csv`, `test_metrics.csv`, `selection.json`, `splits.csv` and `provenance.json`. Training fit, solver success, numerical stability, predictive accuracy and physical plausibility are separate checks. The EnergyPlus error log is retained; successful completion does not mean the source model has no warnings.
