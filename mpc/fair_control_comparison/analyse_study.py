"""Reconcile plant outputs, compare experiments and export publication figures."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1'
from pathlib import Path
import json,hashlib,sqlite3
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from price_mpc import HourlyPrices

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'thesis_figures';OUT.mkdir(exist_ok=True)
FIG=OUT/'figures';FIG.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'serif','font.size':10,'axes.labelsize':10,'axes.titlesize':11,
 'legend.fontsize':8,'pdf.fonttype':42,'ps.fonttype':42,'figure.dpi':130,'savefig.dpi':350,
 'axes.spines.top':False,'axes.spines.right':False})
LABELS={'conventional':'Conventional','hvac_mpc_greedy':'HVAC MPC + greedy BESS',
 'zero_export':'Coord.: ignores export','export_pricing':'Coord.: export pricing',
 'no_hvac_penalty':'Export + no HVAC penalty','soft_comfort':'Soft comfort screening',
 'clock_aligned':'Aligned schedule clock','clock_margin020':'Aligned clock + 0.2°C margin',
 'predictive_scheduling':'Predictive scheduling'}
ORDER=list(LABELS)

def save(fig,name):
    fig.savefig(FIG/(name+'.pdf'),bbox_inches='tight')
    fig.savefig(FIG/(name+'.png'),bbox_inches='tight');plt.close(fig)

def read_case(folder):
    e=pd.read_csv(folder/'energy.csv',parse_dates=['time'])
    z=pd.read_csv(folder/'zones.csv',parse_dates=['time'])
    b=pd.read_csv(folder/'battery.csv',parse_dates=['time'])
    return e,z,b

def main():
    cases={};rows=[];verification={};settings=[]
    for result in sorted((ROOT/'results').iterdir()):
        if not (result/'comparison.csv').exists():continue
        proto=json.loads((result/'protocol.json').read_text());variant=proto['study_variant']
        c=proto['config'];prices=HourlyPrices(c['price_path'])
        settings.append(dict(variant=variant,**proto['notebook_settings']))
        comp=pd.read_csv(result/'comparison.csv')
        for case in comp.scenario.unique():
            key=case if case!='coordinated_mpc' else result.name
            LABELS.setdefault(key,variant.replace('_',' ')+' ('+result.name+')')
            if key in cases:continue
            folder=result/'runs'/case;e,z,b=read_case(folder);cases[key]=(folder,e,z,b)
            p=np.array([prices.average(t,c['dt_hours']) for t in e.time])
            exports=float(np.dot(e.export_kWh,p));imports=float(np.dot(e.import_kWh,p))
            summary=comp[(comp.scenario==case)&(comp.period=='whole_experiment')].iloc[0].to_dict()
            assert abs(exports-summary['export_credit_USD'])<1e-7
            assert abs(imports-summary['import_energy_cost_USD'])<1e-7
            assert abs(imports-exports-summary['net_energy_cost_USD'])<1e-7
            assert len(e)==1296 and len(z)==1296*15
            rec=dict(case=key,label=LABELS[key],**summary);rows.append(rec)
            plant=json.loads((result/'verification.json').read_text())[case]
            decfile=folder/'decisions.csv'
            if case!='conventional':
                d=pd.read_csv(decfile)
                plant.update(control_updates=len(d),policies=d.policy.value_counts().to_dict(),
                  first_sat_counts=d.supply_C.value_counts().to_dict(),
                  median_solve_seconds=float(d.solve_seconds.median()),p95_solve_seconds=float(d.solve_seconds.quantile(.95)))
                horizons=np.load(folder/'selected_horizons.npz')
                first=horizons['setpoint'][:,0]-horizons['upper'][:,0]
                plant['updates_with_applied_precooling_over_0p2C']=int((first.min(axis=1)<-.2).sum())
                plant['updates_with_any_planned_precooling_over_0p2C']=int(((horizons['setpoint']-horizons['upper']).min(axis=(1,2))<-.2).sum())
                actual_power=np.array([e[(e.time>=pd.Timestamp(str(t)))&(e.time<pd.Timestamp(str(t))+pd.Timedelta(minutes=30))].hvac_kWh.sum()*2 for t in horizons['time']])
                power_error=horizons['hvac_kW'][:,0]-actual_power
                plant['predicted_vs_actual_first_interval_HVAC_RMSE_kW']=float(np.sqrt(np.mean(power_error**2)))
                horizons.close()
            plant.update(export_credit_recalculated_USD=exports,net_cost_recalculated_USD=imports-exports,
                         initial_soc=summary['initial_soc'],final_soc=summary['final_soc'])
            verification[key]=plant
    df=pd.DataFrame(rows).set_index('case').reindex([x for x in ORDER if x in cases]+[x for x in cases if x not in ORDER])
    base=df.loc['conventional']
    for metric in ['HVAC_kWh','facility_kWh','import_kWh','net_energy_cost_USD','occupied_comfort_degree_hours']:
        df[metric+'_reduction_percent']=100*(base[metric]-df[metric])/base[metric]
    df.to_csv(OUT/'comparison.csv');pd.DataFrame(settings).to_csv(OUT/'settings.csv',index=False)
    effects=[]
    for before,after in [('zero_export','export_pricing'),('export_pricing','no_hvac_penalty'),
        ('no_hvac_penalty','soft_comfort'),('soft_comfort','clock_aligned'),
        ('clock_aligned','predictive_scheduling'),('clock_aligned','clock_margin020')]:
        if before in df.index and after in df.index:
            effects.append(dict(reference=before,change=after,**{k+'_change':df.loc[after,k]-df.loc[before,k]
              for k in ['HVAC_kWh','import_kWh','net_energy_cost_USD','occupied_comfort_degree_hours']}))
    pd.DataFrame(effects).to_csv(OUT/'incremental_effects.csv',index=False)
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2))
    print(df[['HVAC_kWh','import_kWh','export_credit_USD','net_energy_cost_USD','occupied_comfort_degree_hours']].to_string())
    # Choose the smallest import among cases no worse than conventional occupied
    # comfort. This is explicit same-week exploratory selection, not validation.
    eligible=df[(df.occupied_comfort_degree_hours<=base.occupied_comfort_degree_hours+1e-8)&
                (df.net_energy_cost_USD<=base.net_energy_cost_USD)&(df.index!='conventional')]
    import_minimum=eligible.import_kWh.idxmin() if len(eligible) else 'export_pricing'
    # After reviewing the trade-offs, illustrate the lowest net-cost eligible
    # case as well. Preserve the original import-minimum result explicitly.
    selected=eligible.net_energy_cost_USD.idxmin() if len(eligible) else 'export_pricing'
    (OUT/'selection.json').write_text(json.dumps(dict(case=selected,
       import_minimum_case=import_minimum,
       rule='Post-run illustration: lowest net cost among cases with occupied violations and net cost no greater than conventional. Original lowest-import rule result retained as import_minimum_case. Both are same-week exploratory comparisons, not held-out selection.'),indent=2))
    metrics=[('import_kWh','Grid imports (kWh)'),('net_energy_cost_USD','Net energy cost (USD)'),
             ('HVAC_kWh','HVAC electricity (kWh)'),('occupied_comfort_degree_hours','Occupied violations (zone K h)')]
    fig,axes=plt.subplots(2,2,figsize=(10,7.2),layout='constrained')
    for ax,(metric,title) in zip(axes.flat,metrics):
        ax.bar(np.arange(len(df)),df[metric],color=['#566573' if k in ('conventional','hvac_mpc_greedy') else '#1f8a8a' if k==selected else '#628db3' for k in df.index])
        ax.set_ylabel(title);ax.set_xticks(np.arange(len(df)),[LABELS[k].replace(' + ',' +\n').replace('Coord.: ','Coord.:\n') for k in df.index],rotation=35,ha='right',fontsize=8)
        ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    save(fig,'controller_comparison')
    main_cases=list(dict.fromkeys(['conventional','hvac_mpc_greedy','export_pricing',selected]))
    fig,axes=plt.subplots(2,2,figsize=(7.6,6.1),layout='constrained')
    main_labels=['Conventional','HVAC MPC','Export-aware\nMPC','Improved\nMPC']
    for ax,(metric,title) in zip(axes.flat,metrics):
        vals=df.loc[main_cases,metric]
        ax.bar(np.arange(len(vals)),vals,color=['#566573','#7a91ab','#628db3','#1f8a8a'])
        ax.set_ylabel(title);ax.set_xticks(np.arange(len(vals)),main_labels[:len(vals)],fontsize=9,rotation=25,ha='right')
        ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    save(fig,'main_controller_comparison')
    # Financial accounting applies exactly the same tariff to all cases.
    fig,ax=plt.subplots(figsize=(8,3.8),layout='constrained');x=np.arange(len(df))
    ax.bar(x-.25,df.import_energy_cost_USD,.25,label='Import charge',color='#547aa5')
    ax.bar(x,df.export_credit_USD,.25,label='Export credit',color='#d6a23d')
    ax.bar(x+.25,df.net_energy_cost_USD,.25,label='Net energy cost',color='#1f8a8a')
    ax.set_xticks(x,[LABELS[k] for k in df.index],rotation=30,ha='right',fontsize=8);ax.set_ylabel('USD');ax.legend();save(fig,'import_export_cost')
    folder,e,z,b=cases[selected];conv=cases['conventional'][1]
    # Full applied control week: all 15 temperatures and commands are available.
    zone='CORE_MID' if 'CORE_MID' in set(z.zone) else sorted(z.zone.unique())[0]
    zz=z[(z.zone==zone)&(z.phase=='control')];ee=e[e.phase=='control']
    d=pd.read_csv(folder/'decisions.csv',parse_dates=['time'])
    fig,axs=plt.subplots(4,1,figsize=(10,8),sharex=True,layout='constrained')
    axs[0].step(zz.time,zz.upper_C,where='post',label='Original cooling schedule',color='0.5',ls='--')
    axs[0].step(zz.time,zz.actual_cooling_setpoint_C,where='post',label='Applied cooling setpoint',color='#1f8a8a');axs[0].set_ylabel('Setpoint (°C)');axs[0].legend(ncol=2)
    axs[1].step(d.time,d.supply_C,where='post',color='#a25f2b');axs[1].set_ylabel('Supply air (°C)')
    axs[2].plot(ee.time,ee.hvac_kWh*6,label=LABELS[selected]);cc=conv[conv.phase=='control'];axs[2].plot(cc.time,cc.hvac_kWh*6,alpha=.65,label='Conventional');axs[2].set_ylabel('HVAC (kW)');axs[2].legend()
    axs[3].plot(zz.time+pd.Timedelta(minutes=10),zz.temperature_C,label=zone);axs[3].plot(zz.time,zz.upper_C,'--',color='0.5',label='Original upper bound');axs[3].set_ylabel('Zone air (°C)');axs[3].legend()
    axs[-1].xaxis.set_major_formatter(mdates.DateFormatter('%a\n%d Aug'));[ax.grid(alpha=.2) for ax in axs]
    save(fig,'applied_hvac_schedule')
    # One real saved horizon at 08:00 Monday, selected before seeing its outcome.
    with np.load(folder/'selected_horizons.npz') as h:
        ids=pd.DatetimeIndex(h['time']);idx=int(np.argmin(abs(ids-pd.Timestamp('2017-08-21 08:00'))))
        t=ids[idx];tt=pd.date_range(t,periods=h['sat'].shape[1],freq='30min')
        zone_names=json.loads((folder.parent.parent/'thermal_model/model.json').read_text()).get('zones',[]) if (folder.parent.parent/'thermal_model/model.json').exists() else []
        # Runtime outputs preserve model zone order.
        names=list(z.zone.drop_duplicates());zi=names.index(zone)
        fig,axs=plt.subplots(4,1,figsize=(9,8),sharex=True,layout='constrained')
        axs[0].step(tt,h['setpoint'][idx,:,zi],where='post',label='Planned zone cooling setpoint');axs[0].step(tt,h['upper'][idx,:,zi],where='post',ls='--',label='Original upper bound');axs[0].set_ylabel('Setpoint (°C)');axs[0].legend()
        axs[1].step(tt,h['sat'][idx],where='post',color='#a25f2b');axs[1].set_ylabel('Planned SAT (°C)')
        axs[2].plot(tt+pd.Timedelta(minutes=30),h['temperature'][idx,:,zi],label='Predicted zone temperature')
        real=z[(z.zone==zone)&(z.time>=t)&(z.time<tt[-1])];axs[2].plot(real.time+pd.Timedelta(minutes=10),real.temperature_C,'--',label='Actual under subsequent replanning',alpha=.7);axs[2].set_ylabel('Zone air (°C)');axs[2].legend()
        axs[3].step(tt,h['hvac_kW'][idx],where='post',label='Predicted HVAC');axs[3].plot(tt,h['pv'][idx],label='Forecast PV',color='#c7962d');axs[3].step(tt,h['grid'][idx],where='post',label='Predicted grid import',alpha=.8);axs[3].plot(tt,h['base'][idx]+h['hvac_kW'][idx],color='0.4',ls=':',label='Predicted total building');axs[3].set_ylabel('Power (kW)');axs[3].legend(ncol=2)
        for ax in axs:ax.axvspan(t,t+pd.Timedelta(minutes=30),color='0.7',alpha=.25);ax.grid(alpha=.2)
        axs[-1].xaxis.set_major_formatter(mdates.DateFormatter('%a %H:%M'))
        save(fig,'predictive_hvac_schedule')
    # Measured dispatch Sunday and Monday includes recovery and its energy cost.
    mask=e.time>=pd.Timestamp('2017-08-27');ee=e[mask];bb=b[mask]
    fig,axs=plt.subplots(4,1,figsize=(9,8),sharex=True,layout='constrained')
    axs[0].plot(ee.time,ee.demand_kWh*6,label='Building demand');axs[0].plot(ee.time,bb.pv_DC_kWh*6*.96,label='PV equivalent AC',color='#c7962d');axs[0].set_ylabel('Power (kW)');axs[0].legend()
    axs[1].plot(ee.time,ee.import_kWh*6,label='Import');axs[1].plot(ee.time,-ee.export_kWh*6,label='Export (negative)');axs[1].set_ylabel('Grid (kW)');axs[1].legend()
    axs[2].plot(bb.time,bb.charge_DC_kWh*6,label='Charge');axs[2].plot(bb.time,-bb.discharge_DC_kWh*6,label='Discharge (negative)');axs[2].set_ylabel('Battery DC (kW)');axs[2].legend()
    axs[3].plot(bb.time,bb.end_soc*100,color='#1f8a8a');axs[3].set_ylabel('SOC (%)');ax2=axs[3].twinx();ax2.plot(ee.time,[prices.at(t)*100 for t in ee.time],color='#a25f2b',ls='--');ax2.set_ylabel('BES-H (cents/kWh)')
    axs[-1].xaxis.set_major_formatter(mdates.DateFormatter('%a %H:%M'));[ax.grid(alpha=.2) for ax in axs]
    save(fig,'weekend_battery_dispatch')
    cols=['label','HVAC_kWh','import_kWh','export_kWh','import_energy_cost_USD','export_credit_USD','net_energy_cost_USD','occupied_comfort_degree_hours']
    names={'conventional':'Conventional','hvac_mpc_greedy':'HVAC MPC','zero_export':'No export term',
        'export_pricing':'Export pricing','no_hvac_penalty':'No HVAC penalty','soft_comfort':'Soft comfort',
        'clock_aligned':'Clock aligned','clock_margin020':'Clock + 0.2 C margin','predictive_scheduling':'Predictive scheduling'}
    def table(keys,label):
        lines=[r'\begin{table}[htbp]',r'\centering\small',
          r'\caption{Whole-experiment comparison over 20--28 August, including conditioning and recovery. All exports receive the same hourly BES-H valuation.}',
          r'\label{'+label+'}',r'\begin{tabular}{@{}lrrrrr@{}}',r'\toprule',
          r'Controller & HVAC & Grid import & Export credit & Net cost & Occupied \\',
          r' & (kWh) & (kWh) & (USD) & (USD) & (zone K h) \\',r'\midrule']
        for k in keys:
            r=df.loc[k];name=names.get(k,k.replace('_',' '))
            lines.append(f'{name} & {r.HVAC_kWh:.1f} & {r.import_kWh:.1f} & {r.export_credit_USD:.2f} & {r.net_energy_cost_USD:.2f} & {r.occupied_comfort_degree_hours:.3f} '+r'\\')
        return '\n'.join(lines+[r'\bottomrule',r'\end{tabular}',r'\end{table}'])
    tex=table(list(df.index),'tab:export-price-comparison')
    (OUT/'comparison_table.tex').write_text(tex,encoding='utf-8')
    main_keys=list(dict.fromkeys(['conventional','hvac_mpc_greedy','export_pricing',selected,import_minimum]))
    (OUT/'main_comparison.tex').write_text(table(main_keys,'tab:export-main-comparison'),encoding='utf-8')
    print('Selected exploratory case:',selected)

if __name__=='__main__':main()
