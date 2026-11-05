"""Three-controller thesis figures from saved results; no simulation is run."""
from pathlib import Path
import argparse, hashlib, json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager
from presentation import (ROOT, ORDER, LABELS, NAMES, TICKS, COLORS, STYLES,
                          PERIOD, BASELINE, CAPTIONS, main_results)

OUT = ROOT/'thesis_figures'; FIG = OUT/'figures'; FIG.mkdir(parents=True, exist_ok=True)
for name in ['times.ttf', 'timesbd.ttf', 'timesi.ttf', 'timesbi.ttf']:
    p = Path('C:/Windows/Fonts')/name
    if p.exists(): font_manager.fontManager.addfont(str(p))
font = font_manager.findfont('Times New Roman', fallback_to_default=False)
assert 'times' in Path(font).name.lower(), font
plt.rcParams.update({
    'font.family': 'Times New Roman', 'font.size': 11, 'axes.labelsize': 11,
    'axes.titlesize': 12, 'legend.fontsize': 10, 'xtick.labelsize': 10,
    'ytick.labelsize': 10, 'pdf.fonttype': 42, 'ps.fonttype': 42,
    'svg.fonttype': 'none', 'axes.spines.top': False, 'axes.spines.right': False,
    'axes.axisbelow': True, 'grid.alpha': .20, 'lines.linewidth': 1.4})
D = main_results(); built = []; annotations = {}
parser = argparse.ArgumentParser(description=__doc__)
subset = parser.add_mutually_exclusive_group()
subset.add_argument('--summary-only', action='store_true',
                    help='Refresh the three bar-chart summaries; preserve existing time-series exports.')
subset.add_argument('--response-only', action='store_true',
                    help='Refresh the combined control response and separate temperature figure only.')
subset.add_argument('--control-response-only', action='store_true',
                    help='Refresh only the two-panel HVAC control-response figure.')
subset.add_argument('--battery-only', action='store_true',
                    help='Refresh the separate grid-import and battery-coordination figures.')
subset.add_argument('--battery-price-only', action='store_true',
                    help='Create or refresh the optional battery/price figure; preserve all existing figures.')
args = parser.parse_args()
SUMMARY_FIGURES = {'matched_energy_and_cost', 'grid_exchange_and_cost', 'matched_comfort'}
RESPONSE_FIGURES = {'original_bounds_control_response', 'original_bounds_zone_temperature'}
requested = (SUMMARY_FIGURES if args.summary_only else RESPONSE_FIGURES if args.response_only
             else {'original_bounds_control_response'} if args.control_response_only
             else {'grid_import_response', 'battery_coordination'} if args.battery_only
             else {'battery_coordination_with_price'} if args.battery_price_only else set(CAPTIONS))


def save(fig, name):
    if name not in requested:
        for suffix in ['.pdf', '.png']:
            if not (FIG/(name+suffix)).exists():
                raise FileNotFoundError(f'Run without a subset option first: {name+suffix}')
        plt.close(fig); built.append(name+'.pdf'); return
    fig.savefig(FIG/(name+'.pdf'), bbox_inches='tight', metadata={
        'Title': name.replace('_', ' '), 'Author': 'Thesis simulation study',
        'Subject': 'Three controllers, original common temperature bounds; '+PERIOD})
    fig.savefig(FIG/(name+'.png'), dpi=600, bbox_inches='tight')
    plt.close(fig); built.append(name+'.pdf')


def load(label, filename):
    paths = list((ROOT/'results'/label/'runs').glob('*/'+filename))
    if len(paths) != 1: raise ValueError(f'Expected one {filename} for {label}')
    return pd.read_csv(paths[0], parse_dates=['time'])


