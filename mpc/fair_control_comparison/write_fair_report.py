"""Keep the report, notebook and LaTeX exports aligned with the main figures."""
import html, json
import pandas as pd
from presentation import (ROOT, ORDER, LABELS, NAMES, METRICS, CAPTIONS, PERIOD,
                          BASELINE, main_results, metric_table)

OUT=ROOT/'thesis_figures'; OUT.mkdir(exist_ok=True)
D=main_results(); TABLE=metric_table(D)
ref=D.loc['original_reactive']
PAIRS=pd.DataFrame([dict(reference='reactive',comparison=key,**{
    metric+'_saving_pct':100*(ref[metric]-D.loc['original_'+key,metric])/ref[metric]
    for metric in ['HVAC_kWh','facility_kWh','import_kWh','net_energy_cost_USD']})
    for key in ORDER[1:]])
AUDIT=pd.read_csv(ROOT/'fairness_audit.csv')
D.reset_index().to_csv(OUT/'summary.csv',index=False)
TABLE.to_csv(OUT/'main_comparison.csv',index=False)
PAIRS.to_csv(OUT/'main_savings.csv',index=False)

settings=[]
for label in LABELS:
    p=json.loads((ROOT/'results'/label/'protocol.json').read_text())
    c=p['config']; key=p['fair_comparison']['controller']; active=key!='reactive'
    settings.append(dict(case=label,controller=NAMES[key],optimises_objective=active,
        horizon_hours=c['horizon_hours'] if active else 0,
        grid_import_weight=c['grid_import_weight'] if key=='coordinated' else 0,
        price_weight=c['price_weight'] if key=='coordinated' else 0,
        HVAC_energy_weight=c['renewable_hvac_weight'] if key=='coordinated' else c['hvac_only_energy_weight'] if active else 0,
        comfort_weight=c['comfort_weight'] if active else 0,
        battery_throughput_weight=c['battery_throughput_weight'] if key=='coordinated' else 0,
        setpoint_movement_weight=c['setpoint_movement_weight'] if active else 0,
        SAT_movement_weight=c['sat_movement_weight'] if active else 0))
weights=pd.DataFrame(settings); weights.to_csv(OUT/'objective_weights.csv',index=False)

body='''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conventional control, HVAC MPC and coordinated MPC</title>
<style>body{font:18px 'Times New Roman',serif;line-height:1.45;color:#17252e;max-width:1000px;margin:30px auto;padding:20px}h1{font-size:32px}h2{font-size:25px}table{border-collapse:collapse;font-size:17px;width:100%}td,th{padding:8px;border-bottom:1px solid #b7c3cb;text-align:right}td:first-child,th:first-child{text-align:left}img{max-width:100%;height:auto}.note{padding:16px;background:#eef4f6;border-left:4px solid #167c80}.scroll{overflow-x:auto}a{color:#175a91}summary{cursor:pointer}figure{margin:24px 0}figcaption{font-size:16px}</style>
<h1>Conventional control, HVAC MPC and coordinated MPC</h1>
<p>Principal comparison using the original common temperature-command bounds.
The DOE Medium Office, 80% roof PV, 413.25 kWh NMC battery, weather, occupancy,
equipment and operating limits are unchanged across these three saved cases.</p>'''
body+=f'<p><b>Reporting period:</b> {html.escape(PERIOD)}.</p>'
body+=f'<p class="note">{html.escape(BASELINE)} All three have the same allowed cooling-command limits and supply-air-temperature options: 12.8, 14, 15.5, 17 and 18°C. Equal command limits do not guarantee identical achieved temperatures.</p>'
body+='''<p><a href="Fair_Control_Comparison.ipynb">Demonstration notebook</a> |
<a href="thesis_figures/comparison_tables.tex">LaTeX table</a> |
<a href="thesis_figures/figure_includes.tex">LaTeX figure snippets</a> |
<a href="README.txt">Protocol</a></p>
<h2>Three configurations</h2><ul>
<li><b>Conventional:</b> native zone thermostat/VAV controls with current-temperature-based supply-air-temperature reset and greedy battery operation. No RC predictions enter its decisions.</li>
<li><b>HVAC MPC:</b> the identified RC model evaluates HVAC policies over 48 hours; the battery uses the same greedy rule as conventional control.</li>
<li><b>Coordinated MPC:</b> 48-hour HVAC policy selection and predictive battery dispatch consider grid-import energy and net import/export cost.</li></ul>
<h2>Main results</h2><div class="scroll">'''
body+=TABLE.to_html(index=False,escape=True)+'</div>'
body+='''<p>Net electricity cost = import cost minus export credit. The same hourly BES-H price is used for import and export; this is an energy-price scenario, not a complete retail bill. Occupied violations sum the distance outside the original scheduled temperature bounds multiplied by interval duration across all occupied zones. They are not simply hours of discomfort.</p>'''
interpret=[]
for row in PAIRS.itertuples():
    r=D.loc['original_'+row.comparison]
    reduction=100*(1-r.common_occupied_degree_h/D.loc['original_reactive','common_occupied_degree_h'])
    sentence=(f'{NAMES[row.comparison]} versus conventional: HVAC electricity '
        f'{row.HVAC_kWh_saving_pct:.2f}% lower, grid imports {row.import_kWh_saving_pct:.2f}% '
        f'lower, net electricity cost {row.net_energy_cost_USD_saving_pct:.2f}% lower '
        f'and occupied violation integral {reduction:.2f}% lower.')
    interpret.append(sentence); body+='<p>'+html.escape(sentence)+'</p>'
