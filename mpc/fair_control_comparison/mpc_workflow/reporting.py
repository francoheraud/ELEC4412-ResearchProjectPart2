import json,sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

def sql_energy(folder):
    db=sqlite3.connect(folder/'energyplus'/'eplusout.sql')
    rows=db.execute('''SELECT t.Month,t.Day,t.Hour,t.Minute,d.Name,r.Value
        FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex)
        JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex) WHERE e.EnvironmentType=3 AND t.WarmupFlag=0
        AND d.ReportingFrequency='Zone Timestep' AND d.IsMeter=1 AND d.Name IN
        ('Electricity:Facility','ElectricityPurchased:Facility','ElectricityProduced:Facility','ElectricitySurplusSold:Facility',
         'Cooling:Electricity','Fans:Electricity','Heating:Electricity','NaturalGas:Facility')''').fetchall()
    db.close();df=pd.DataFrame(rows,columns=['month','day','hour','minute','name','J'])
    times=pd.to_datetime(dict(year=2017,month=df.month,day=df.day))+pd.to_timedelta(df.hour,unit='h')+pd.to_timedelta(df.minute,unit='min')-pd.Timedelta(minutes=10)
    df['time']=times;return df.pivot(index='time',columns='name',values='J')/3.6e6

def summarise(config):
    output=[];checks=[];baseline=None;baseline_zones=None
    for case in config.scenarios:
        folder=config.output/'runs'/case
        if not (folder/'energy.csv').exists():continue
        e=pd.read_csv(folder/'energy.csv',parse_dates=['time']);z=pd.read_csv(folder/'zones.csv',parse_dates=['time'])
        expected=(config.days+config.preconditioning_days+config.recovery_days)*round(24/config.dt_hours)
        if len(e)!=expected:continue
        expected_times=pd.date_range(pd.Timestamp(config.start)-pd.Timedelta(days=config.preconditioning_days),periods=expected,freq=pd.Timedelta(hours=config.dt_hours))
        if not pd.DatetimeIndex(e.time).equals(expected_times):raise RuntimeError(f'Incorrect simulation dates: {case}')
        if len(z)!=expected*15 or z.duplicated(['time','zone']).any():raise RuntimeError(f'Invalid zone telemetry: {case}')
        if not np.isfinite(e.select_dtypes('number').to_numpy()).all() or not np.isfinite(z.select_dtypes('number').to_numpy()).all():raise RuntimeError(f'Nonfinite telemetry: {case}')
        initial_difference=0.
        if case=='conventional':baseline=e;baseline_zones=z
        elif baseline is not None:
            conditioning=z.phase=='conditioning'
            initial_difference=float(np.max(np.abs(z.loc[conditioning,'temperature_C'].to_numpy()-baseline_zones.loc[conditioning,'temperature_C'].to_numpy())))
            if initial_difference>1e-8:raise RuntimeError(f'Initial plant trajectories differ: {case}')
            np.testing.assert_allclose(z[['lower_C','upper_C']],baseline_zones[['lower_C','upper_C']],atol=1e-10)
            np.testing.assert_array_equal(z.occupied,baseline_zones.occupied)
        sql=sql_energy(folder)
        names={'demand_kWh':'Electricity:Facility','pv_kWh':'ElectricityProduced:Facility','import_kWh':'ElectricityPurchased:Facility','export_kWh':'ElectricitySurplusSold:Facility',
               'cooling_kWh':'Cooling:Electricity','fan_kWh':'Fans:Electricity','heating_electric_kWh':'Heating:Electricity','gas_kWh':'NaturalGas:Facility'}
        delta=max(float(np.max(np.abs(e[k].to_numpy()-sql.loc[e.time,v].to_numpy()))) for k,v in names.items())
        balance=float(np.max(np.abs(e.import_kWh+e.pv_kWh-e.demand_kWh-e.export_kWh)))
        err=(folder/'energyplus'/'eplusout.err').read_text()
        if '** Severe **' in err or 'EnergyPlus Completed Successfully' not in err:raise RuntimeError(f'EnergyPlus error in {case}')
        if delta>1e-6 or balance>1e-6:raise RuntimeError(f'API energy reporting mismatch: {case}, SQL delta {delta}, balance {balance}')
        checks.append(dict(scenario=case,records=len(e),api_vs_sql_max_kWh=delta,balance_max_kWh=balance,severe_errors=0,conditioning_temperature_difference_C=initial_difference))
        decisions=pd.read_csv(folder/'decisions.csv') if (folder/'decisions.csv').stat().st_size>3 else pd.DataFrame()
        expected_updates=round(config.days*24/config.control_hours) if case!='conventional' else 0
        if len(decisions)!=expected_updates:raise RuntimeError(f'Incorrect number of control updates: {case}')
        actuator_error=float(np.max(np.abs(z.actual_cooling_setpoint_C-z.cooling_command_C)))
        if actuator_error>1e-6:raise RuntimeError(f'Thermostat commands were not applied at the intended timestep: {case}')
        checks[-1].update(control_updates=len(decisions),actuator_setpoint_max_difference_C=actuator_error)
        for label,phases in [('control',['control']),('control_plus_recovery',['control','recovery'])]:
            energy=e[e.phase.isin(phases)];zones=z[z.phase.isin(phases)].copy()
            low=np.maximum(zones.lower_C-zones.temperature_C,0);high=np.maximum(zones.temperature_C-zones.upper_C,0)
            occupied=zones.occupied.astype(bool).to_numpy();v=low+high
            changes=zones.groupby('zone',sort=False).cooling_command_C.diff().abs().fillna(0)
            mismatch=np.abs(zones.actual_cooling_setpoint_C-zones.cooling_command_C)
            output.append(dict(scenario=case,period=label,**{k:float(energy[k].sum()) for k in ['demand_kWh','pv_kWh','import_kWh','export_kWh','hvac_kWh','cooling_kWh','fan_kWh','heating_electric_kWh','gas_kWh']},
                peak_grid_import_kW=float(energy.import_kWh.max()/config.dt_hours),occupied_violation_zone_degree_hours=float(v[occupied].sum()*config.dt_hours),
                occupied_zone_hours=float(occupied.sum()*config.dt_hours),max_occupied_violation_C=float(v[occupied].max()) if occupied.any() else 0.,
                all_zone_violation_degree_hours=float(v.sum()*config.dt_hours),one_step_temperature_rmse_C=float(np.sqrt(np.mean(zones.innovation_C**2))),
                planned_vs_delivered_cooling_rmse_kW=float(np.sqrt(np.mean((zones.planned_cooling_kW-np.maximum(-zones.delivered_heat_kW,0))**2))) if case!='conventional' else np.nan,
                disturbance_at_limit_fraction=float(np.mean(np.abs(zones.disturbance_kW)>=config.disturbance_limit_kW-1e-6)),
                total_command_variation_C=float(changes.sum()),maximum_command_change_C=float(changes.max()),
                actuator_setpoint_max_difference_C=float(mismatch.max()),
                mean_solve_seconds=float(decisions.solve_seconds.mean()) if len(decisions) else 0.,max_solve_seconds=float(decisions.solve_seconds.max()) if len(decisions) else 0.,
                optimizer_failures=int((~decisions.success).sum()) if len(decisions) else 0))
    frame=pd.DataFrame(output)
    if len(frame):
        for metric in ['import_kWh','hvac_kWh','occupied_violation_zone_degree_hours']:
            base=frame[frame.scenario=='conventional'].set_index('period')[metric].to_dict()
            frame[metric+'_change_vs_baseline']=frame.apply(lambda r:r[metric]-base.get(r.period,np.nan),axis=1)
        frame.to_csv(config.output/'comparison.csv',index=False)
    (config.output/'verification.json').write_text(json.dumps(checks,indent=2))
    if len(frame):make_plot(config.output,frame);make_trajectory_plot(config.output,frame);write_summary(config.output,frame)
    return frame

