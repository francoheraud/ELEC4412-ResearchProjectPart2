"""Direct setpoint policy MPC and independently measured air-system electricity.

The RC model rolls out candidate thermostat policies with a saturated local
thermostat response. Cooling power is a consequence, not an independent actuator.
"""
from dataclasses import dataclass
import json,time
import numpy as np
import pandas as pd
from .config import Config
from .runtime import CoupledRun

SAT_LEVELS=np.array([12.8,14.0,15.5])

@dataclass
class RevisedConfig(Config):
    version: str='direct_setpoint_v2'
    mode: str='evaluate'
    electrical_path: str=''
    # A registered additional HVAC strategy, separable from RC reduction.
    supply_reset: bool=True
    comfort_margin: float=0.05
    max_precooling: float=0.5
    start: str='2017-08-28'
    scenarios: tuple=('conventional','reduced_energy','reduced_renewable','dense_renewable','reduced_renewable_no_correction','scheduled_supply_reset')

def scheduled_on(t):
    t=pd.Timestamp(t)
    # Matches this IDF's HVACOperationSchd. No holiday during development;
    # Labor Day lies in the conventional recovery day, not MPC evaluation.
    return float((t.weekday()<5 and 6<=t.hour<22) or (t.weekday()==5 and 6<=t.hour<18))

def rollout(model,forecast,current,disturbance,profiles,policy,sat,coeff,config):
    A,Bq,Bv=model.discretize(config.control_hours);Bq_zone=Bq[:model.n];diag=np.diag(Bq_zone)
    state=model.state.copy();state[:model.n]=current;temps=[];powers=[];cool=[]
    groups=profiles['groups'];cap=profiles['capacity'];gc=profiles['group_capacity']
    for k,sp in enumerate(policy):
        free=A@state+Bv@forecast['forcing'][k]+Bq@disturbance
        # Solve the monotone, saturated thermostat response approximately by
        # fixed-point sweeps, retained from the original controller.
        q=np.maximum((free[:model.n]-sp)/diag,0.)
        warm=np.clip((np.maximum(state[:model.n],22)-sat[k])/(np.maximum(state[:model.n],22)-12.8),.4,1.)
        zonecap=cap*warm
        for _ in range(4):
            q=np.clip((free[:model.n]-sp-(Bq_zone@q-diag*q))/diag,0,zonecap)
            for g in range(3):
                members=groups==g;total=q[members].sum();limit=gc[g]*warm[members].min()
                if total>limit:q[members]*=limit/total
        state=free-Bq@q
        # Retain scheduled local heating; estimated electrical heating cost is
        # conservative and does not provide an optimised heating actuator.
        heating=np.maximum((forecast['lower'][k]-state[:model.n])/diag,0)
        state+=Bq@heating
        p=0.;level=int(np.argmin(np.abs(SAT_LEVELS-sat[k])))
        for g in range(3):
            total=q[groups==g].sum();on=max(forecast['on'][k],float(total>.1))
            feat=np.array([total,on,max(forecast['outdoor'][k]-18,0)*on])
            p+=max(0,float(feat@coeff[level,g]))
        p+=heating.sum()
        temps.append(state[:model.n].copy());powers.append(p);cool.append(q.copy())
    return np.array(temps),np.array(powers),np.array(cool)

