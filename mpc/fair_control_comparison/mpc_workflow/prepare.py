"""Prepare exogenous benchmark forecasts and training-only HVAC surrogate parameters."""
from pathlib import Path
import sys,json,sqlite3
import hashlib
import numpy as np
import pandas as pd
from scipy.optimize import nnls

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verify_cache(config):
    """Fail explicitly on stale input profiles rather than silently mixing plants."""
    audit=json.loads((config.output/'preparation.json').read_text())
    for pattern,key in [('*.idf','source_sha256'),('*.epw','weather_sha256')]:
        if audit.get(key)!=file_hash(next(config.source.glob(pattern))):
            raise ValueError('Forecast cache differs from the source model/weather. Use a fresh --output directory.')

def prepare(config):
    out=config.output;out.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(config.implementation/'rc-modelling'))
    from rc_workflow.config import Config as RCConfig
    from rc_workflow.energyplus import prepare_and_run,metadata,digest
    from rc_workflow.data import load
    # Standalone from installed files: regenerates missing instrumented SQL in MPC workspace.
    rcconf=RCConfig(implementation=config.implementation,output=out/'training_source')
    sql,meta=prepare_and_run(rcconf)
    data=load(sql,meta,rcconf)
    n=len(data.zones);dt=data.dt;train=np.isin(data.time.month,[1,4,7,10])&(data.time.day<=14)&(data.time.day>=2)
    cool=np.maximum(-data.hvac,0);heat=np.maximum(data.hvac,0)
    # Estimate capacity envelopes from training only; these are empirical, not certified equipment capacities.
    capacity=np.maximum(2.,np.quantile(cool[train],.995,axis=0)*1.2)
    groups=np.array([0 if 'BOTTOM' in z or '_BOT_' in z else 1 if '_MID' in z else 2 for z in data.zones])
    group_capacity=np.array([np.quantile(cool[train][:,groups==g].sum(axis=1),.995)*1.2 for g in range(3)])
    db=sqlite3.connect(sql)
    def meter(name):
        rows=db.execute('''SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
            JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
            WHERE e.EnvironmentType=3 AND t.WarmupFlag=0 AND d.Name=? AND d.ReportingFrequency='Zone Timestep'
            ORDER BY t.TimeIndex''',(name,)).fetchall()
        value=np.array(rows).ravel()/3.6e6/dt
        if len(value)!=len(data.T):raise ValueError(name)
        return value
    hvac_power=meter('Cooling:Electricity')+meter('Fans:Electricity')+meter('Heating:Electricity')
    db.close()
    # Floor cooling powers plus positive net zone heat plus an operating intercept.
    qc=np.column_stack([cool[:,groups==g].sum(axis=1) for g in range(3)])
    on=(np.abs(data.hvac).sum(axis=1)>.1).astype(float)
    X=np.column_stack([qc,heat.sum(axis=1),on])
    coefficient,_=nnls(X[train],hvac_power[train])
    # Constant nonnegative floor coefficients are a deliberately modest electrical surrogate.
    prediction=X@coefficient
    power_diagnostics=dict(coefficients=coefficient.tolist(),training_rmse_kW=float(np.sqrt(np.mean((prediction[train]-hvac_power[train])**2))),
        nontraining_rmse_kW=float(np.sqrt(np.mean((prediction[~train]-hvac_power[~train])**2))),
        caveat='Aggregate NNLS electricity surrogate; fan/reheat/latent effects are imperfect. Actual energy comes from EnergyPlus meters.')
    oa_delta=data.boundaries[:,0,None]-data.T
    oa_coefficient=np.maximum(0.,(oa_delta[train]*data.outdoor_air[train]).sum(axis=0)/(oa_delta[train]**2).sum(axis=0))
    # Only exogenous profiles are retained for forecasts. No future zone HVAC or plenums.
    np.savez_compressed(out/'forecast_profiles.npz',time=data.time.astype(str).to_numpy(dtype=str),zones=np.array(data.zones),
        outdoor=data.boundaries[:,0],ground=data.boundaries[:,-1],convective=data.convective,radiant=data.radiant,solar=data.solar,
        setpoints=data.setpoints,occupancy=data.occupancy,pv_kW=data.electric[:,1]/dt,
        non_hvac_kW=np.maximum(0.,data.electric[:,0]/dt-hvac_power),capacity=capacity,group_capacity=group_capacity,
        groups=groups,power_coefficient=coefficient,oa_coefficient=oa_coefficient)
    source_idf=next(config.source.glob('*.idf'))
    audit=dict(source_idf=str(source_idf),source_sha256=digest(source_idf),weather_sha256=digest(next(config.source.glob('*.epw'))),zones=data.zones,plenums=meta['plenums'],
        assumed_calendar_year=2017,forecast_assumption='Perfect weather/PV/fixed gain schedules from an offline deterministic simulation; current measured plenums held constant. No future realised controlled HVAC or zone temperatures.',
        capacity=capacity.tolist(),group_capacity=group_capacity.tolist(),power_surrogate=power_diagnostics,
        price_status='BES-H prices are not used: user requested energy/grid objectives, and supplied time labels require repair before tariff use.')
    (out/'preparation.json').write_text(json.dumps(audit,indent=2))
    return audit
