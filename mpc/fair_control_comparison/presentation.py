"""Select saved original-bound results; no controller or simulation changes."""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
ORDER = ['reactive', 'hvac_mpc', 'coordinated']
LABELS = ['original_' + key for key in ORDER]
NAMES = dict(zip(ORDER, ['Conventional', 'HVAC MPC', 'Coordinated MPC']))
TICKS = dict(zip(ORDER, ['Conventional', 'HVAC\nMPC', 'Coordinated\nMPC']))
COLORS = {'reactive': '#64666B', 'hvac_mpc': '#167C80', 'coordinated': '#365DA3'}
STYLES = {'reactive': '-', 'hvac_mpc': (0, (2, 2)), 'coordinated': (0, (7, 2))}
PERIOD = ('20-28 August 2017, 216 hours: one conditioning day, seven controller '
          'evaluation days and one common recovery day')
BASELINE = ('Conventional denotes native thermostat/VAV control with a reactive '
            'supply-air-temperature reset, not the unmodified EnergyPlus schedule.')
CAPTIONS = {
    'matched_energy_and_cost':
        'HVAC electricity and net electricity cost for the three controllers '
        'under the original common temperature-command bounds. Totals cover '
        '216 hours, including conditioning and recovery. Conventional denotes '
        'native thermostat/VAV control with reactive supply-air-temperature '
        'reset. Net cost is import expenditure less export credit.',
    'grid_exchange_and_cost':
        'Grid imports, grid exports, import expenditure and export credit over '
        'the same 216-hour period with original common temperature-command '
        'bounds. The same hourly BES-H energy price is applied to imports and '
        'exports. The panels show distinct quantities and use separate scales; '
        'export credit is revenue deducted from import cost.',
    'matched_comfort':
        'Occupied temperature deviations from the same original scheduled '
        'bounds, aggregated across all 15 zones over 216 hours. The integral '
        'sums deviation magnitude multiplied by interval duration; the maximum '
        'is the largest individual occupied-zone excursion. Lower cumulative '
        'violations do not necessarily imply a lower maximum excursion.',
    'original_bounds_control_response':
        'Applied supply-air-temperature target and '
        'HVAC electrical power for the three original-bound controllers. The '
        'displayed 48-hour window is fixed from 22 August at 06:00. The '
        'supply-air target is the recorded first-floor command; HVAC power '
        'covers the whole building and uses ten-minute interval averages. HVAC '
        'MPC is orange with circular markers; coordinated MPC is blue dashed '
        'with square markers. Marker positions are staggered to reveal nearly '
        'overlapping traces; the data values are unchanged.',
    'original_bounds_zone_temperature':
        'Enlarged measured zone-temperature comparison for the zone with the '
        'largest pooled occupied violation during the seven control days '
        'across the three controllers. The fixed 48-hour window starts on '
        '22 August at 06:00, matching the control-response figure. Temperatures '
        'refer to interval ends. All '
        'controllers use the same temperature axis. The scheduled lower '
        'bounds (15.6 and 21 degrees Celsius) are below the displayed range. '
        'HVAC MPC is orange '
        'with circular markers; coordinated MPC is blue dashed with square '
        'markers. Near-coincident traces indicate similar measured '
        'temperatures, without any artificial offset.',
    'grid_import_response':
        'Grid-import power during the seven evaluation days and common '
        'recovery day (shaded). Values are ten-minute interval averages. '
        'Conventional control is grey with triangular markers, HVAC MPC is '
        'orange with circular markers, and coordinated MPC is blue dashed '
        'with square markers. The displayed period matches the separate '
        'battery state-of-charge and dispatch figure.',
    'battery_coordination':
        'Battery state of charge and DC battery power during the '
        'seven evaluation days and common recovery day (shaded). Conventional '
        'and HVAC MPC use greedy battery operation; coordinated MPC jointly '
        'schedules HVAC and the battery. Dotted lines denote the common '
        '24 and 92 percent SOC limits. Positive battery power denotes '
        'discharging and negative power denotes charging. This compares complete control strategies, rather than '
        'isolating battery dispatch while holding HVAC commands fixed. '
        'Conventional control is grey with triangular markers, HVAC MPC is '
        'orange with circular markers, and coordinated MPC is blue dashed '
        'with square markers. Markers appear at different sample positions '
        'to distinguish overlapping traces; timestamps and values are unchanged.',
    'battery_coordination_with_price':
        'Optional price-aligned view of battery SOC and DC dispatch. The bottom '
        'panel shows the common hourly BES-H electricity price (USD/kWh), not '
        'accumulated expenditure. The original 2025 price sequence is mapped '
        'to simulation month, day and hour using the saved standard-time '
        'convention. The same energy price values imports and exports. SOC '
        'values refer to interval ends; dispatch values are ten-minute '
        'averages. Positive power denotes discharge and negative power '
        'denotes charge. Dotted lines mark the 24 and 92 percent SOC bounds; '
        'the recovery day is shaded. This illustrates dispatch timing, but '
        'does not isolate battery-policy benefits from changes in HVAC control.',
    'saved_predictive_plan':
        'Saved 48-hour coordinated-MPC plan starting on 22 August at 06:00: '
        'RC-predicted temperature, cooling target, supply-air-temperature '
        'target and electrical powers. These are predictions and planned '
        'inputs, not realised future measurements. Only the first action was '
        'applied before measurements were updated and the controller replanned.',
}
for _name in ['matched_energy_and_cost', 'grid_exchange_and_cost', 'matched_comfort']:
    CAPTIONS[_name] += (
        ' Parenthetical percentages are signed changes relative to conventional '
        'control, calculated from unrounded totals; negative values indicate '
        'reductions and positive values indicate increases.')
METRICS = [
    ('HVAC_kWh', 'HVAC electricity', 'kWh', 2),
    ('facility_kWh', 'Whole-building electricity', 'kWh', 2),
    ('import_kWh', 'Grid imports', 'kWh', 2),
    ('export_kWh', 'Grid exports', 'kWh', 2),
    ('import_energy_cost_USD', 'Import cost', 'USD', 2),
    ('export_credit_USD', 'Export credit', 'USD', 2),
    ('net_energy_cost_USD', 'Net electricity cost', 'USD', 2),
    ('common_occupied_degree_h', 'Occupied violation integral', 'K h', 3),
    ('common_occupied_max_K', 'Maximum occupied deviation', 'K', 3),
]


def main_results():
    data = pd.read_csv(ROOT / 'comparison.csv')
    rows = data[data.period.eq('whole_experiment')].set_index('label')
    if not rows.index.is_unique:
        raise ValueError('Duplicate whole-experiment case labels.')
    selected = rows.loc[LABELS].copy()
    assert selected.band.eq('original').all()
    assert selected.controller.tolist() == ORDER
    return selected


def metric_table(selected):
    return pd.DataFrame([
        {'Metric': f'{title} ({unit})', **{
            NAMES[k]: f'{selected.loc["original_" + k, key]:,.{digits}f}'
            for k in ORDER}}
        for key, title, unit, digits in METRICS])
