MATCHED CONVENTIONAL CONTROL AND MPC

MAIN THESIS PRESENTATION (updated 14 October 2026)
RESULTS.html, Fair_Control_Comparison.ipynb and thesis_figures now show only
original_reactive, original_hvac_mpc and original_coordinated, labelled
Conventional, HVAC MPC and Coordinated MPC. These are the original-bound
cases giving 4.77% lower coordinated HVAC electricity versus reactive control.
No controller settings, simulation outputs or reporting periods were changed.
The extended presentation is preserved in previous_presentation_20261014.
The complete ten-case data and paired diagnostics remain in comparison.csv
and incremental_comparisons.csv. The protocol below describes that full study.

Rebuild only the main presentation, without running EnergyPlus:
  python build_figures.py
  python write_fair_report.py
  python refresh_presentation_manifest.py
  python verify_delivery.py

Main outputs include grid imports/exports, import cost/export credit, net cost,
HVAC electricity and occupied violations, plus actual control/battery traces.
Use thesis_figures/comparison_tables.tex and figure_includes.tex in LaTeX.

Open RESULTS.html or Fair_Control_Comparison.ipynb.
Use thesis_figures/figures/*.pdf for LaTeX (embedded Times New Roman).
PNG previews are 600 dpi. Tables and figure captions are in thesis_figures.
Bar-chart labels retain absolute values and show signed percentage changes
from conventional control, using unrounded totals. Negative means lower and
positive means higher; it does not automatically denote improvement.
To refresh only these summaries, use: python build_figures.py --summary-only
Time-series plots remain in physical units without percentage annotations.
The control-response figure contains supply-air target and HVAC power panels,
using orange/blue MPC traces with different markers. original_bounds_zone_temperature.pdf
provides a separate enlarged temperature view; its caption explains the axis.
Refresh these two figures with: python build_figures.py --response-only
Refresh only the control-response figure with: python build_figures.py --control-response-only
Grid-import power is exported separately as grid_import_response.pdf.
battery_coordination.pdf contains only battery SOC and DC dispatch power.
Both figures use grey triangles, orange circles and blue dashed squares for
conventional, HVAC MPC and coordinated MPC, respectively.
Refresh these two figures with: python build_figures.py --battery-only
An optional battery_coordination_with_price.pdf adds the common hourly BES-H
price beneath SOC and dispatch. The original battery and grid figures remain.
Refresh only this version with: python build_figures.py --battery-price-only
Its plotted data and cost reconciliation are saved in thesis_figures as
battery_price_timeseries.csv and battery_price_evidence.json. Price is USD/kWh,
not expenditure; the evidence distinguishes figure and headline periods.

QUESTION
Does predictive control add value when nonpredictive control has the same
temperature-command limits and the same supply-air-temperature (SAT) options?

DESIGN
Two separate, internally matched temperature-band experiments:
  original: native cooling schedule, normally 24 C and setback 26.7 C;
  relaxed: add 3 C when the recorded occupancy fraction is greater than 0.01,
           during the seven control days. This can give 29.7 C during occupied
           setback periods; it is an experimental bound, not a comfort standard.

The common upper bound is used by BOTH control and primary comfort evaluation.
Original-bound deviations are also saved, so relaxed operation cannot hide its
reduced cooling service. Heating targets remain unchanged: normally 21 C during
scheduled operation and 15.6 C otherwise. Cooling commands have the same lower
guard, the heating target plus 0.5 C. All controllers can use SAT values 12.8,
14, 15.5, 17 and 18 C, shared across the three original air systems.

Each band has five cases:
  reactive: Native thermostat/VAV loops, common upper cooling targets, and a
            nonpredictive trim/respond SAT reset. At each 30-minute update,
            max(measured zone temperature - current cooling target) determines
            a one-level SAT decrease above 0.20 K, increase at or below 0.05 K,
            or hold otherwise. The rule has no weather/PV/price forecast or RC
            prediction input. Its thresholds were fixed before these runs.
  fixed18:  Native thermostat/VAV loops, same cooling targets, SAT fixed to
            18 C while scheduled on. A deliberately simple strong comparator.
  myopic:   Same RC model, observer, electrical predictor and HVAC objective as
            HVAC MPC; one 30-minute prediction interval instead of 48 hours.
            This is a model-based diagnostic, not conventional control.
  hvac_mpc: 48-hour finite-policy HVAC MPC with the same native greedy battery
            rule as reactive, fixed18 and myopic. This isolates HVAC policy.
  coordinated: 48-hour joint HVAC policy selection and battery LP, with the
            corrected export-aware measured-power feedback used previously.

All native thermostat, VAV, heating and fan-availability mechanisms remain.
Fan-off SAT is 12.8 C. A common API guard keeps applied cooling commands inside
the current common bounds even at schedule transitions. Actual temperatures
can still exceed those bounds and are reported without clipping.

FAIRNESS AND INTERPRETATION
Compare hvac_mpc with reactive and fixed18 for model-based HVAC control versus
simple policies, using identical battery rules. Compare hvac_mpc with myopic
for prediction-horizon value with the same model and objective. Compare
coordinated with hvac_mpc for integrated economic scheduling; both the HVAC
objective and battery policy change. Attribute the difference solely to battery
dispatch only when the paired-command audit confirms identical HVAC commands.

This is not a proof against all possible conventional tuning or all MPC
implementations. The original native 12.8 C conventional schedule is not the
matched-savings denominator. Matching permissions does not guarantee identical
achieved thermal comfort, humidity or outdoor-air delivery.

COMMON EXPERIMENT
DOE Medium Office Chicago, EnergyPlus 25.2; 15 zones/three air systems.
The fixed restricted 2R1C model has 45 states, nine interzone edges and 65 fitted
parameters. No RC refitting was performed for this study. Existing disturbance
correction uses measured delivered HVAC heat, gain 0.2 and +/-20 kW per zone.
PV coverage 80%; NMC battery 413.253 kWh; nominal 50 kW; SOC limits 0.24-0.92.
Identical weather, occupancy, non-HVAC loads, ventilation settings and hardware.
Electrical SAT coefficients come from the earlier separate Aug 7-13 calibration
and validation; no coefficients were fitted to this evaluation week.
Original schedule daylight-saving correction remains enabled in all cases.
Independent floor-by-floor SAT control is not introduced.
Simulations ran in separate processes with single-threaded BLAS. Recorded solve
times describe this run and are not a controlled processor-performance benchmark.

TIME AND METRICS
20 August 2017: common conditioning; 21-27 August: controller evaluation;
28 August: original native HVAC control and greedy battery recovery.
Headline totals always use all 216 hours, with initial/final battery SOC shown.
The two temperature bands are compared separately, not pooled into one saving.
HVAC electricity = DX cooling + fans + electric heating, from native meters.
Building electricity is total facility demand before PV/storage offsets.
Net cost = sum(import kWh * hourly price - export kWh * hourly price).
Prices are the existing 2025 BES-H scenario mapped by month/day/hour to the
simulation calendar, not a reconstruction of a complete commercial bill.
Occupied violations = sum(distance outside common scheduled bounds * 1/6 h),
over occupied zone samples. Mean violation divides by occupied zone-hours and
includes samples with zero violation. These are temperature metrics, not PMV.
Savings = 100*(reference - controller)/reference, with references explicitly
named in incremental_comparisons.csv.

OBJECTIVES
HVAC MPC and myopic: HVAC energy weight 10, comfort weight 10, cooling-setpoint
movement 0.05, SAT movement 0.10. Coordinated: import energy 10, net price 1
(reference 0.05 USD/kWh), separate HVAC energy 0, comfort 10, battery throughput
0.01, and the same movement weights. Comfort margin is zero; no extra positive
offset candidates exist above the common band. The allowed predicted HVAC
increase relative to the controller's reference rollout remains 5%.
Conventional policies do not minimise these objective functions.
See thesis_figures/objective_weights.csv for the actually applied terms.

LIMITATIONS
Single exploratory summer week with perfect weather/PV information, not an
annual or independently selected validation of a newly tuned controller.
The HVAC search is a finite set of trajectories plus a sequential RC-based SAT
candidate, without a global optimality guarantee. A longer horizon may not
improve performance if the model, electrical surrogate or policy set is limiting.
One common recovery day and equal final SOC do not establish identical hidden
building thermal energy. Terminal measured temperatures are recorded.
Ventilation is audited against the existing IDF 12.5 L/s/person design quantity
while fans are scheduled on, not against a legal ventilation standard.
The native battery can slightly exceed the nominal 50 kW request. Failed flags
and measured overshoot energy are retained in fairness_audit.csv.
RC identification is demonstrated as an input to control; these cases do not
isolate the effect of the topology-discovery method itself on energy savings.

REPRODUCE
Validated Python: C:/Program Files/FreeCAD 1.0/bin/python.exe
From this directory, use a NEW result label to avoid overwriting evidence:
  python run_fair.py --band original --controller hvac_mpc --label repeat_case
The canonical analysis expects the ten labels <original|relaxed>_<controller>.
  python analyse_fair.py
  python build_figures.py
  python write_fair_report.py
  python -m unittest test_fair test_advanced test_export_pricing
The notebook includes a disabled-by-default rerun cell and preview cells.
Result protocols preserve the original execution paths as provenance. Entry
scripts derive output paths from their own location and work after copying to
the implementation/mpc/fair_control_comparison folder.

FILES
comparison.csv: all metrics for control-only and full 216-hour periods.
incremental_comparisons.csv: paired savings, comfort changes, command matching.
fairness_audit.csv / matching_checks.json: native verification and matching.
per_zone_comfort.csv: every zone, common and original temperature references.
results/<case>/protocol.json: configuration, plant/model hashes and case design.
results/<case>/runs/<scenario>/: API data, EnergyPlus SQL/ERR, commands and plans.
thesis_figures/summary.csv: headline table; comparison_tables.tex: LaTeX tables.
thesis_figures/figure_includes.tex: figure examples with precise captions.