def bars(ax, key, ylabel, title, digits=1):
    values = D[key].to_numpy(); x = np.arange(3)
    baseline = float(D.loc['original_reactive', key])
    annotations[key] = []
    ax.bar(x, values, color=[COLORS[k] for k in ORDER], width=.60)
    for xx, value, case in zip(x, values, LABELS):
        change = None if baseline == 0 else 100*(float(value)-baseline)/abs(baseline)
        note = 'Baseline' if case == 'original_reactive' else (
            'Change: n/a' if change is None else f'{change:+.2f}%')
        ax.text(xx, value+.025*values.max(), f'{value:,.{digits}f}\n({note})',
                ha='center', va='bottom', fontsize=10, linespacing=1.25)
        annotations[key].append(dict(case=case, value=float(value), baseline=baseline,
                                    percent_change=change, label=note))
    ax.set_xticks(x, [TICKS[k] for k in ORDER])
    ax.set(ylabel=ylabel, title=title, ylim=(0, values.max()*1.36))
    ax.grid(axis='y'); ax.ticklabel_format(axis='y', style='plain', useOffset=False)


def percentage_note(fig):
    fig.supxlabel('Percentages: change relative to conventional control.', fontsize=10)


fig, axes = plt.subplots(1, 2, figsize=(7.1, 3.55), layout='constrained')
bars(axes[0], 'HVAC_kWh', 'HVAC electricity (kWh)', '(a) HVAC electricity')
bars(axes[1], 'net_energy_cost_USD', 'Net electricity cost (USD)', '(b) Net electricity cost', 2)
percentage_note(fig)
save(fig, 'matched_energy_and_cost')

fig, axes = plt.subplots(2, 2, figsize=(7.1, 6.35), layout='constrained')
for ax, key, unit, title, digits in [
    (axes[0,0], 'import_kWh', 'Imported energy (kWh)', '(a) Grid imports', 1),
    (axes[0,1], 'export_kWh', 'Exported energy (kWh)', '(b) Grid exports', 1),
    (axes[1,0], 'import_energy_cost_USD', 'Import cost (USD)', '(c) Import expenditure', 2),
    (axes[1,1], 'export_credit_USD', 'Export credit (USD)', '(d) Export revenue', 2)]:
    bars(ax, key, unit, title, digits)
percentage_note(fig)
save(fig, 'grid_exchange_and_cost')

fig, axes = plt.subplots(1, 2, figsize=(7.1, 3.55), layout='constrained')
bars(axes[0], 'common_occupied_degree_h', 'Occupied violation integral (K·h)', '(a) Accumulated deviation', 3)
bars(axes[1], 'common_occupied_max_K', 'Maximum occupied deviation (K)', '(b) Largest excursion', 3)
percentage_note(fig)
save(fig, 'matched_comfort')

# Fixed selection rule, independent of which case has the greatest energy saving.
scores = []
for lab in LABELS:
    z = load(lab, 'zones.csv'); z = z[z.phase.eq('control') & z.occupied].copy()
    z['violation'] = (z.temperature_C-z.upper_C).clip(lower=0)+(z.lower_C-z.temperature_C).clip(lower=0)
    scores.append(z.groupby('zone').violation.sum())
zone = pd.concat(scores, axis=1).sum(axis=1).idxmax()
start = pd.Timestamp('2017-08-22 06:00'); end = start+pd.Timedelta(hours=48)
selection = {'original': dict(zone=zone, start=str(start), end=str(end),
    rule='Largest pooled occupied violation during control days across the '
         'three plotted original-bound controllers; fixed 48-hour window.')}
response_colors = {'reactive': '#64666B', 'hvac_mpc': '#D55E00', 'coordinated': '#0072B2'}
response_styles = {'reactive': '-', 'hvac_mpc': '-', 'coordinated': (0, (6, 3))}
response_widths = {'reactive': 1.5, 'hvac_mpc': 2.4, 'coordinated': 1.4}
response_markers = {'reactive': None, 'hvac_mpc': 'o', 'coordinated': 's'}


