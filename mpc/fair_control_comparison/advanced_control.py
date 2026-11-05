"""Finite-policy MPC with RC-predicted, time-varying SAT on each air system.

No new plant equipment. Original calibrated SAT levels and comfort bounds.
The sequential schedule builder is a heuristic candidate, not a global optimum.
"""
import itertools,time,json
import numpy as np
import pandas as pd
from bess_mpc import BESSRun,dispatch
from mpc_workflow.runtime import CoupledRun
from mpc_workflow.revised import SAT_LEVELS,scheduled_on
from hvac_policies import policy_candidates

def step_candidates(model,state,forcing,disturbance,lower,sp,outdoor,on,sats,profiles,coeff,c):
    A,Bq,Bv=model.discretize(c.control_hours);n=model.n;Bz=Bq[:n];diag=np.diag(Bz)
    free=A@state+Bv@forcing+Bq@disturbance
    groups=profiles['groups'];sat_zone=sats[:,groups]
    warm=np.clip((np.maximum(state[:n],22)[None,:]-sat_zone)/(np.maximum(state[:n],22)[None,:]-12.8),.4,1.)
    cap=profiles['capacity'][None,:]*warm
    q=np.broadcast_to(np.maximum((free[:n]-sp)/diag,0),(len(sats),n)).copy()
    for _ in range(4):
        cross=q@Bz.T-diag*q
        qmin=np.zeros_like(q)
        if getattr(c,'vav_minimum_flow',False) and on:
            # Existing terminal minimum air delivery. Implicit endpoint balance:
            # q_min=mCp*(T_end-SAT), T_end=free-cross-diag*q_min.
            # This is a sensible-heat predictor, not the full native moist-air model.
            mcp=1.2*1.006*profiles['minimum_airflow_m3_s'][None,:]
            qmin=np.maximum(0,(free[:n]-cross-sat_zone)/(1/mcp+diag))
            qmin=np.minimum(qmin,cap)
        q=np.clip((free[:n]-sp-cross)/diag,qmin,cap)
        for g in range(3):
            m=groups==g;total=q[:,m].sum(axis=1);limit=profiles['group_capacity'][g]*warm[:,m].min(axis=1)
            q[:,m]*=np.minimum(1,limit/np.maximum(total,1e-10))[:,None]
    states=free[None,:]-q@Bq.T
    heat=np.maximum((lower-states[:,:n])/diag,0);states+=heat@Bq.T
    power=heat.sum(axis=1)
    for g in range(3):
        total=q[:,groups==g].sum(axis=1);operating=np.maximum(on,(total>.1).astype(float))
        level=np.argmin(abs(SAT_LEVELS[None,:]-sats[:,g,None]),axis=1)
        feat=np.column_stack([total,operating,np.maximum(outdoor-18,0)*operating])
        power+=np.maximum(0,(feat*coeff[level,g,:]).sum(axis=1))
    return states,power,q

def simulate(model,f,current,d,profiles,policy,sats,coeff,c):
    state=model.state.copy();state[:model.n]=current;tr=[];p=[];qs=[]
    for k,sp in enumerate(policy):
        xx,pp,qq=step_candidates(model,state,f['forcing'][k],d,f['lower'][k],sp,f['outdoor'][k],f['on'][k],sats[k:k+1],profiles,coeff,c)
        state=xx[0];tr.append(state[:model.n].copy());p.append(pp[0]);qs.append(qq[0])
    return np.array(tr),np.array(p),np.array(qs)

def adaptive_schedule(model,f,current,d,profiles,policy,coeff,c,last_sat,independent=True):
    state=model.state.copy();state[:model.n]=current;seq=[]
    choices=np.array(list(itertools.product(SAT_LEVELS,repeat=3))) if independent else np.repeat(SAT_LEVELS[:,None],3,axis=1)
    previous=np.asarray(last_sat).copy()
    for k,sp in enumerate(policy):
        available=choices if f['on'][k] else np.full((1,3),12.8)
        xx,p,q=step_candidates(model,state,f['forcing'][k],d,f['lower'][k],sp,f['outdoor'][k],f['on'][k],available,profiles,coeff,c)
        risk=(np.maximum(xx[:,:model.n]-(f['upper'][k]-c.comfort_margin*f['occupied'][k]),0)+np.maximum(f['lower'][k]-xx[:,:model.n],0)).sum(axis=1)
        net=f['base'][k]+p-f['pv'][k]
        price=f['prices'][k]/c.price_reference_USD_per_kWh
        score=c.control_hours*(c.grid_import_weight*np.maximum(net,0)+c.price_weight*price*net+c.renewable_hvac_weight*p+c.comfort_weight*risk)
        score+=c.sat_movement_weight*np.abs(available-previous).mean(axis=1)
        j=int(np.argmin(score));state=xx[j];seq.append(available[j]);previous=available[j]
    return np.array(seq)

