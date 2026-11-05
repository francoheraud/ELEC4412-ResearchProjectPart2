"""Run isolated PV+BESS comparisons without modifying the existing experiments."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
from pathlib import Path
import argparse,json,shutil,hashlib,sqlite3,re
import numpy as np
import pandas as pd
from bess_mpc import BESSConfig,BESSRun
from price_mpc import HourlyPrices
from experiment_settings import load_settings,validate,resize_nmc,set_common_soc_limits
from battery_inventory import initial_inventory

ROOT=Path(__file__).resolve().parent
DEFAULT=ROOT.parents[1]
CASES=['conventional','hvac_mpc_greedy','coordinated_mpc']

def setup(args):
    implementation=Path(args.implementation);original=implementation/'mpc';source=Path(args.plant_folder) if args.plant_folder else implementation/'ep-data/with-pv-bess'
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',args.label): raise ValueError('Use a simple result label without path separators')
    out=ROOT/'results'/args.label
    if args.case=='report':
        config=json.loads((out/'protocol.json').read_text())['config']
        # Historical protocols predate the chemistry field and used KiBaM.
        if 'battery_type' not in config: config.update(battery_type='KiBaM',battery_name='Thesis KiBaM Battery')
        config.update(implementation=implementation,output=out,source_folder=str(out/'inputs'),electrical_path=str(out/'electrical_model.json'),energyplus_root=Path(config['energyplus_root']))
        return BESSConfig(**config)
    if out.exists(): raise ValueError('Result label already exists. Use a fresh --label, or --case report for analysis only.')
    if args.days<=0 or args.recovery_days<0: raise ValueError('Control days must be positive and recovery days nonnegative')
    if pd.Timestamp(args.start).year!=2017: raise ValueError('This benchmark uses the 2017 weather calendar')
    settings=load_settings(args.settings)
    settings_config=BESSConfig(**settings)
    validate(settings_config)
    inputs=out/'inputs'
    model=source/f'RefBldgMediumOfficeNew2004_Chicago_PV{args.coverage}_{args.battery}.idf'
    # Read identity and nominal energy from the selected plant, avoiding stale
    # feedback keys or SOC-to-energy scaling after hardware changes.
    kind='ElectricLoadCenter:Storage:LiIonNMCBattery' if args.battery=='NMC' else 'ElectricLoadCenter:Storage:Battery'
    objects=[[v.strip() for v in o.split(',')] for o in re.sub(r'!.*','',model.read_text()).split(';') if o.strip()]
    batteries=[o for o in objects if o[0].lower()==kind.lower()]
    if len(batteries)!=1: raise ValueError('Expected exactly one '+kind)
    b=batteries[0]
    if args.battery=='NMC':
        model_text,hardware=resize_nmc(model.read_text(),args.capacity_multiplier)
        capacity=hardware['capacity_kWh'];power=hardware['charge_design_kW']
    else:
        if args.capacity_multiplier!=1: raise ValueError('Capacity scaling is supported for NMC only')
        model_text=model.read_text();capacity=206.64;power=50.
        hardware=dict(battery_type='KiBaM',capacity_kWh=capacity,capacity_multiplier=1)
    model_text=set_common_soc_limits(model_text,settings_config.soc_min,settings_config.soc_max)
    hardware.update(common_soc_min=settings_config.soc_min,common_soc_max=settings_config.soc_max)
    inputs.mkdir(parents=True)
    shutil.copytree(ROOT/'model',out/'thermal_model')
    (inputs/'model.idf').write_text(model_text)
    shutil.copy2(next(source.glob('*.epw')),inputs/next(source.glob('*.epw')).name)
    shutil.copy2(original/'results/preparation.json',out/'preparation.json')
    shutil.copy2(original/'results_v2/electrical_model.json',out/'electrical_model.json')
    with np.load(original/'results/forecast_profiles.npz') as a:data={k:a[k] for k in a.files}
    # Exact annual PV-only output, not net production from a storage run.
    pv=pd.read_csv(source/f'PV{args.coverage}_Only_timeseries.csv')
    times=pd.to_datetime(data['time'])
    ends=pd.to_datetime(dict(year=np.full(len(pv),2017),month=pv.Month,day=pv.Day))+pd.to_timedelta(pv.Hour,unit='h')+pd.to_timedelta(pv.Minute,unit='m')
    starts=ends-pd.Timedelta(minutes=10)
    series=pd.Series(pv.inverter_AC_kWh.to_numpy()*6,index=starts)
    data['pv_kW']=series.reindex(times).to_numpy()
    if not np.isfinite(data['pv_kW']).all():raise ValueError('PV forecast alignment failed')
    np.savez_compressed(out/'forecast_profiles.npz',**data)
    c=BESSConfig(implementation=implementation,output=out,source_folder=str(inputs),coverage=args.coverage,start=args.start,days=args.days,recovery_days=args.recovery_days,
        electrical_path=str(out/'electrical_model.json'),price_path=str(implementation/'ep-data/RealTime_BES-H_Prices_Annual.csv'),
        battery_name=b[1],battery_type=args.battery,capacity_kWh=capacity,power_kW=power,**settings)
    validate(c)
    protocol=dict(config=c.serializable(),comparisons=CASES,scope='Simulation benchmark; fixed RC and electrical models; finite thermostat/SAT policy search coupled to linear battery dispatch. No field validation.',
       battery=f'{args.battery} EnergyPlus plant; first-order predictor with charge efficiency {c.eta_charge:g} and discharge efficiency {c.eta_discharge:g}. Efficiencies are user scenario assumptions. SOC times nominal capacity is an approximate inventory measure.',
       hardware=hardware,notebook_settings=settings,
       initialisation='Battery charge/discharge overrides are zero during weather-run warmup for every controller. A stale first begin-timestep SOC is retained as raw_initial_soc; where the first recorded interval has zero battery flow its end SOC defines settled initial inventory. Conditioning-day charging is included in whole-experiment capacity comparisons.',
       flexibility='Candidate cooling setpoints stay inside original comfort bounds; no new equipment or wider evaluation comfort band. Time-varying SAT policies use only the three calibrated levels. HVAC energy allowance is a prediction guard, not an actual plant guarantee.',
       forecasts='Perfect PV/weather and historical price scenario; gains use existing forecast assumptions.',
       terminal=f'Fixed {c.soc_min:.1%} nominal planning reserve (or starting SOC when below reserve); no ratcheting to the current charge level. Actual final inventory is separately reported, including recovery.',
       price=HourlyPrices(c.price_path).audit,
       hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in list(ROOT.glob('*.py'))+list((ROOT/'mpc_workflow').glob('*.py'))},
       source_idf_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
       simulation_input_sha256=hashlib.sha256((inputs/'model.idf').read_bytes()).hexdigest())
    protocol['price']['tariff_scope']='Energy-only BES-H import/export scenario; excludes other tariff charges. Signed hourly prices are retained. Credits are economic value, not a cash-payment settlement model.'
    protocol['price']['optimisation_export_price_factor']=c.export_price_factor
    protocol['price']['evaluation_export_price_factor']=1.0
    protocol['price']['reference']='https://www.comed.com/cdn/assets/v3/assets/blt3ebb3fed6084be2a/bltceb8d9495434223b/695be67c33699162b6ea350c/20065_Net_Metering_FAQ_2025_1223A.pdf'
    protocol['thermal_model']=json.loads((out/'thermal_model/provenance.json').read_text())
    protocol['battery_control_correction']={
        'native_and_planning_soc_limits':[c.soc_min,c.soc_max],
        'charging':'Reserve the LP planned AC export before charging measured surplus; native power and common SOC limits remain active.',
        'discharging':'Retain the first LP discharge request, clipped to measured deficit, power and SOC limits.',
        'scope':'HVAC policy generation, scoring, model, observer and weights unchanged; corrected battery feedback can change future optimisation through measured SOC.',
        'reference':json.loads((ROOT/'correction_provenance.json').read_text())}
    protocol['thermal_model']['initialisation']='Causal 72-hour past-data endpoint filtering followed by the unchanged one-day live conditioning; storage estimates are propagated between measurements.'
    protocol['thermal_model']['observer']='Original zone heat-bias gain 0.2 and +/-20 kW bounds; full-state predictions projected to measured zones. Storage states updated from measured endpoints.'
    (out/'protocol.json').write_text(json.dumps(protocol,indent=2))
    snapshot=out/'code_snapshot';snapshot.mkdir()
    for p in ROOT.glob('*.py'): shutil.copy2(p,snapshot/p.name)
    shutil.copytree(ROOT/'mpc_workflow',snapshot/'mpc_workflow',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    return c

def report(c):
    prices=HourlyPrices(c.price_path);summary=[];checks={}
    for case in CASES:
        folder=c.output/'runs'/case
        if not (folder/'battery.csv').exists():continue
        e=pd.read_csv(folder/'energy.csv',parse_dates=['time']);b=pd.read_csv(folder/'battery.csv');z=pd.read_csv(folder/'zones.csv')
        steps=pd.read_csv(folder/'battery_system_steps.csv')
        con=sqlite3.connect(folder/'energyplus/eplusout.sql')
        sql=pd.read_sql_query("SELECT d.Name,r.Value FROM ReportData r JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex JOIN Time t ON r.TimeIndex=t.TimeIndex JOIN EnvironmentPeriods e ON t.EnvironmentPeriodIndex=e.EnvironmentPeriodIndex WHERE e.EnvironmentType=3 AND t.WarmupFlag=0 AND d.Name='Electricity:Facility' AND d.ReportingFrequency='Zone Timestep'",con);con.close()
        # Source models use Timestep meters; verify actual SQL frequency if absent.
        err=(folder/'energyplus/eplusout.err').read_text()
        balance=float(np.max(np.abs(b.inverter_AC_kWh-c.inverter_efficiency*(b.pv_DC_kWh+b.discharge_DC_kWh-b.charge_DC_kWh))))
        checks[case]=dict(soc_min=float(steps.soc.min()),soc_max=float(steps.soc.max()),max_charge_kW=float(steps.charge_kW.max()),max_discharge_kW=float(steps.discharge_kW.max()),simultaneous_steps=int(((steps.charge_kW>1e-6)&(steps.discharge_kW>1e-6)).sum()),DC_AC_balance_max_kWh=balance,severe_errors=err.count('** Severe **'),sql_demand_rows=len(sql))
        checks[case]['charge_beyond_surplus_kWh']=float((steps.charge_beyond_surplus_kW*steps.dt_hours).sum())
        checks[case]['common_SOC_limits_passed']=bool(steps.soc.min()>=c.soc_min-1e-5 and steps.soc.max()<=c.soc_max+1e-5)
        if not checks[case]['common_SOC_limits_passed']:
            raise RuntimeError('Configured common SOC limits failed: '+str(checks[case]))
        checks[case]['nominal_power_limit_passed']=bool(max(steps.charge_kW.max(),steps.discharge_kW.max())<=c.power_kW+.001)
        checks[case]['max_nominal_power_exceedance_kW']=float(max(0,max(steps.charge_kW.max(),steps.discharge_kW.max())-c.power_kW))
        if not checks[case]['nominal_power_limit_passed']:
            checks[case]['limitation']='Native NMC achieved power exceeds the nominal load-centre request. Report the measured maximum; this check did not pass.'
        if len(sql)==len(e):checks[case]['facility_meter_max_error_kWh']=float(np.max(np.abs(sql.Value.to_numpy()/3.6e6-e.demand_kWh)))
        if len(sql)!=len(e) or balance>1e-6 or checks[case]['facility_meter_max_error_kWh']>1e-6 or checks[case]['severe_errors'] or checks[case]['simultaneous_steps'] or steps.soc.min()<.199 or steps.soc.max()>.951:
            raise RuntimeError('Plant verification failed: '+str(checks[case]))
        checks[case]['electrical_balance_and_SOC_passed']=True
        for phase in ['control','control_and_recovery','whole_experiment']:
            mask=(e.phase=='control') if phase=='control' else (e.phase!='conditioning') if phase=='control_and_recovery' else np.ones(len(e),dtype=bool)
            zz=z[z.phase=='control'] if phase=='control' else z[z.phase!='conditioning'] if phase=='control_and_recovery' else z
            bb=b.loc[mask]
            violation=np.maximum(zz.temperature_C-zz.upper_C,0)+np.maximum(zz.lower_C-zz.temperature_C,0)
            row=dict(scenario=case,period=phase,capacity_kWh=c.capacity_kWh,policy_family=c.policy_family,price_weight=c.price_weight,HVAC_kWh=float(e.loc[mask,'hvac_kWh'].sum()),facility_kWh=float(e.loc[mask,'demand_kWh'].sum()),import_kWh=float(e.loc[mask,'import_kWh'].sum()),export_kWh=float(e.loc[mask,'export_kWh'].sum()),import_energy_cost_USD=float(sum(r.import_kWh*prices.average(r.time,c.dt_hours) for r in e.loc[mask].itertuples())),comfort_degree_hours=float(violation.sum()*c.dt_hours),occupied_comfort_degree_hours=float(violation[zz.occupied].sum()*c.dt_hours),peak_import_kW=float(e.loc[mask,'import_kWh'].max()/c.dt_hours),initial_soc=float(bb.start_soc.iloc[0]),final_soc=float(bb.end_soc.iloc[-1]),nominal_inventory_change_kWh=float((bb.end_soc.iloc[-1]-bb.start_soc.iloc[0])*c.capacity_kWh),charge_DC_kWh=float(bb.charge_DC_kWh.sum()),discharge_DC_kWh=float(bb.discharge_DC_kWh.sum()))
            row['export_credit_USD']=float(sum(r.export_kWh*prices.average(r.time,c.dt_hours) for r in e.loc[mask].itertuples()))
            row['net_energy_cost_USD']=row['import_energy_cost_USD']-row['export_credit_USD']
            row['optimisation_export_price_factor']=c.export_price_factor
            summary.append(row)
            row.update(initial_inventory(bb,phase=='whole_experiment',c.freeze_battery_during_warmup))
            row['nominal_inventory_change_kWh']=(row['final_soc']-row['initial_soc'])*c.capacity_kWh
    pd.DataFrame(summary).to_csv(c.output/'comparison.csv',index=False)
    (c.output/'verification.json').write_text(json.dumps(checks,indent=2))
    print(pd.DataFrame(summary).to_string(index=False));print(json.dumps(checks,indent=2))

def main():
    p=argparse.ArgumentParser();p.add_argument('--implementation',default=str(DEFAULT));p.add_argument('--coverage',type=int,choices=[60,80],default=80);p.add_argument('--start',default='2017-07-17');p.add_argument('--days',type=int,default=7);p.add_argument('--label',default='development80_nmc');p.add_argument('--case',choices=CASES+['all','report'],default='all')
    p.add_argument('--battery',choices=['NMC','KiBaM'],default='NMC');p.add_argument('--plant-folder',default=None,help='Optional plant/forecast folder; defaults to implementation/ep-data/with-pv-bess')
    p.add_argument('--settings',type=Path,help='JSON objective weights and HVAC policy settings; see notebook')
    p.add_argument('--capacity-multiplier',type=int,default=1,help='NMC parallel count, mass and area multiplier; same plant for every controller')
    p.add_argument('--recovery-days',type=int,default=1)
    a=p.parse_args();c=setup(a)
    if a.case!='report':
        for case in CASES if a.case=='all' else [a.case]:
            print('Running',case,flush=True);BESSRun(c,case).run()
    report(c)
if __name__=='__main__':main()