def response_style(key, stride):
    # Offset the marker locations in time, never the underlying data values.
    return dict(color=response_colors[key], ls=response_styles[key],
                lw=response_widths[key], marker=response_markers[key],
                markevery=(0 if key == 'hvac_mpc' else stride//2, stride),
                markersize=4, markerfacecolor='white', markeredgewidth=.9)


fig, axes = plt.subplots(2, 1, figsize=(7.1, 4.8), sharex=True,
                         height_ratios=[1, 1.1], layout='constrained')
zone_traces = {}
for key, lab in zip(ORDER, LABELS):
    z = load(lab, 'zones.csv'); z = z[z.zone.eq(zone) & z.time.between(start, end)]
    zone_traces[key] = z
    e = load(lab, 'energy.csv'); e = e[e.time.between(start, end)]
    dec = load(lab, 'decisions.csv'); dec = dec[dec.time.between(start, end)]
    axes[0].step(dec.time, dec.supply_floor1_C, where='post', label=NAMES[key], **response_style(key, 4))
    axes[1].step(e.time, e.hvac_kWh*6, where='post', **response_style(key, 12))
axes[0].set(ylabel='Supply-air target (°C)', yticks=[12.8,15.5,18.], ylim=(12.3,18.5),
            title='HVAC control response under original temperature bounds')
axes[1].set(ylabel='HVAC electricity (kW)', xlabel='Simulation time (standard time)')
for ax in axes: ax.grid(True); ax.set_xlim(start, end)
axes[-1].xaxis.set_major_locator(mdates.HourLocator(byhour=[6,18]))
axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%d Aug\n%H:%M'))
handles, labels = axes[0].get_legend_handles_labels()
fig.legend(handles, labels, loc='outside lower center', ncol=3, frameon=False, handlelength=3.5)
save(fig, 'original_bounds_control_response')

# A separate temperature figure uses the measured-temperature range, with the
# omitted lower bounds explicitly documented. All controllers share this axis.
fig, ax = plt.subplots(figsize=(7.1, 4.0), layout='constrained')
shown = []
for key in ORDER:
    z = zone_traces[key]
    endpoints = z.time+pd.Timedelta(minutes=10)
    z = z.loc[endpoints.between(start, end)].copy()
    shown.append(z.temperature_C.to_numpy())
    ax.plot(z.time+pd.Timedelta(minutes=10), z.temperature_C,
            label=NAMES[key], **response_style(key, 12))
bounds = zone_traces['coordinated']
ax.step(bounds.time, bounds.upper_C, where='post', color='black',
        ls='--', lw=.9, zorder=1, label='Common upper bound')
ymin = np.floor((min(v.min() for v in shown)-.2)*2)/2
ymax = np.ceil((max(bounds.upper_C.max(), max(v.max() for v in shown))+.2)*2)/2
assert bounds.lower_C.max() < ymin, 'Update lower-bound annotation if the temperature range changes.'
ax.set(ylabel='Zone temperature (°C)', xlabel='Simulation time (standard time)',
       title=f'{zone}: measured zone temperature', xlim=(start, end), ylim=(ymin, ymax))
ax.grid(True)
ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[6,18]))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%d Aug\n%H:%M'))
handles, labels = ax.get_legend_handles_labels()
fig.legend(handles, labels, loc='outside upper center', ncol=2,
           frameon=False, fontsize=10, handlelength=3.5)
lower_values = '/'.join(f'{v:g}' for v in np.unique(np.round(bounds.lower_C.to_numpy(), 6)))
fig.supxlabel(f'Enlarged temperature scale; lower bounds ({lower_values}°C) lie below the plotted range.', fontsize=9)
save(fig, 'original_bounds_zone_temperature')
hvac_trace = zone_traces['hvac_mpc'].set_index('time').temperature_C
coord_trace = zone_traces['coordinated'].set_index('time').temperature_C
selection['original']['max_MPC_temperature_difference_K'] = float((hvac_trace-coord_trace).abs().max())
selection['original']['temperature_only_ylim_C'] = [float(ymin), float(ymax)]
selection['original']['response_colors'] = response_colors
print('Largest HVAC/coordinated MPC temperature difference in displayed window (K):',
      selection['original']['max_MPC_temperature_difference_K'])

grid_fig, grid_ax = plt.subplots(figsize=(7.1, 3.7), layout='constrained')
fig, axes = plt.subplots(2, 1, figsize=(7.1, 5.1), sharex=True,
                         height_ratios=[1.15, 1], layout='constrained')