class AdvancedRun(BESSRun):
    def __init__(self,c,scenario,variant):
        self.variant=variant;self.sats=np.full(3,12.8);self.air_rows=[]
        c.vav_minimum_flow=variant.startswith(('independent_vav','shared_vav'))
        super().__init__(c,scenario)
        if c.vav_minimum_flow:
            from pathlib import Path
            specs=json.loads((Path(__file__).parent/'vav_minimum_flow.json').read_text())
            self.forecast.data['minimum_airflow_m3_s']=np.array([specs['zones'][z.upper()]['minimum_m3_s'] for z in self.model.zones])
        for g in range(3):self.ex.request_variable(self.state,'Schedule Value',f'Thesis SAT Floor {g+1}')
        for z in self.model.zones:self.ex.request_variable(self.state,'Zone Air Relative Humidity',z)
    def acquire(self,state):
        super().acquire(state)
        self.sat_handles=[self.ex.get_actuator_handle(state,'Schedule:Compact','Schedule Value',f'Thesis SAT Floor {g+1}') for g in range(3)]
        self.sat_sensors=[self.ex.get_variable_handle(state,'Schedule Value',f'Thesis SAT Floor {g+1}') for g in range(3)]
        self.rh_handles=[self.ex.get_variable_handle(state,'Zone Air Relative Humidity',z) for z in self.model.zones]
        if min(self.sat_handles+self.sat_sensors+self.rh_handles)<0:raise RuntimeError('Missing independent SAT/humidity handles')
    def begin(self,state):
        name=self.scenario;old_last=self.last_control_time;old_command=self.command
        self.scenario='conventional';CoupledRun.begin(self,state);self.scenario=name
        self.component_energy[:]=0;self.battery_integral[:]=0
        self.start_soc=self.ex.get_variable_value(state,self.bh['soc'])
        active=pd.Timestamp(self.c.start)<=self.zone_begin_time<pd.Timestamp(self.c.start)+pd.Timedelta(days=self.c.days)
        self.battery_active=active and name=='coordinated_mpc'
        if not active or name=='conventional':self.sats[:]=12.8;self.sat=12.8;return
        self.active=True;self.command=old_command;self.last_control_time=old_last
        if old_last is not None and (self.zone_begin_time-old_last).total_seconds()<self.c.control_hours*3600-1:return
        started=time.perf_counter();c=self.c
        f=self.forecast.horizon(self.zone_begin_time,self.current_temperature,self.current_plenums)
        times=[self.zone_begin_time+pd.Timedelta(hours=k*c.control_hours) for k in range(len(f['pv']))]
        dst=float(self.ex.daylight_savings_time_indicator(state))
        f['on']=np.array([scheduled_on(t+pd.Timedelta(hours=dst)) for t in times])
        f['outdoor']=np.array([self.forecast.data['outdoor'][self.forecast.index(t)] for t in times])
        f['prices']=np.array([self.prices.average(t,c.control_hours) for t in times])
        args=(self.model,f,self.current_temperature,self.observer.d,self.forecast.data)
        h=len(times);upper=f['upper'];lower=f['lower']
        base=simulate(*args,upper,np.full((h,3),12.8),self.coeff,c);be=base[1].sum()*c.control_hours
        raw=policy_candidates(f,base[1],base[2],self.forecast.data,c)
        options=[(label,satlabel,sp,np.repeat(s[:,None],3,axis=1)) for label,satlabel,sp,s in raw]
        if self.variant!='shared_original':
            policies={label:sp for label,_,sp,_ in raw}
            for label,sp in policies.items():
                ss=adaptive_schedule(*args,sp,self.coeff,c,self.sats,independent=not self.variant.startswith('shared'))
                options.append((label,'RC_adaptive_'+self.variant,sp,ss))
        accepted=[];rejected=0
        for label,slabel,sp,ss in options:
            tr,p,q=simulate(*args,sp,ss,self.coeff,c);energy=p.sum()*c.control_hours
            if energy>be*(1+c.max_hvac_energy_increase_fraction)+1e-7:rejected+=1;continue
            bat=dispatch(f['base']+p,f['pv'],f['prices'],self.start_soc,c) if name=='coordinated_mpc' else None
            risk=(np.maximum(tr-(upper-c.comfort_margin*f['occupied']),0)+np.maximum(lower-tr,0)).sum()*c.control_hours
            movement=np.abs(np.diff(np.vstack([self.command,sp]),axis=0)).sum()
            satmove=np.abs(np.diff(np.vstack([self.sats,ss]),axis=0)).sum()/3
            objective=(bat['objective']+c.renewable_hvac_weight*energy if bat else c.hvac_only_energy_weight*energy)+c.comfort_weight*risk+c.setpoint_movement_weight*movement+c.sat_movement_weight*satmove
            accepted.append((objective,label,slabel,sp,ss,tr,p,q,bat,energy,risk))
        best=min(accepted,key=lambda v:v[0]);obj,label,slabel,sp,ss,tr,p,q,bat,energy,risk=best
        self.command=sp[0].copy();self.sats=ss[0].copy();self.sat=float(self.sats.mean());self.planned_cooling=q[0].copy()
        self.battery_command=np.array([bat['charge'][0],bat['discharge'][0]]) if bat else np.zeros(2)
        self.planned_export_ac=float(bat['export'][0]) if bat else 0
        if bat and self.variant.endswith('vav_corrected'):
            from test_battery_feedback import intentional_export
            self.planned_export_ac=intentional_export(self.planned_export_ac,max(0.,f['pv'][0]-f['base'][0]-p[0]),c.power_kW,c.inverter_efficiency)
        self.horizon_records.append(dict(time=str(self.zone_begin_time),temperature=tr,hvac_kW=p,cooling_kW=q,setpoint=sp.copy(),sat=ss.copy(),upper=upper.copy(),lower=lower.copy(),occupied=f['occupied'].copy(),pv=f['pv'].copy(),base=f['base'].copy(),prices=f['prices'].copy(),**{k:bat[k] if bat else np.zeros(h) for k in ['grid','export','charge','discharge','energy']}))
        self.last_control_time=self.zone_begin_time
        self.decisions.append(dict(time=str(self.zone_begin_time),objective=obj,policy=label,sat_policy=slabel,**{f'supply_floor{g+1}_C':self.sats[g] for g in range(3)},soc=self.start_soc,predicted_HVAC_kWh=energy,baseline_predicted_HVAC_kWh=be,predicted_comfort_degree_hours=risk,candidates_accepted=len(accepted),rejected_energy=rejected,solve_seconds=time.perf_counter()-started))
        if len(self.decisions)%48==1:print(f'{self.variant}: {self.zone_begin_time}',flush=True)
    def actuate(self,state):
        # Same thermostat/local controls and battery feedback as the source study.
        CoupledRun.actuate(self,state)
        for handle,value in zip(self.sat_handles,self.sats):
            if self.active:self.ex.set_actuator_value(state,handle,float(value))
            else:self.ex.reset_actuator(state,handle)
        self.battery_actuate(state)
    def end(self,state):
        super().end(state)
        for g in range(3):
            self.component_rows[-3+g]['supply_command_C']=float(self.sats[g])
            self.component_rows[-3+g]['supply_reported_C']=self.ex.get_variable_value(state,self.sat_sensors[g])
        for z,h in zip(self.model.zones,self.rh_handles):self.air_rows.append(dict(time=str(self.zone_begin_time),zone=z,RH_percent=self.ex.get_variable_value(state,h)))
    def run(self):
        folder=super().run();pd.DataFrame(self.air_rows).to_csv(folder/'humidity.csv',index=False);return folder