body+='''<p>Coordinated MPC has slightly higher imports than HVAC MPC but lower import expenditure. Export credits are similar. Its financial improvement therefore principally reflects the timing of imported electricity. The coordinated comparison changes both HVAC objectives and battery scheduling; it is not a battery-only ablation.</p>
<h2>Figures for the thesis</h2><p>Use the vector PDFs in LaTeX. All PDFs embed Times New Roman; 600 dpi PNG copies are provided. A separate enlarged temperature figure accompanies the combined control-response figure. No simulation was rerun or retuned to produce these figures.</p>'''
for name,caption in CAPTIONS.items():
    assert (OUT/'figures'/f'{name}.pdf').exists()
    body+=f'<figure><a href="thesis_figures/figures/{name}.pdf">Vector PDF</a> | <a href="thesis_figures/figures/{name}.png">600 dpi PNG</a><br><img src="thesis_figures/figures/{name}.png" alt="{html.escape(name.replace("_"," "))}"><figcaption>{html.escape(caption)}</figcaption></figure>'
body+='''<details><summary>Objective coefficients and interpretation limits</summary>
<p>Conventional control does not minimise an objective. Zeros in its coefficient row denote absent terms. Both MPC controllers use comfort weight 10; the coordinated controller uses grid-import weight 10 and net-price weight 1.</p><div class="scroll">'''
body+=weights.to_html(index=False)+'</div>'
body+='''<p>This is an exploratory summer-week simulation. It does not establish annual savings or superiority over all conventional tuning. The original unmodified EnergyPlus control is a different baseline and previously achieved tighter temperature tracking. Supporting fixed-SAT and one-step-RC cases remain in the complete study; the one-step case performed almost identically to the 48-hour HVAC MPC, so the longer horizon did not demonstrate a material additional HVAC-energy benefit. RC modelling is demonstrated as an input to control; this comparison does not isolate the causal benefit of topology discovery.</p>
<p>Cumulative occupied violations fall, but the largest occupied excursion is slightly higher for MPC. These are temperature-tracking metrics, not a full comfort or indoor-air-quality certification. The recovery day and equal final battery SOC reduce endpoint bias without proving equal hidden building thermal energy.</p></details>
<details><summary>Complete study and verification</summary>
<p><a href="comparison.csv">All ten case summaries</a> | <a href="incremental_comparisons.csv">All paired comparisons</a> | <a href="fairness_audit.csv">Native verification audit</a>. This curated copy includes exported traces for the three principal cases.</p>
<p>All ten cases have no severe EnergyPlus errors, matched input hashes and conditioning trajectories, common SOC limits, valid applied cooling commands, and reconciled native electrical meters. Native battery power slightly exceeded the nominal 50 kW request in some cases; original flags remain in the audit. Ventilation is audited against the unchanged IDF design quantity, not a legal compliance standard.</p>
</details></html>'''
(ROOT/'RESULTS.html').write_text(body,encoding='utf-8')
(OUT/'interpretation.txt').write_text('\n\n'.join(interpret)+'\n\n'+BASELINE,encoding='utf-8')