for index, (key, lab) in enumerate(zip(ORDER, LABELS)):
    e = load(lab, 'energy.csv'); e = e[e.phase.ne('conditioning')]
    b = load(lab, 'battery.csv'); b = b[b.phase.ne('conditioning')]
    # Thin coloured traces over a wider grey trace reveal coincident curves.
    # Markers identify each curve without shifting any timestamps or values.
    style = dict(color=response_colors[key], ls=response_styles[key],
                 lw=[2.6, 1.8, 1.6][index], marker=['^', 'o', 's'][index],
                 markevery=(index*12, 36), markersize=3.8,
                 markerfacecolor='white', markeredgewidth=.8)
    grid_ax.plot(e.time, e.import_kWh*6, label=NAMES[key], **style)
    axes[0].plot(b.time+pd.Timedelta(minutes=10), b.end_soc*100, label=NAMES[key], **style)
    axes[1].plot(b.time, (b.discharge_DC_kWh-b.charge_DC_kWh)*6, **style)
grid_ax.set(ylabel='Grid import (kW)', title='Grid-import power',
            xlabel='Simulation date (standard time)')
axes[0].set(ylabel='Battery SOC (%)', ylim=(20,99), title='Battery state of charge and dispatch')
for limit in [24,92]: axes[0].axhline(limit, color='black', ls=':', lw=.8)
axes[1].set(ylabel='Battery DC power (kW)', xlabel='Simulation date (standard time)')
axes[1].axhline(0, color='black', lw=.6, zorder=1)
axes[1].text(.01,.02,'Positive: discharge; negative: charge', transform=axes[1].transAxes,
    fontsize=9, bbox=dict(facecolor='white', alpha=.85, edgecolor='none', pad=1))
for ax in [grid_ax, *axes]:
    ax.grid(True); ax.axvspan(pd.Timestamp('2017-08-28'),pd.Timestamp('2017-08-29'),color='black',alpha=.07)
    ax.set_xlim(pd.Timestamp('2017-08-21'),pd.Timestamp('2017-08-29'))
for ax in [grid_ax, axes[0]]:
    ax.text(pd.Timestamp('2017-08-28 12:00'),ax.get_ylim()[1]*.99,'Recovery',
        ha='center',va='top',fontsize=9,bbox=dict(facecolor='white',alpha=.85,edgecolor='none',pad=1))
for ax in [grid_ax, axes[-1]]:
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d Aug'))
for target_fig, ax in [(grid_fig, grid_ax), (fig, axes[0])]:
    handles,labels=ax.get_legend_handles_labels()
    target_fig.legend(handles,labels,loc='outside lower center',ncol=3,frameon=False,handlelength=3.5)
save(grid_fig,'grid_import_response')
save(fig,'battery_coordination')