def choose(model,forecast,current,last_command,disturbance,profiles,coeff,config,renewable,last_sat):
    started=time.perf_counter();h=len(forecast['pv']);upper=forecast['upper'];lower=forecast['lower']
    # The conventional policy is explicitly evaluated from the SAME state.
    policies=[('scheduled',upper.copy())]
    for margin in [config.comfort_margin,config.max_precooling]:
        sp=upper.copy()
        if margin==config.comfort_margin:
            sp-=margin*forecast['occupied']
        else:
            # Precool only during forecast surplus, not all daylight hours.
            sp-=margin*(forecast['pv']>forecast['base']+5)[:,None]
        policies.append((f'offset_{margin:g}',np.maximum(sp,lower+.5)))
    baseline=rollout(model,forecast,current,disturbance,profiles,upper,np.ones(h)*12.8,coeff,config)
    def evaluate(trajectory,power,policy,sats):
        violation=np.maximum(trajectory-upper,0)+np.maximum(lower-trajectory,0)
        energy=power.sum()*config.control_hours
        grid=np.maximum(forecast['base']+power-forecast['pv'],0).sum()*config.control_hours
        movement=np.abs(np.diff(np.vstack([last_command,policy]),axis=0)).sum()
        sat_move=np.abs(np.diff(np.r_[last_sat,sats])).sum()
        objective=(grid+config.renewable_hvac_weight*energy if renewable else energy)
        # Small engineering prediction-error buffer, not a claimed robust bound.
        # Report actual comfort against the ORIGINAL limits, never these targets.
        guarded_upper=upper-config.comfort_margin*forecast['occupied']
        risk=np.maximum(trajectory-guarded_upper,0)+np.maximum(lower-trajectory,0)
        return objective+config.comfort_weight*risk.sum()*config.control_hours+.05*movement+.1*sat_move,energy,float(violation.sum()),grid
    base_metrics=evaluate(baseline[0],baseline[1],upper,np.ones(h)*12.8)
    candidates=[]
    for label,policy in policies:
        for sat in SAT_LEVELS if config.supply_reset else [12.8]:
            # Warm supply reset only within the native scheduled fan period.
            sats=np.where(forecast['on']>0,sat,12.8)
            tr,p,q=rollout(model,forecast,current,disturbance,profiles,policy,sats,coeff,config)
            metrics=evaluate(tr,p,policy,sats)
            admissible=metrics[1]<=base_metrics[1]+1e-7 and metrics[2]<=base_metrics[2]+1e-7
            if label=='scheduled' and sat==12.8:admissible=True
            if admissible:candidates.append((metrics[0],label,float(sats[0]),policy,q,metrics))
    best=min(candidates,key=lambda item:item[0]);_,label,sat,policy,q,metrics=best
    # Execute the evaluated reference, not a post-optimisation transformation.
    # Candidate offsets are <=0.5 C; original schedule transitions are retained.
    command=policy[0].copy()
    diag=dict(success=True,status=0,message='finite direct-setpoint policy search',solve_seconds=time.perf_counter()-started,
        objective=best[0],policy=label,supply_temperature_C=sat,predicted_HVAC_kWh=metrics[1],baseline_predicted_HVAC_kWh=base_metrics[1],
        predicted_grid_kWh=metrics[3],predicted_comfort_degree_hours=metrics[2]*config.control_hours,
        candidates_accepted=len(candidates),dynamics_residual=0.)
    return dict(command=command,planned_cooling=q[0],sat=sat),diag

