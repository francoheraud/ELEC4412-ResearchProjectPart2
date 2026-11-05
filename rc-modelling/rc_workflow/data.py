"""Strict EnergyPlus extraction; separate measured inputs from identification targets."""
from dataclasses import dataclass
import sqlite3, json
import numpy as np
import pandas as pd
from scipy.signal import lfilter

@dataclass
class Dataset:
    time: pd.DatetimeIndex
    T: np.ndarray
    boundaries: np.ndarray
    hvac: np.ndarray
    convective: np.ndarray
    outdoor_air: np.ndarray
    radiant: np.ndarray
    solar: np.ndarray
    setpoints: np.ndarray
    occupancy: np.ndarray
    electric: np.ndarray
    zones: list
    boundary_names: list
    meta: dict
    dt: float

    @property
    def base_heat(self): return self.hvac+self.convective+self.outdoor_air

def causal_filter(values,tau,dt):
    alpha=1-np.exp(-dt/tau) if tau>0 else 1.
    # Fixed zero initial state, burn-in is documented. No future data are used.
    return lfilter([alpha],[1.,-(1-alpha)],values,axis=0)

def load(sql,meta,config):
    db=sqlite3.connect(sql)
    # The generated EnergyPlus database has no index for repeated per-signal reads.
    # Add an index only to our isolated instrumented output, never the user's SQL.
    db.execute('CREATE INDEX IF NOT EXISTS rc_signal_time ON ReportData(ReportDataDictionaryIndex,TimeIndex)')
    db.commit()
    dictionary=pd.read_sql_query("SELECT * FROM ReportDataDictionary WHERE ReportingFrequency='Zone Timestep'",db)
    dictionary['KeyValue']=dictionary['KeyValue'].fillna('')
    times=pd.read_sql_query('''SELECT DISTINCT t.TimeIndex,t.Year,t.Month,t.Day,t.Hour,t.Minute
        FROM Time t JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
        WHERE e.EnvironmentType=3 AND t.WarmupFlag=0 AND t.IntervalType=-1 ORDER BY t.TimeIndex''',db)
    dates=pd.to_datetime(dict(year=times.Year,month=times.Month,day=times.Day))+pd.to_timedelta(times.Hour,unit='h')+pd.to_timedelta(times.Minute,unit='min')
    time=pd.DatetimeIndex(dates)-pd.Timedelta(hours=config.dt_hours)
    if len(time)!=52560 or not np.all(np.diff(time.asi8)==round(config.dt_hours*3600e9)):
        raise ValueError('Expected one contiguous annual 10-minute series; sizing rows must not enter fitting.')
    ix=times.TimeIndex.to_numpy(); n=len(ix)
    cache={}
    def get(name,key):
        k=(name.upper(),key.upper())
        if k in cache:return cache[k]
        matches=dictionary[(dictionary.Name.str.upper()==k[0])&(dictionary.KeyValue.str.upper()==k[1])]
        if len(matches)!=1: raise ValueError(f'Required signal unavailable or duplicated: {name}, {key}. Run instrumentation first.')
        rows=db.execute('SELECT TimeIndex,Value FROM ReportData WHERE ReportDataDictionaryIndex=? AND TimeIndex>=? AND TimeIndex<=? ORDER BY TimeIndex',
                        (int(matches.iloc[0].ReportDataDictionaryIndex),int(ix[0]),int(ix[-1]))).fetchall()
        v=np.asarray(rows,dtype=float)
        if v.shape!=(n,2) or not np.array_equal(v[:,0],ix) or not np.isfinite(v[:,1]).all():
            raise ValueError(f'Missing/nonfinite/misaligned records: {name}, {key}')
        cache[k]=v[:,1]; return cache[k]
    zones=meta['zones']; plenums=meta['plenums']
    def matrix(name):return np.column_stack([get(name,z) for z in zones])
    T=matrix('Zone Mean Air Temperature')
    boundaries=np.column_stack([get('Site Outdoor Air Drybulb Temperature','Environment')]+[get('Zone Mean Air Temperature',p) for p in plenums]+[np.asarray(meta['ground_monthly_C'])[time.month-1]])
    hvac=(matrix('Zone Air System Sensible Heating Rate')-matrix('Zone Air System Sensible Cooling Rate'))/1000
    conv=matrix('Zone Total Internal Convective Heating Rate')/1000
    outdoor=matrix('Zone Air Heat Balance Outdoor Air Transfer Rate')/1000
    rad=(matrix('Zone Total Internal Radiant Heating Rate')+matrix('Zone Total Internal Visible Radiation Heating Rate'))/1000
    solar=np.zeros_like(T)
    for i,z in enumerate(zones):
        for window in meta['windows'][z]:solar[:,i]+=get('Surface Window Transmitted Solar Radiation Rate',window)/1000
    setpoints=np.stack([matrix('Zone Thermostat Heating Setpoint Temperature'),matrix('Zone Thermostat Cooling Setpoint Temperature')],axis=-1)
    occupancy=matrix('Zone People Occupant Count')
    # Electrical energy per interval in kWh; no tariff enters RC fitting.
    electric=np.column_stack([get(name,'')/3.6e6 for name in ['Electricity:Facility','ElectricityProduced:Facility','ElectricityPurchased:Facility','ElectricitySurplusSold:Facility']])
    db.close()
    return Dataset(time,T,boundaries,hvac,conv,outdoor,causal_filter(rad,config.radiant_tau_hours,config.dt_hours),
                   causal_filter(solar,config.solar_tau_hours,config.dt_hours),setpoints,occupancy,electric,zones,
                   ['OUTDOOR']+plenums+['GROUND_IDF_MONTHLY'],meta,config.dt_hours)

def blocks(data,months,days):
    selected=np.flatnonzero(np.isin(data.time.month,months)&(data.time.day>=days[0])&(data.time.day<=days[1]))
    return [v for v in np.split(selected,np.flatnonzero(np.diff(selected)!=1)+1) if len(v)]

def split_blocks(data,config):
    result={'train':blocks(data,config.train_months,config.train_days),
            'validation':blocks(data,config.train_months,config.validation_days),
            'test':blocks(data,config.test_months,config.test_days)}
    # Exclude first day to remove causal filter initialisation transients.
    result['train']=[b[b>=round(24/data.dt)] for b in result['train']]
    for k,b in result.items():
        if not b or any(len(v)<config.sg_window+2 for v in b): raise ValueError(f'Insufficient {k} data')
    sets={k:set(np.concatenate(v)) for k,v in result.items()}
    assert not sets['train']&sets['validation'] and not sets['train']&sets['test'] and not sets['validation']&sets['test']
    return result
