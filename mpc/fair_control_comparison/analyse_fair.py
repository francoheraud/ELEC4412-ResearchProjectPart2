"""Native-meter outcomes and auditable matching; never infer savings from forecasts."""
from pathlib import Path
import argparse, hashlib, json, sqlite3
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
CONTROLLERS=['reactive','fixed18','myopic','hvac_mpc','coordinated']

def ventilation(folder):
    with sqlite3.connect(folder/'energyplus/eplusout.sql') as db:
        d=pd.read_sql_query('''SELECT t.Month,t.Day,t.Hour,t.Minute,d.Name,d.KeyValue,r.Value
          FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
          JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
          WHERE e.EnvironmentType=3 AND t.WarmupFlag=0 AND d.ReportingFrequency='Zone Timestep'
          AND (d.Name IN ('Zone People Occupant Count','Zone Air Terminal Outdoor Air Volume Flow Rate')
          OR (d.Name='Schedule Value' AND d.KeyValue='HVACOPERATIONSCHD'))''',db)
    d['time']=pd.to_datetime(dict(year=2017,month=d.Month,day=d.Day))+pd.to_timedelta(d.Hour,unit='h')+pd.to_timedelta(d.Minute,unit='m')-pd.Timedelta(minutes=10)
    v=d.pivot(index=['time','KeyValue'],columns='Name',values='Value')
    oa=v['Zone Air Terminal Outdoor Air Volume Flow Rate'].dropna().rename('oa_m3_s').reset_index()
    oa['KeyValue']=oa.KeyValue.str.replace(' VAV BOX COMPONENT','',regex=False)
    z=oa.set_index(['time','KeyValue']).join(v['Zone People Occupant Count'].dropna().rename('people')).reset_index()
    z['required_m3_s']=.0125*z.people
    fan=v['Schedule Value'].dropna().xs('HVACOPERATIONSCHD',level=1)
    z['fan_schedule']=z.time.map(fan)
    z['deficit_m3_s']=(z.required_m3_s-z.oa_m3_s).clip(lower=0)
    z.to_csv(folder/'ventilation_diagnostic.csv',index=False)
    on=z[(z.fan_schedule>0)&(z.people>.01)]
    tol=np.maximum(.0001,.01*on.required_m3_s)
    return dict(ventilation_design_shortfall_zone_h=float((on.deficit_m3_s>tol).sum()/6),
                ventilation_design_shortfall_m3=float(on.deficit_m3_s.sum()*600))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--partial',action='store_true');args=parser.parse_args()
    rows=[];audit=[];zone_rows=[];matching={};series={}
    expected=[b+'_'+k for b in ['original','relaxed'] for k in CONTROLLERS]
    missing=[]
    for label in expected:
        case=ROOT/'results'/label
        if not (case/'comparison.csv').exists():missing.append(label);continue
        proto=json.loads((case/'protocol.json').read_text());meta=proto['fair_comparison'];cfg=proto['config']
        table=pd.read_csv(case/'comparison.csv');scenario=table.scenario.iloc[0];folder=case/'runs'/scenario
        checks=json.loads((case/'verification.json').read_text())[scenario]
        e=pd.read_csv(folder/'energy.csv',parse_dates=['time']);z=pd.read_csv(folder/'zones.csv',parse_dates=['time'])
        b=pd.read_csv(folder/'battery_system_steps.csv');dec=pd.read_csv(folder/'decisions.csv')
        assert len(e)==1296 and len(z)==19440,(label,len(e),len(z))
        assert not (folder/'callback_errors.txt').read_text().strip(),label
        assert 'EnergyPlus Completed Successfully' in (folder/'energyplus/eplusout.err').read_text(),label
        active=z.phase=='control'
        bound_excess=float((z.loc[active,'cooling_command_C']-z.loc[active,'upper_C']).clip(lower=0).max())
        actual_excess=float((z.loc[active,'actual_cooling_setpoint_C']-z.loc[active,'upper_C']).clip(lower=0).max())
        assert bound_excess<1e-7 and actual_excess<1e-7,(label,bound_excess,actual_excess)
        assert np.allclose(z.upper_C,z.common_upper_C),label
        assert np.isin(dec[[f'supply_floor{g+1}_C' for g in range(3)]].to_numpy(),[12.8,14.,15.5,17.,18.]).all(),label
        assert len(dec)==336,label
        assert checks['electrical_balance_and_SOC_passed'] and checks['severe_errors']==0,label
        full=table[table.period=='whole_experiment'].iloc[0]
        assert abs(full.initial_soc-.24)<1e-5 and abs(full.final_soc-.24)<1e-5,(label,full.initial_soc,full.final_soc)
        series[label]=(e,z)
        identity=dict(idf=hashlib.sha256((case/'inputs/model.idf').read_bytes()).hexdigest(),
            weather=hashlib.sha256(next((case/'inputs').glob('*.epw')).read_bytes()).hexdigest(),
            rc=hashlib.sha256((case/'thermal_model/thermal_model.npz').read_bytes()).hexdigest(),
            profiles=hashlib.sha256((case/'forecast_profiles.npz').read_bytes()).hexdigest(),
            electrical=hashlib.sha256((case/'electrical_model.json').read_bytes()).hexdigest())
        matching[label]=identity
        vent=ventilation(folder)
        power_excess=(b[['charge_kW','discharge_kW']].max(axis=1)-cfg['power_kW']).clip(lower=0)
        aud=dict(label=label,band=meta['band'],controller=meta['controller'],
            bound_excess_K=bound_excess,actual_setpoint_excess_K=actual_excess,
            native_meter_error_kWh=checks['facility_meter_max_error_kWh'],
            soc_min=float(b.soc.min()),soc_max=float(b.soc.max()),soc_passed=checks['common_SOC_limits_passed'],
            nominal_power_passed=checks['nominal_power_limit_passed'],
            native_power_excess_kW=float(power_excess.max()),native_power_excess_kWh=float((power_excess*b.dt_hours).sum()),
            solve_median_s=float(dec.solve_seconds.median()),solve_p95_s=float(dec.solve_seconds.quantile(.95)),
            preconditioning_HVAC_kWh=float(e.loc[e.phase=='conditioning','hvac_kWh'].sum()),
            final_zone_mean_C=float(z.loc[z.time==z.time.max(),'temperature_C'].mean()),**vent)
        audit.append(aud)
        for period in ['control','whole_experiment']:
            t=table[table.period==period].iloc[0].to_dict()
            zz=z[z.phase=='control'].copy() if period=='control' else z.copy()
            en=e[e.phase=='control'] if period=='control' else e
            v=(zz.temperature_C-zz.upper_C).clip(lower=0)+(zz.lower_C-zz.temperature_C).clip(lower=0)
            old=(zz.temperature_C-zz.original_upper_C).clip(lower=0)+(zz.lower_C-zz.temperature_C).clip(lower=0)
            occ=zz.occupied
            t.update(label=label,band=meta['band'],controller=meta['controller'],
                occupied_zone_hours=float(occ.sum()/6),common_occupied_degree_h=float(v[occ].sum()/6),
                common_occupied_mean_K=float(v[occ].mean()),common_occupied_p95_K=float(v[occ].quantile(.95)),
                common_occupied_max_K=float(v[occ].max()),original_occupied_degree_h=float(old[occ].sum()/6),
                original_occupied_mean_K=float(old[occ].mean()),peak_occupied_T_C=float(zz.loc[occ,'temperature_C'].max()),
                common_exceedance_zone_h=float((v[occ]>.1).sum()/6),
                solve_median_s=aud['solve_median_s'],soc_passed=aud['soc_passed'],nominal_power_passed=aud['nominal_power_passed'])
            for col in ['cooling_kWh','fan_kWh','heating_electric_kWh','gas_kWh']:t[col]=float(en[col].sum())
            rows.append(t)
            if period=='control':
                zz['common_violation_K']=v;zz['original_violation_K']=old
                for zone,g in zz[zz.occupied].groupby('zone'):
                    zone_rows.append(dict(label=label,band=meta['band'],controller=meta['controller'],zone=zone,
                        common_degree_h=float(g.common_violation_K.sum()/6),original_degree_h=float(g.original_violation_K.sum()/6),
                        common_mean_K=float(g.common_violation_K.mean()),peak_T_C=float(g.temperature_C.max())))
    if missing and not args.partial:raise RuntimeError('Incomplete cases: '+', '.join(missing))
    d=pd.DataFrame(rows)
    incremental=[]
    for (band,period),part in d.groupby(['band','period']):
        base=part[part.controller=='reactive'].iloc[0]
        mask=(d.band==band)&(d.period==period)
        for metric in ['HVAC_kWh','facility_kWh','import_kWh','net_energy_cost_USD']:
            d.loc[mask,metric+'_saving_vs_reactive_pct']=100*(1-d.loc[mask,metric]/base[metric])
        lookup=part.set_index('controller')
        for left,right,purpose in [('reactive','hvac_mpc','Predictive HVAC vs reactive reset, same greedy battery'),
                                  ('fixed18','hvac_mpc','Predictive HVAC vs fixed18, same greedy battery'),
                                  ('myopic','hvac_mpc','48-hour vs one-step RC control, same model and objective'),
                                  ('hvac_mpc','coordinated','Coordinated vs HVAC-only MPC; both HVAC objective and battery dispatch differ')]:
            if left not in lookup.index or right not in lookup.index:continue
            a=lookup.loc[left];b=lookup.loc[right]
            rec=dict(band=band,period=period,reference=left,comparison=right,interpretation=purpose)
            for metric in ['HVAC_kWh','facility_kWh','import_kWh','net_energy_cost_USD']:
                rec[metric+'_difference']=float(b[metric]-a[metric]);rec[metric+'_saving_pct']=float(100*(1-b[metric]/a[metric]))
            rec['common_occupied_degree_h_difference']=float(b.common_occupied_degree_h-a.common_occupied_degree_h)
            left_case=ROOT/'results'/(band+'_'+left);right_case=ROOT/'results'/(band+'_'+right)
            za=series[band+'_'+left][1];zb=series[band+'_'+right][1]
            da=pd.read_csv(next((left_case/'runs').glob('*/decisions.csv')))
            db=pd.read_csv(next((right_case/'runs').glob('*/decisions.csv')))
            rec['max_cooling_command_difference_K']=float((za.cooling_command_C-zb.cooling_command_C).abs().max())
            rec['max_SAT_command_difference_K']=float(np.max(np.abs(da[[f'supply_floor{g+1}_C' for g in range(3)]].to_numpy()-db[[f'supply_floor{g+1}_C' for g in range(3)]].to_numpy())))
            rec['identical_HVAC_commands']=bool(rec['max_cooling_command_difference_K']<1e-7 and rec['max_SAT_command_difference_K']<1e-7)
            incremental.append(rec)
    # Matching uses actual inputs and measured preconditioning, not just names.
    assert all(v==next(iter(matching.values())) for v in matching.values()),matching
    conditioning_ref=next(iter(series.values()))[0].query("phase=='conditioning'")
    conditioning_zone_ref=next(iter(series.values()))[1].query("phase=='conditioning'")
    for label,(en,zz) in series.items():
        assert np.allclose(en.query("phase=='conditioning'")[['hvac_kWh','demand_kWh','import_kWh']],conditioning_ref[['hvac_kWh','demand_kWh','import_kWh']],atol=1e-7,rtol=0),label
        assert np.allclose(zz.query("phase=='conditioning'").temperature_C,conditioning_zone_ref.temperature_C,atol=1e-7,rtol=0),label
    d.to_csv(ROOT/'comparison.csv',index=False)
    pd.DataFrame(incremental).to_csv(ROOT/'incremental_comparisons.csv',index=False)
    pd.DataFrame(audit).to_csv(ROOT/'fairness_audit.csv',index=False)
    pd.DataFrame(zone_rows).to_csv(ROOT/'per_zone_comfort.csv',index=False)
    (ROOT/'matching_checks.json').write_text(json.dumps(dict(completed=len(matching),missing=missing,input_hashes_identical=True,
        conditioning_meters_and_temperatures_match=True,command_bounds_passed=True,identities=matching,
        limitation='Identical permitted bounds do not imply identical achieved comfort. Ventilation diagnostic is against the IDF 12.5 L/s/person design quantity, not a code-compliance test. Native battery power flags are retained.'),indent=2))
    print(d[d.period=='whole_experiment'][['label','HVAC_kWh','HVAC_kWh_saving_vs_reactive_pct','import_kWh','net_energy_cost_USD','common_occupied_degree_h','original_occupied_mean_K']].round(3).to_string(index=False))

if __name__=='__main__':main()