class RevisedRun(CoupledRun):
    def __init__(self,config,scenario):
        super().__init__(config,scenario)
        self.sat=12.8;self.component_rows=[];self.component_energy=np.zeros((3,3));self.previous_command=None
        self.coeff=None if config.mode=='train' or scenario=='conventional' else np.array(json.loads(open(config.electrical_path).read())['coefficients'])
        self.ex.request_variable(self.state,'Schedule Value','Seasonal-Reset-Supply-Air-Temp-Sch')
        for g in range(3):
            self.ex.request_variable(self.state,'Cooling Coil Electricity Rate',f'VAV_{g+1}_CoolC DXCoil')
            self.ex.request_variable(self.state,'Fan Electricity Rate',f'VAV_{g+1}_Fan')
        for z in self.model.zones:self.ex.request_variable(self.state,'Heating Coil Electricity Rate',z+' VAV Box Reheat Coil')

    def acquire(self,state):
        super().acquire(state)
        self.sat_handle=self.ex.get_actuator_handle(state,'Schedule:Compact','Schedule Value','Seasonal-Reset-Supply-Air-Temp-Sch')
        self.sat_sensor=self.ex.get_variable_handle(state,'Schedule Value','Seasonal-Reset-Supply-Air-Temp-Sch')
        self.component_handles=[]
        for g in range(3):
            self.component_handles.append([self.ex.get_variable_handle(state,'Cooling Coil Electricity Rate',f'VAV_{g+1}_CoolC DXCoil'),
                self.ex.get_variable_handle(state,'Fan Electricity Rate',f'VAV_{g+1}_Fan')])
        self.reheat_handles=[self.ex.get_variable_handle(state,'Heating Coil Electricity Rate',z+' VAV Box Reheat Coil') for z in self.model.zones]
        if min([self.sat_handle,self.sat_sensor]+sum(self.component_handles,[])+self.reheat_handles)<0:raise ValueError('Missing component/SAT handles')

    def begin(self,state):
        # Reuse plant clock and measurements, without invoking the old optimiser.
        name=self.scenario;old_last=self.last_control_time;old_command=self.command
        self.scenario='conventional';super().begin(state);self.scenario=name
        self.component_energy[:]=0
        active=pd.Timestamp(self.c.start)<=self.zone_begin_time<pd.Timestamp(self.c.start)+pd.Timedelta(days=self.c.days)
        if not active:self.sat=12.8;return
        if self.c.mode=='train':
            # Independent, deterministic two-hour blocks, balanced over floors.
            k=int((self.zone_begin_time-pd.Timestamp(self.c.start)).total_seconds()//7200)
            rng=np.random.default_rng(self.c.seed+k)
            self.sat=float(SAT_LEVELS[rng.integers(len(SAT_LEVELS))]);return
        if name=='conventional':return
        self.active=True;self.last_control_time=old_last;self.command=old_command
        if old_last is not None and (self.zone_begin_time-old_last).total_seconds()<self.c.control_hours*3600-1:return
        f=self.forecast.horizon(self.zone_begin_time,self.current_temperature,self.current_plenums)
        times=[self.zone_begin_time+pd.Timedelta(hours=k*self.c.control_hours) for k in range(len(f['pv']))]
        f['on']=np.array([scheduled_on(t) for t in times])
        f['outdoor']=np.array([self.forecast.data['outdoor'][self.forecast.index(t)] for t in times])
        if name=='scheduled_supply_reset':
            result=dict(command=f['upper'][0],planned_cooling=np.zeros(self.model.n),sat=15.5 if f['on'][0] else 12.8)
            diag=dict(success=True,status=0,message='Fixed reset comparator; no RC optimisation',solve_seconds=0.,objective=0.,policy='fixed_supply_reset',supply_temperature_C=result['sat'])
        else:result,diag=choose(self.model,f,self.current_temperature,self.command,self.observer.d,self.forecast.data,self.coeff,self.c,'renewable' in name,self.sat)
        self.command=result['command'];self.planned_cooling=result['planned_cooling'];self.sat=result['sat']
        self.last_control_time=self.zone_begin_time;diag['time']=str(self.zone_begin_time);self.decisions.append(diag)
        if len(self.decisions)%48==0:print(f'{name}: {self.zone_begin_time}',flush=True)

    def actuate(self,state):
        super().actuate(state)
        if self.zone_begin_time is None:return
        train_active=self.c.mode=='train' and pd.Timestamp(self.c.start)<=self.zone_begin_time<pd.Timestamp(self.c.start)+pd.Timedelta(days=self.c.days)
        if self.active or train_active:self.ex.set_actuator_value(state,self.sat_handle,self.sat)
        else:self.ex.reset_actuator(state,self.sat_handle)

    def system_end(self,state):
        super().system_end(state)
        if self.zone_begin_time is None:return
        dt=self.ex.system_time_step(state)
        for g in range(3):
            self.component_energy[g,:2]+=np.array([self.ex.get_variable_value(state,h) for h in self.component_handles[g]])/1000*dt
            members=np.flatnonzero(self.forecast.data['groups']==g)
            self.component_energy[g,2]+=sum(self.ex.get_variable_value(state,self.reheat_handles[i]) for i in members)/1000*dt

    def end(self,state):
        super().end(state)
        for g in range(3):
            self.component_rows.append(dict(time=str(self.zone_begin_time),floor=g,cooling_kWh=self.component_energy[g,0],fan_kWh=self.component_energy[g,1],reheat_kWh=self.component_energy[g,2],
                supply_command_C=self.sat,supply_reported_C=self.ex.get_variable_value(state,self.sat_sensor)))

    def run(self):
        folder=super().run()
        pd.DataFrame(self.component_rows).to_csv(folder/'components.csv',index=False)
        return folder