# Optional price-aligned view, keeping the original battery exports untouched.
price_figure = 'battery_coordination_with_price'
if price_figure in requested:
    from price_mpc import HourlyPrices
    protocol = json.loads((ROOT/'results/original_coordinated/protocol.json').read_text())
    price_candidates = [ROOT.parent.parent/'ep-data/RealTime_BES-H_Prices_Annual.csv',
                        Path(protocol['config']['price_path'])]
    price_path = next((p for p in price_candidates if p.exists()), None)
    if price_path is None:
        raise FileNotFoundError('The original BES-H hourly price CSV is required for the price figure.')
    prices = HourlyPrices(price_path)
    assert prices.audit['sha256'] == protocol['price']['sha256'], 'Price source differs from saved run.'
    fig, axes = plt.subplots(3, 1, figsize=(7.1, 7.0), sharex=True,
                             height_ratios=[1.15, 1, .85], layout='constrained')
    price_start, price_end = pd.Timestamp('2017-08-21'), pd.Timestamp('2017-08-29')
    price_times = pd.date_range(price_start, price_end, freq='h', inclusive='left')
    hourly_prices = np.array([prices.at(t) for t in price_times])
    evidence, plotted_rows = [], []
    for index, (key, lab) in enumerate(zip(ORDER, LABELS)):
        e = load(lab, 'energy.csv')
        b = load(lab, 'battery.csv')
        assert e.time.equals(b.time) and e.phase.equals(b.phase), lab
        p = np.array([prices.average(t, 1/6) for t in e.time])
        import_cost, export_credit = float(np.dot(e.import_kWh, p)), float(np.dot(e.export_kWh, p))
        assert np.isclose(import_cost, D.loc[lab, 'import_energy_cost_USD'], rtol=0, atol=1e-8)
        assert np.isclose(export_credit, D.loc[lab, 'export_credit_USD'], rtol=0, atol=1e-8)
        control = e.phase.eq('control').to_numpy()
        discharge = b.loc[control, 'discharge_DC_kWh'].to_numpy()
        evidence.append(dict(case=lab, import_kWh=float(e.import_kWh.sum()),
            import_expenditure_USD=import_cost, export_revenue_USD=export_credit,
            net_cost_USD=import_cost-export_credit,
            import_weighted_price_USD_per_kWh=import_cost/float(e.import_kWh.sum()),
            control_discharge_weighted_price_USD_per_kWh=float(np.dot(discharge,p[control])/discharge.sum())))
        shown = e.phase.ne('conditioning')
        rows = e.loc[shown, ['time', 'phase', 'import_kWh', 'export_kWh']].copy()
        rows['case'] = lab
        rows['price_USD_per_kWh'] = p[shown]
        rows['end_soc_pct'] = b.loc[shown, 'end_soc'].to_numpy()*100
        rows['battery_DC_kW'] = (b.loc[shown, 'discharge_DC_kWh']-b.loc[shown, 'charge_DC_kWh']).to_numpy()*6
        rows['net_cost_USD'] = (rows.import_kWh-rows.export_kWh)*rows.price_USD_per_kWh
        plotted_rows.append(rows)
        style = dict(color=response_colors[key], ls=response_styles[key],
                     lw=[2.6, 1.8, 1.6][index], marker=['^', 'o', 's'][index],
                     markevery=(index*12, 36), markersize=3.8,
                     markerfacecolor='white', markeredgewidth=.8)
        axes[0].plot(rows.time+pd.Timedelta(minutes=10), rows.end_soc_pct, label=NAMES[key], **style)
        axes[1].plot(rows.time, rows.battery_DC_kW, **style)
    axes[0].set(ylabel='Battery SOC (%)', ylim=(20,99), title='Battery dispatch and hourly electricity price')
    for limit in [24,92]: axes[0].axhline(limit, color='black', ls=':', lw=.8)
    axes[1].set(ylabel='Battery DC power (kW)')
    axes[1].axhline(0, color='black', lw=.6, zorder=1)
    axes[1].text(.01,.02,'Positive: discharge; negative: charge', transform=axes[1].transAxes,
        fontsize=9, bbox=dict(facecolor='white', alpha=.85, edgecolor='none', pad=1))
    axes[2].step(price_times.append(pd.DatetimeIndex([price_end])),
                 np.r_[hourly_prices, hourly_prices[-1]], where='post', color='#704580', lw=1.5)
    axes[2].set(ylabel='Electricity price\n(USD/kWh)', xlabel='Simulation date (standard time)')
    axes[2].yaxis.set_major_formatter(plt.FormatStrFormatter('%.2f'))
    for ax in axes:
        ax.grid(True)
        ax.set_xlim(price_start, price_end)
        ax.axvspan(pd.Timestamp('2017-08-28'),price_end,color='black',alpha=.07)
    axes[0].text(pd.Timestamp('2017-08-28 12:00'),98,'Recovery',ha='center',va='top',fontsize=9,
                 bbox=dict(facecolor='white',alpha=.85,edgecolor='none',pad=1))
    axes[2].xaxis.set_major_locator(mdates.DayLocator())
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%d Aug'))
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='outside lower center',ncol=3,frameon=False,handlelength=3.5)
    save(fig, price_figure)
    pd.concat(plotted_rows, ignore_index=True).to_csv(OUT/'battery_price_timeseries.csv',index=False)
    (OUT/'battery_price_evidence.json').write_text(json.dumps(dict(
        source=str(price_path), source_sha256=prices.audit['sha256'],
        mapping=protocol['price']['convention'],
        figure_period='21-28 August 2017: controller evaluation and recovery; conditioning omitted',
        energy_and_cost_period=PERIOD,
        discharge_weighted_price_period='21-27 August 2017: controller evaluation only',
        price_definition='Common hourly BES-H import/export price, not expenditure; energy-only scenario',
        interpretation_limit='Both HVAC objective and battery policy differ; this is not an isolated battery-policy experiment.',
        results=evidence),indent=2),encoding='utf-8')
