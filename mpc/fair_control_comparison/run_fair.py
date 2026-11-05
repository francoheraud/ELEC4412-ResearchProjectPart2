"""Run one predeclared case; refuses to overwrite previous simulations."""
import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
from pathlib import Path
from types import SimpleNamespace
import argparse, hashlib, json, shutil, re
import numpy as np
from run import ROOT, DEFAULT, setup, report
from run_advanced import split_schedule
from fair_control import CommonBoundsForecast, MatchedRun, SAT_CHOICES


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--band', choices=['original','relaxed'], required=True)
    p.add_argument('--controller', choices=['reactive','fixed18','myopic','hvac_mpc','coordinated'], required=True)
    p.add_argument('--label')
    p.add_argument('--implementation', type=Path, default=DEFAULT)
    p.add_argument('--energyplus-root', type=Path,
                   default=Path(os.environ.get('ENERGYPLUS_ROOT','C:/EnergyPlusV25-2-0')))
    a = p.parse_args()
    label = a.label or a.band+'_'+a.controller
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', label):
        p.error('Use a simple result label without path separators.')
    settings = json.loads((ROOT/'settings_soft_comfort.json').read_text())
    settings.update(schedule_clock_correction=True, comfort_margin=0., comfort_weight=10.,
                    horizon_hours=.5 if a.controller=='myopic' else 48.)
    recipe = ROOT/f'recipe_{label}.json'
    if recipe.exists():
        raise ValueError('Recipe already exists; use a new label')
    recipe.write_text(json.dumps(settings, indent=2))
    c = setup(SimpleNamespace(implementation=str(a.implementation.resolve()), plant_folder=None, label=label,
        case='all', days=7, recovery_days=1, start='2017-08-21', settings=recipe,
        coverage=80, battery='NMC', capacity_multiplier=2))
    c.energyplus_root = a.energyplus_root.resolve()
    c.common_upper_offset_C = 3. if a.band=='relaxed' else 0.
    c.occupied_relaxation_C = 0.  # No controller may exceed the common ceiling.
    import advanced_control, hvac_policies, mpc_workflow.revised as revised
    import mpc_workflow.runtime as runtime
    runtime.Forecast = CommonBoundsForecast
    for mod in (advanced_control, hvac_policies, revised):
        mod.SAT_LEVELS = SAT_CHOICES.copy()
    shutil.copy2(ROOT/'extended_electrical_model.json', c.output/'electrical_model.json')
    path = c.output/'inputs/model.idf'
    text = split_schedule(path.read_text())
    # Read-only output requests: allow ventilation/humidity audits without replay.
    for name in ['Zone People Occupant Count','Zone Air Terminal Outdoor Air Volume Flow Rate','Zone Air Relative Humidity','Schedule Value']:
        text += f'\nOutput:Variable,*,{name},Timestep;'
    path.write_text(text)
    proto = json.loads((c.output/'protocol.json').read_text())
    proto['config']['energyplus_root'] = str(c.energyplus_root)
    proto.update(simulation_input_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        flexibility='All cases in each band share the same cooling-command bounds, heating targets, SAT options and update interval. Achieved temperatures remain outputs, not guaranteed hard constraints.',
        fair_comparison=dict(band=a.band, controller=a.controller, common_upper_offset_C=c.common_upper_offset_C,
            sat_choices_C=SAT_CHOICES.tolist(), common_cooling_command_lower='scheduled heating target +0.5 C',
            common_cooling_command_upper='original cooling schedule + band offset * (occupancy >0.01), during seven control days',
            score_reference='Common band for optimisation and primary comfort metrics; original band additionally reported for every case.',
            conventional='Original local thermostat and VAV control; supervisory SAT reset from current maximum zone error. Fixed18 is a second simple nonpredictive comparator.',
            reactive_rule='Every 30 minutes, SAT moves one allowed level colder if max(T-current_target)>0.20 K, warmer if <=0.05 K, else holds. Starts at 12.8 C; fan-off command 12.8 C.',
            myopic='Same RC model, observer, electrical predictor and HVAC objective as HVAC MPC, but one 30-minute prediction step. Diagnostic, not conventional control.',
            battery='Same native greedy rule except coordinated case, which uses the existing 48-hour LP and corrected measured-surplus feedback.',
            selection='All controller rules and weights fixed before reading these evaluation results; all cases retained. No post-hoc best-week selection.',
            limitations='Single exploratory summer week, perfect weather/PV forecasts, no guarantee of global optimum or matched achieved comfort. Relaxed band is a sensitivity scenario, not a comfort-standard recommendation.'))
    (c.output/'protocol.json').write_text(json.dumps(proto, indent=2))
    MatchedRun(c, a.controller).run()
    report(c)
    print('FINISHED', label, flush=True)


if __name__=='__main__':
    main()