def make_plot(out,frame):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    x=frame[frame.period=='control'].copy();fig,axs=plt.subplots(1,3,figsize=(14,5),layout='constrained')
    for ax,key,label in zip(axs,['import_kWh','hvac_kWh','occupied_violation_zone_degree_hours'],['Grid import (kWh)','HVAC electricity (kWh)','Occupied comfort violation (zone C h)']):
        labels={'conventional':'Conventional','reduced_energy':'Reduced\nenergy','reduced_renewable':'Reduced\nPV-aware','dense_renewable':'Dense-candidate\nPV-aware','reduced_renewable_no_correction':'Reduced PV\nno correction','scheduled_supply_reset':'Fixed supply\nreset'}
        ax.bar([labels[s] for s in x.scenario],x[key]);ax.set_ylabel(label);ax.tick_params(axis='x',rotation=35,labelsize=8);ax.grid(axis='y',alpha=.2)
    fig.savefig(out/'comparison.png',dpi=150);plt.close(fig)

def make_trajectory_plot(out,frame):
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(3,1,figsize=(12,8),sharex=True,layout='constrained')
    for case in frame.scenario.unique():
        folder=out/'runs'/case
        e=pd.read_csv(folder/'energy.csv',parse_dates=['time']);e=e[e.phase=='control']
        z=pd.read_csv(folder/'zones.csv',parse_dates=['time']);z=z[z.phase=='control'].copy()
        z['violation']=np.maximum(z.temperature_C-z.upper_C,0)+np.maximum(z.lower_C-z.temperature_C,0)
        z['violation']*=z.occupied.astype(bool)
        axs[0].plot(e.time,e.import_kWh*6,label=case,linewidth=.8,alpha=.8)
        v=z.groupby('time').violation.max();axs[1].plot(v.index,v,label=case,linewidth=.8)
        d=z.groupby('time').disturbance_kW.mean();axs[2].plot(d.index,d,label=case,linewidth=.8)
    axs[0].set_ylabel('Grid import (kW)');axs[1].set_ylabel('Worst occupied\nviolation (C)');axs[2].set_ylabel('Mean estimated\nheat bias (kW/zone)')
    axs[0].legend(fontsize=7,ncol=2)
    for ax in axs:ax.grid(alpha=.2)
    fig.savefig(out/'trajectories.png',dpi=150);plt.close(fig)