tex=[r'% Requires booktabs. Original-bound three-controller comparison only.',
    r'\begin{table}[htbp]',r'\centering\small',
    r'\caption{Conventional and MPC comparison over 216 hours under the original common temperature-command bounds. Conventional control includes reactive supply-air-temperature reset. Net electricity cost is import cost less export credit.}',
    r'\label{tab:matched-control-original}',r'\begin{tabular}{@{}lrrr@{}}',r'\toprule',
    r'Metric & Conventional & HVAC MPC & Coordinated MPC \\',r'\midrule']
for key,title,unit,digits in METRICS:
    unit=unit.replace('K h',r'K\,h')
    tex.append(title+' ('+unit+') & '+' & '.join(f'{D.loc["original_"+k,key]:,.{digits}f}' for k in ORDER)+r' \\')
tex += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
(OUT/'comparison_tables.tex').write_text('\n'.join(tex)+'\n',encoding='utf-8')
figtex=[r'% Requires graphicx. All captions refer to the original common bounds.']
for name,caption in CAPTIONS.items():
    figtex += [r'\begin{figure}[htbp]',r'\centering',
        r'\includegraphics[width=\linewidth]{figures/'+name+'.pdf}',
        r'\caption{'+caption+'}',r'\label{fig:'+name.replace('_','-')+'}',r'\end{figure}','']
(OUT/'figure_includes.tex').write_text('\n'.join(figtex),encoding='utf-8')

def cell(kind,source):
    return dict(cell_type=kind,metadata={},source=source.splitlines(True),
                **(dict(execution_count=None,outputs=[]) if kind=='code' else {}))
cells=[cell('markdown', '''# Conventional, HVAC MPC and coordinated MPC
Main comparison: original common temperature-command bounds, 216-hour totals.
Conventional means native thermostat/VAV controls with reactive SAT reset.
The three cases, all objective weights and simulation outputs are unchanged.
Read RESULTS.html for captions, interpretation and limitations.
'''),cell('code','''from pathlib import Path
import sys, subprocess, json
import pandas as pd
from IPython.display import display, Image
ROOT = Path.cwd()
if not (ROOT / 'run_fair.py').exists():
    raise RuntimeError('Start this notebook in fair_control_comparison.')
display(pd.read_csv(ROOT/'thesis_figures/main_comparison.csv'))
'''),cell('code','''display(pd.read_csv(ROOT/'thesis_figures/main_savings.csv'))
display(pd.read_csv(ROOT/'thesis_figures/objective_weights.csv'))
'''),cell('code','''manifest = json.loads((ROOT/'thesis_figures/figure_manifest.json').read_text())
for filename in manifest['figures']:
    display(Image(filename=str(ROOT/'thesis_figures/figures'/Path(filename).with_suffix('.png')), width=950))
'''),cell('markdown', '''## Regenerate the thesis presentation (no EnergyPlus rerun)
Set REBUILD_FIGURES to True and run the next cell. It regenerates only the
figures, tables and report from the existing original-bound cases.
'''),cell('code','''REBUILD_FIGURES = False
if REBUILD_FIGURES:
    for script in ['build_figures.py', 'write_fair_report.py']:
        subprocess.run([sys.executable, str(ROOT/script)], cwd=ROOT, check=True)
'''),cell('markdown','''## Optional new simulation
This is unnecessary when changing presentation alone. Use a fresh label to
preserve the original results. New runs do not silently replace thesis cases.
'''),cell('code','''RUN_SIMULATION = False
CONTROLLER = 'hvac_mpc'  # reactive, hvac_mpc or coordinated
NEW_LABEL = 'original_hvac_mpc_repeat'
if RUN_SIMULATION:
    subprocess.run([sys.executable, str(ROOT/'run_fair.py'), '--band', 'original',
                    '--controller', CONTROLLER, '--label', NEW_LABEL], cwd=ROOT, check=True)
'''),cell('markdown','''## Supporting audit (optional)
The original ten-case summary and audit CSVs remain available. Only the three
principal cases have complete exported traces in this curated copy; supporting
scenarios are excluded from the main figures.
'''),cell('code','''SHOW_SUPPORTING_CASES = False
if SHOW_SUPPORTING_CASES:
    display(pd.read_csv(ROOT/'comparison.csv').query("period == 'whole_experiment'"))
    display(pd.read_csv(ROOT/'fairness_audit.csv'))
''')]
nb=dict(cells=cells,metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'}},nbformat=4,nbformat_minor=5)
(ROOT/'Fair_Control_Comparison.ipynb').write_text(json.dumps(nb,indent=1),encoding='utf-8')
print('Updated three-controller report, notebook and LaTeX exports.')
