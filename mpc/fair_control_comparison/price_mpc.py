"""Version 3: explicit hourly electricity cost added to the frozen v2 policy search.

Imported v2 files and fitted models remain reproducible. Prices are a declared
8760-hour scenario, not a claim that ambiguous supplier labels were repaired.
"""
from dataclasses import dataclass
from pathlib import Path
import csv, hashlib, json, time
from datetime import datetime
import numpy as np
import pandas as pd
from mpc_workflow.revised import RevisedConfig, RevisedRun, SAT_LEVELS, rollout, scheduled_on
from mpc_workflow.runtime import CoupledRun


class HourlyPrices:
    def __init__(self, path, shift_hours=0):
        self.path=Path(path); self.shift_hours=int(shift_hours)
        with self.path.open(encoding='utf-8-sig',newline='') as f:
            records=list(csv.DictReader(f))
        if len(records)!=8760: raise ValueError('Expected exactly 8760 hourly prices')
        self.values=np.array([float(r['Hourly Price ($/kWh)']) for r in records])
        if not np.isfinite(self.values).all(): raise ValueError('Nonfinite prices')
        labels=[r['Date & Hour Ending'] for r in records]
        dates=[]
        for value in labels:
            fmt='%m/%d/%Y %I:%M:%S %p' if ('AM' in value or 'PM' in value) else '%m/%d/%Y %H:%M'
            dates.append(datetime.strptime(value,fmt))
        ordinal=pd.date_range('2025-01-01',periods=8760,freq='h')
        offset=(pd.DatetimeIndex(dates)-ordinal).total_seconds()/3600
        unique,counts=np.unique(offset,return_counts=True)
        self.audit=dict(source=str(self.path),sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),rows=8760,
            duplicate_labels=len(labels)-len(set(labels)),label_minus_ordinal_hours=dict(zip(map(str,unique),map(int,counts))),
            minimum_USD_per_kWh=float(self.values.min()),maximum_USD_per_kWh=float(self.values.max()),
            negative_price_hours=int((self.values<0).sum()),shift_hours=self.shift_hours,
            convention='Row 0 is assigned to Jan 1 00:00-01:00 in a consecutive non-leap standard-time scenario. Map simulation month/day/hour to that sequence. Original labels retained; no inferred DST correction.',
            limitation='Hour-ending header, mixed label formats and DST anomalies prevent certifying original settlement alignment. +/-1 hour reruns assess local timing sensitivity, not complete calendar uncertainty.',
            forecast='Perfect future historical prices, benchmark only; not an operational forecast.',
            tariff_scope='Supplied hourly energy price only; zero export credit; excludes delivery charges, taxes, demand charges and fixed fees.')

    def at(self,t):
        t=pd.Timestamp(t)
        if t.month==2 and t.day==29: raise ValueError('Leap day is not supported')
        ref=pd.Timestamp(year=2025,month=t.month,day=t.day,hour=t.hour)
        i=int((ref-pd.Timestamp('2025-01-01')).total_seconds()//3600)
        return float(self.values[(i+self.shift_hours)%8760])

    def average(self,start,hours):
        """Exact piecewise-constant integration, including hour boundaries."""
        t=pd.Timestamp(start);end=t+pd.Timedelta(hours=hours)
        if hours<=0: raise ValueError('Interval must have positive duration')
        value=0.
        while t<end:
            stop=min(end,t.floor('h')+pd.Timedelta(hours=1))
            value+=self.at(t)*(stop-t).total_seconds()/3600
            t=stop
        return value/hours


@dataclass
class PriceConfig(RevisedConfig):
    version: str='energy_grid_price_v3'
    price_path: str=''
    price_shift_hours: int=0
    # Fixed before simulations: one USD costs 20 objective units.
    price_reference_USD_per_kWh: float=0.05
    price_weight: float=5.0
    scenarios: tuple=('conventional','reduced_renewable','reduced_price')


def score(trajectory,power,policy,sats,forecast,last_command,last_sat,c):
    if c.price_reference_USD_per_kWh<=0:raise ValueError('Price reference must be positive')
    dt=c.control_hours;upper=forecast['upper'];lower=forecast['lower']
    violation=np.maximum(trajectory-upper,0)+np.maximum(lower-trajectory,0)
    grid_power=np.maximum(forecast['base']+power-forecast['pv'],0)
    energy=float(power.sum()*dt);grid=float(grid_power.sum()*dt)
    cost=float(np.dot(forecast['price'],grid_power)*dt)
    risk=np.maximum(trajectory-(upper-c.comfort_margin*forecast['occupied']),0)+np.maximum(lower-trajectory,0)
    movement=np.abs(np.diff(np.vstack([last_command,policy]),axis=0)).sum()
    sat_move=np.abs(np.diff(np.r_[last_sat,sats])).sum()
    objective=(grid+c.renewable_hvac_weight*energy+c.price_weight*cost/c.price_reference_USD_per_kWh
               +c.comfort_weight*risk.sum()*dt+.05*movement+.1*sat_move)
    return float(objective),energy,float(violation.sum()),grid,cost


def choose_price(model,f,current,last_command,disturbance,profiles,coeff,c,last_sat):
    started=time.perf_counter();h=len(f['pv']);upper=f['upper'];lower=f['lower']
    policies=[('scheduled',upper.copy())]
    for margin in [c.comfort_margin,c.max_precooling]:
        sp=upper.copy()
        if margin==c.comfort_margin: sp-=margin*f['occupied']
        else: sp-=margin*(f['pv']>f['base']+5)[:,None]
        policies.append((f'offset_{margin:g}',np.maximum(sp,lower+.5)))
    base_sat=np.full(h,12.8)
    base=rollout(model,f,current,disturbance,profiles,upper,base_sat,coeff,c)
    bm=score(base[0],base[1],upper,base_sat,f,last_command,last_sat,c)
    candidates=[]
    for label,policy in policies:
        for sat in SAT_LEVELS if c.supply_reset else [12.8]:
            sats=np.where(f['on']>0,sat,12.8)
            tr,p,q=rollout(model,f,current,disturbance,profiles,policy,sats,coeff,c)
            metrics=score(tr,p,policy,sats,f,last_command,last_sat,c)
            ok=metrics[1]<=bm[1]+1e-7 and metrics[2]<=bm[2]+1e-7 and metrics[4]<=bm[4]+1e-7
            if label=='scheduled' and sat==12.8: ok=True
            if ok: candidates.append((metrics[0],label,float(sats[0]),policy,q,metrics))
    best=min(candidates,key=lambda item:item[0]);_,label,sat,policy,q,m=best
    diag=dict(success=True,status=0,message='Same nine v2 policies; added price objective and cost guard',
        solve_seconds=time.perf_counter()-started,objective=m[0],policy=label,supply_temperature_C=sat,
        predicted_HVAC_kWh=m[1],baseline_predicted_HVAC_kWh=bm[1],predicted_grid_kWh=m[3],
        predicted_import_cost_USD=m[4],baseline_import_cost_USD=bm[4],
        predicted_comfort_degree_hours=m[2]*c.control_hours,baseline_comfort_degree_hours=bm[2]*c.control_hours,
        price_first_USD_per_kWh=float(f['price'][0]),price_min_USD_per_kWh=float(min(f['price'])),
        price_max_USD_per_kWh=float(max(f['price'])),candidates_accepted=len(candidates),dynamics_residual=0.)
    return dict(command=policy[0].copy(),planned_cooling=q[0],sat=sat),diag


class PriceRun(RevisedRun):
    def __init__(self,c,scenario):
        super().__init__(c,scenario)
        self.prices=HourlyPrices(c.price_path,c.price_shift_hours)

    def begin(self,state):
        # Initialise the clock and measurements without invoking either old optimiser.
        name=self.scenario;old_last=self.last_control_time;old_command=self.command
        self.scenario='conventional';CoupledRun.begin(self,state);self.scenario=name
        self.component_energy[:]=0
        active=pd.Timestamp(self.c.start)<=self.zone_begin_time<pd.Timestamp(self.c.start)+pd.Timedelta(days=self.c.days)
        if not active:self.sat=12.8;return
        self.active=True;self.last_control_time=old_last;self.command=old_command
        if old_last is not None and (self.zone_begin_time-old_last).total_seconds()<self.c.control_hours*3600-1:return
        f=self.forecast.horizon(self.zone_begin_time,self.current_temperature,self.current_plenums)
        times=[self.zone_begin_time+pd.Timedelta(hours=k*self.c.control_hours) for k in range(len(f['pv']))]
        f['on']=np.array([scheduled_on(t) for t in times])
        f['outdoor']=np.array([self.forecast.data['outdoor'][self.forecast.index(t)] for t in times])
        f['price']=np.array([self.prices.average(t,self.c.control_hours) for t in times])
        result,diag=choose_price(self.model,f,self.current_temperature,self.command,self.observer.d,self.forecast.data,self.coeff,self.c,self.sat)
        self.command=result['command'];self.planned_cooling=result['planned_cooling'];self.sat=result['sat']
        self.last_control_time=self.zone_begin_time;diag['time']=str(self.zone_begin_time);self.decisions.append(diag)
        if len(self.decisions)%48==0:print(f'{name}: {self.zone_begin_time}',flush=True)