def write_summary(out,frame):
    lines=['# Closed-loop benchmark results','',
        'The files report actual EnergyPlus plant outcomes, not the optimiser\'s predicted objective. Positive energy changes indicate increased consumption.','']
    for period in ['control','control_plus_recovery']:
        part=frame[frame.period==period].set_index('scenario')
        if 'conventional' not in part.index:continue
        base=part.loc['conventional'];lines+=['## '+period.replace('_',' '),'',
            '| Scenario | HVAC kWh | HVAC change | Grid import kWh | Grid change | Occupied violation (zone C h) |',
            '|---|---:|---:|---:|---:|---:|']
        for case,r in part.iterrows():
            lines.append(f"| {case} | {r.hvac_kWh:.2f} | {(r.hvac_kWh/base.hvac_kWh-1)*100:+.2f}% | {r.import_kWh:.2f} | {(r.import_kWh/base.import_kWh-1)*100:+.2f}% | {r.occupied_violation_zone_degree_hours:.5f} |")
        lines+=['']
    lines+=['## Interpretation','',
        'Energy benefits must be established against conventional control, not merely against another MPC variant. Tiny comfort violations should not be presented as substantial practical improvements. A seven-day summer test cannot establish annual benefits.','',
        'The corrected and uncorrected renewable-aware cases isolate the implemented bias correction, but their trajectories differ under feedback. The prediction metric is a ten-minute, achieved-HVAC-input prediction error, not a long-horizon forecast error.','',
        'Both RC models have 15 states. The selected model retains zero interzone edges; the dense-candidate fit retains only one. These already similar fitted models do not provide a strong test of reduction versus a richly connected model.','',
        'Remaining development priorities are validation of the planned-heat to thermostat interface, electrical power prediction including fan/reheat effects, and longer-horizon boundary forecasts. Tune any subsequent controller changes on separate development periods before evaluating new held-out control periods.','',
        'Comfort bands, occupancy, weather, PV system and conditioning are common to all cases. See verification.json for independent SQL/API energy checks and zero severe-error checks. See comparison.csv for prediction error, solver timings, planned/achieved cooling mismatch and actuator tracking.']
    (out/'SUMMARY.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