else:
    save(plt.figure(), price_figure)

archive=next((ROOT/'results/original_coordinated/runs').glob('*/selected_horizons.npz'))
from mpc_workflow.thermal import ThermalModel
model=ThermalModel(ROOT/'model/thermal_model.npz'); zi=model.zones.index(zone)
with np.load(archive) as h:
    times=pd.to_datetime(h['time']);idx=int(np.argmin(abs(times-start)))
    t=times[idx]+pd.to_timedelta(np.arange(h['hvac_kW'].shape[1])*.5,unit='h')
    fig,axes=plt.subplots(3,1,figsize=(7.1,6.0),sharex=True,layout='constrained')
    axes[0].plot(t+pd.Timedelta(minutes=30),h['temperature'][idx,:,zi],color=COLORS['coordinated'],label='RC-predicted temperature')
    axes[0].step(t,h['setpoint'][idx,:,zi],where='post',color='#BE862B',label='Planned cooling target')
    axes[0].step(t,h['upper'][idx,:,zi],where='post',color='black',ls='--',label='Common upper bound')
    axes[0].set(ylabel='Temperature (°C)',title=f'Saved 48-hour plan: {zone}, {times[idx]:%d August %H:%M}')
    axes[0].legend(ncol=1,loc='upper left',fontsize=9)
    lo,hi=axes[0].get_ylim();axes[0].set_ylim(lo,hi+(hi-lo)*.50)
    axes[1].step(t,h['sat'][idx,:,0],where='post',color=COLORS['coordinated'])
    axes[1].set(ylabel='Supply-air target (°C)',ylim=(12.3,18.5))
    axes[2].step(t,h['discharge'][idx]-h['charge'][idx],where='post',color=COLORS['coordinated'],label='Planned battery DC power')
    axes[2].step(t,h['hvac_kW'][idx],where='post',color=COLORS['hvac_mpc'],label='Predicted HVAC power')
    axes[2].legend(ncol=2,loc='upper left',fontsize=9)
    lo,hi=axes[2].get_ylim();axes[2].set_ylim(lo,hi+(hi-lo)*.25)
    axes[2].set(ylabel='Electrical power (kW)',xlabel='Future simulation time (standard time)')
    for ax in axes: ax.grid(True)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%d Aug\n%H:%M'))
    save(fig,'saved_predictive_plan')

assert set(built)=={name+'.pdf' for name in CAPTIONS}
manifest=dict(presentation='Three main controllers, original common temperature bounds',
    font_family='Times New Roman',font_file=font,pdf_fonts='Embedded TrueType (fonttype 42)',
    png_dpi=600,cases=LABELS,baseline_definition=BASELINE,period=PERIOD,selection=selection,
    captions=CAPTIONS,figures=built,
    percentage_change_definition='100 * (controller - conventional) / abs(conventional); undefined for zero baseline',
    bar_annotations=annotations,
    source_comparison_sha256=hashlib.sha256((ROOT/'comparison.csv').read_bytes()).hexdigest(),
    exported_totals=D.reset_index().to_dict(orient='records'))
(OUT/'figure_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
(OUT/'captions.json').write_text(json.dumps(CAPTIONS,indent=2),encoding='utf-8')
print('Built three-controller figures:',', '.join(n for n in built if Path(n).stem in requested))
