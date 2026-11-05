# Thermal RC identification and renewable-integrated supervisory MPC

Research code for **Data-Driven Identification and Reduction of Thermal
Resistor–Capacitor Networks for Renewable Integrated Building Supervisory Model
Predictive Control**, Franco Heraud Noya, University of Western Australia, 2026.

This repository is a curated reproducibility copy of the submitted research,
not the entire development workspace. It contains the reported RC investigations,
the selected 45-state predictor, and the final three-controller EnergyPlus study.
It replaces neither the submitted thesis nor the broader historical `Thesis_v2`
archive. The repository name is retained as supplied; the assessment unit was
GENG4412 Engineering Research Project Part 2.

## Start here

| Purpose | Entry point |
|---|---|
| Review the three offline investigations | [RC Overview notebook](rc-modelling/matched_investigations/Overview.ipynb) |
| Candidate connectivity | [Review](rc-modelling/matched_investigations/01_candidate_connectivity/Review.ipynb) |
| Branch complexity, including 3R2C | [Review](rc-modelling/matched_investigations/3R2C_extension/02_branch_complexity/Review.ipynb) |
| Physical information | [Review](rc-modelling/matched_investigations/03_physical_information/Review.ipynb) |
| Final conventional / HVAC MPC / coordinated MPC results | [MPC notebook](mpc/fair_control_comparison/Fair_Control_Comparison.ipynb) |
| MPC numerical results | [Summary table](mpc/fair_control_comparison/thesis_figures/main_comparison.csv) |
| Objective coefficients actually used | [Weights](mpc/fair_control_comparison/thesis_figures/objective_weights.csv) |
| Assumptions and reproduction | [Reproduction guide](docs/REPRODUCING.md) |

The notebooks display saved results by default. They do **not** launch EnergyPlus
unless their explicit run switch is enabled. Start each notebook from its own
directory or follow its first-cell instructions.

## Setup

Python 3.11 is recommended. Install the Python dependencies in an isolated environment:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
jupyter lab
```

Viewing saved results and fitting RC models does not require EnergyPlus.
Plant reruns require **EnergyPlus 25.2**, installed separately, including its
bundled `pyenergyplus` API. Windows was the original execution platform.
The original thesis plotting scripts require an installed Times New Roman font;
no proprietary fonts or EnergyPlus executable are distributed here.

## Research workflow

1. Prepare the simulated zone temperatures, boundary conditions and heat inputs.
2. Define reciprocal thermal graphs and compare candidate connectivity, branch
   storage and limited physical priors.
3. Fit heat-balance regressions over a regularisation path, refit retained
   supports without the sparsity penalty, and select using validation error.
4. Export the selected RC model and use it in finite-policy supervisory MPC.
5. Compare conventional control, HVAC MPC with greedy storage, and coordinated
   HVAC/battery MPC under common actuator permissions and battery limits.

The final control study uses the DOE Medium Office Chicago prototype, 15
conditioned zones, three air systems, 80% effective PV active-cell coverage and
an approximately 413 kWh NMC battery with nominal 50 kW DC commands. The RC
model has 15 zone-air and 30 storage states. MPC uses a 48-hour horizon and
30-minute decisions, with ten-minute measurement updates.

The reported conventional comparator includes a reactive supply-air reset.
The reporting interval is 20–28 August 2017: one conditioning day, seven control
days and one recovery day. Historical 2025 BES-H prices supply an energy-only
scenario, with equal import/export energy prices. These are not full retail bills.

## What is included and omitted

Included: source modules and tests; review notebooks; model/input provenance;
prepared annual arrays; selected models; summary tables and paper figures;
the three principal control traces; PV/NMC EnergyPlus inputs and weather.
Prepared arrays allow inspection without regenerating large simulator databases.

Omitted: unrelated earlier buildings and SINDy/Brick pilots, exploratory MPC
tuning runs, duplicate code snapshots, Python environments/caches, per-lambda
binary fit checkpoints, and bulky EnergyPlus SQL/ESO/MTR files. The small
ten-case comparison/audit CSVs are retained as context; only the three principal
case traces are distributed. Reruns generate new outputs under fresh labels.

Cached scientific outputs are retained from the original experiments. The
[publication manifest](publication_manifest.json) records file hashes and
distinguishes copied research files from packaging changes. Portability edits
are described in [the reproduction guide](docs/REPRODUCING.md).

## Interpretation limits

This is an exploratory simulation case study, not field validation. Offline
temperature prediction uses supplied heat/boundary inputs; that error is not a
guarantee of counterfactual HVAC-response accuracy. Some evaluation periods were
reused during development. Physical priors do not independently validate material
properties, and the selected graph does not recover every literal physical wall.
Better offline RMSE need not imply lower closed-loop energy consumption.

See [third-party attribution](docs/THIRD_PARTY.md) for the simulation and price
sources. No blanket licence is assigned to third-party data or software.
