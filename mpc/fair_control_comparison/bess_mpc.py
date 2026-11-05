"""PV-only battery dispatch coupled to the existing finite-policy thermal MPC."""
from dataclasses import dataclass
from pathlib import Path
import json, time
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from price_mpc import PriceConfig, HourlyPrices
from mpc_workflow.revised import RevisedRun, rollout, scheduled_on, SAT_LEVELS
from mpc_workflow.runtime import CoupledRun
from hvac_policies import policy_candidates
from battery_tracking import track_surplus, track_export_policy

@dataclass
class BESSConfig(PriceConfig):
    export_price_factor: float=1.
    baseline_comfort_guard: bool=True
    anticipatory_policies: bool=False
    schedule_clock_correction: bool=False
    source_folder: str=''
    coverage: int=80
    horizon_hours: float=24.
    price_weight: float=1.
    grid_import_weight: float=1.
    hvac_only_energy_weight: float=1.
    battery_throughput_weight: float=.01
    setpoint_movement_weight: float=.05
    sat_movement_weight: float=.10
    policy_family: str='legacy'
    precooling_offsets_C: tuple=(.5,1.,1.5)
    preoccupancy_hours: float=2.
    allow_dynamic_sat: bool=True
    max_hvac_energy_increase_fraction: float=0.
    freeze_battery_during_warmup: bool=True
    battery_name: str='Thesis NMC Battery'
    battery_type: str='NMC'
    capacity_kWh: float=206.6265024
    power_kW: float=50.
    eta_charge: float=.90
    eta_discharge: float=.90
    inverter_efficiency: float=.96
    soc_min: float=.24
    soc_max: float=.92
    @property
    def source(self): return Path(self.source_folder)

def dispatch(load, pv_ac, prices, soc, c):
    """Linear dispatch, with charge/discharge signs fixed by net PV availability.

    E[k+1]=E[k]+dt*(eta_c*charge-discharge/eta_d); powers are DC.
    No grid charging, battery exports, or simultaneous charge/discharge.
    Terminal nominal energy retains a fixed reserve; it does not ratchet upward
    when midday solar charging raises the current SOC.
    """
    n=len(load);dt=c.control_hours;eta=c.inverter_efficiency
    deficit=np.maximum(load-pv_ac,0);surplus=np.maximum(pv_ac-load,0)/eta
    initial=float(np.clip(soc,0,1))*c.capacity_kWh
    floor=min(c.soc_min*c.capacity_kWh,initial)
    ceiling=max(c.soc_max*c.capacity_kWh,initial)
    weight=c.grid_import_weight+c.price_weight*np.asarray(prices)/c.price_reference_USD_per_kWh
    # Charging diverts PV from export. Include that opportunity cost and the
    # policy-dependent constant for PV that would otherwise be exported.
    sell=c.export_price_factor*np.asarray(prices)
    export_weight=c.price_weight*sell/c.price_reference_USD_per_kWh
    objective=np.r_[(eta*export_weight+c.battery_throughput_weight)*dt,
                    (-eta*weight+c.battery_throughput_weight)*dt,np.zeros(n)]
    eq=np.zeros((n,3*n));rhs=np.zeros(n);rhs[0]=initial
    for k in range(n):
        eq[k,k]=-dt*c.eta_charge;eq[k,n+k]=dt/c.eta_discharge;eq[k,2*n+k]=1
        if k:eq[k,2*n+k-1]=-1
    bounds=[(0,min(c.power_kW,x)) for x in surplus]+[(0,min(c.power_kW,x/eta)) for x in deficit]+[(floor,ceiling)]*n
    bounds[-1]=(floor,ceiling)
    result=linprog(objective,A_eq=eq,b_eq=rhs,bounds=bounds,method='highs')
    if not result.success:raise RuntimeError('Battery dispatch failed: '+result.message)
    charge=result.x[:n];discharge=result.x[n:2*n];grid=deficit-eta*discharge
    exported=np.maximum(0,eta*(surplus-charge))
    return dict(charge=charge,discharge=discharge,energy=result.x[2*n:],grid=grid,
                export=exported, import_cost=float(dt*np.dot(prices,grid)),
                export_credit=float(dt*np.dot(sell,exported)),
                objective=float(result.fun+dt*np.dot(weight,deficit)-dt*np.dot(export_weight,eta*surplus)))

class BESSRun(RevisedRun):
    def __init__(self,c,scenario):
        super().__init__(c,scenario)
        self.prices=HourlyPrices(c.price_path);self.battery_rows=[];self.battery_steps=[]
        self.battery_command=np.zeros(2);self.battery_integral=np.zeros(4)
        self.planned_export_ac=0.;self.horizon_records=[]
        self.sensor_specs={
          'soc':('Electric Storage Charge Fraction',c.battery_name),
          'charge':('Electric Storage Charge Power',c.battery_name),
          'discharge':('Electric Storage Discharge Power',c.battery_name),
          'pv_dc':('Generator Produced DC Electricity Rate','Thesis Roof PV'),
          'inverter_ac':('Inverter AC Output Electricity Rate','Thesis PV Inverter'),
          'load':('Facility Total Electricity Demand Rate','Whole Building')}
        for name,key in self.sensor_specs.values():self.ex.request_variable(self.state,name,key)
        self.warmup_battery_handles=None;self.warmup_battery_overridden=False
        self.guarded_battery_actuate=self.guard(self.battery_actuate)
        self.api.runtime.callback_inside_system_iteration_loop(self.state,self.battery_iteration)

    def battery_iteration(self,state):
        """Prevent unreported solar charging during repeated EnergyPlus warmup days."""
        if self.failed or self.ex.kind_of_sim(state)!=3 or not self.ex.api_data_fully_ready(state):return
        try:
            if self.c.freeze_battery_during_warmup and self.ex.warmup_flag(state):
                if self.warmup_battery_handles is None:
                    self.warmup_battery_handles=[self.ex.get_actuator_handle(state,'Electrical Storage',kind,'Thesis Grid Connected PV') for kind in ['Power Charge Rate','Power Draw Rate']]
                    if min(self.warmup_battery_handles)<0:raise RuntimeError('Missing battery warmup actuators')
                for h in self.warmup_battery_handles:self.ex.set_actuator_value(state,h,0.)
                self.warmup_battery_overridden=True
                return
            if self.warmup_battery_overridden:
                for h in self.warmup_battery_handles:self.ex.reset_actuator(state,h)
                self.warmup_battery_overridden=False
            self.guarded_battery_actuate(state)
        except Exception:
            import traceback
            self.failed=True;self.failures.append(traceback.format_exc());self.api.runtime.stop_simulation(state)

    def acquire(self,state):
        super().acquire(state)
        self.bh={key:self.ex.get_variable_handle(state,*spec) for key,spec in self.sensor_specs.items()}
        self.ba=[self.ex.get_actuator_handle(state,'Electrical Storage',kind,'Thesis Grid Connected PV') for kind in ['Power Charge Rate','Power Draw Rate']]
        if min(list(self.bh.values())+self.ba)<0:
            (self.folder/'available_api.csv').write_bytes(self.ex.list_available_api_data_csv(state))
            raise RuntimeError(f'Battery handles missing: {self.bh}, {self.ba}')

    def begin(self,state):
        name=self.scenario;old_last=self.last_control_time;old_command=self.command
        self.scenario='conventional';CoupledRun.begin(self,state);self.scenario=name
        self.component_energy[:]=0;self.battery_integral[:]=0
        self.start_soc=self.ex.get_variable_value(state,self.bh['soc'])
        self.battery_active=(pd.Timestamp(self.c.start)<=self.zone_begin_time<pd.Timestamp(self.c.start)+pd.Timedelta(days=self.c.days) and name=='coordinated_mpc')
        if not (pd.Timestamp(self.c.start)<=self.zone_begin_time<pd.Timestamp(self.c.start)+pd.Timedelta(days=self.c.days)):
            self.sat=12.8;return
        if name=='conventional':return
        self.active=True;self.command=old_command;self.last_control_time=old_last
        if old_last is not None and (self.zone_begin_time-old_last).total_seconds()<self.c.control_hours*3600-1:return
        started=time.perf_counter();c=self.c
        f=self.forecast.horizon(self.zone_begin_time,self.current_temperature,self.current_plenums)
        times=[self.zone_begin_time+pd.Timedelta(hours=k*c.control_hours) for k in range(len(f['pv']))]
        f['on']=np.array([scheduled_on(t) for t in times]);f['outdoor']=np.array([self.forecast.data['outdoor'][self.forecast.index(t)] for t in times])
        prices=np.array([self.prices.average(t,c.control_hours) for t in times]);h=len(times)
        f['prices']=prices
        if c.schedule_clock_correction:
            # August reference plant applies daylight saving to schedule lookup.
            # Native schedules/actuators remain unchanged. This is forecast-only.
            dst=float(self.ex.daylight_savings_time_indicator(state))
            f['on']=np.array([scheduled_on(t+pd.Timedelta(hours=dst)) for t in times])
        upper=f['upper'];lower=f['lower']
        baseline=rollout(self.model,f,self.current_temperature,self.observer.d,self.forecast.data,upper,np.full(h,12.8),self.coeff,c)
        base_energy=baseline[1].sum()*c.control_hours
        base_violation=(np.maximum(baseline[0]-upper,0)+np.maximum(lower-baseline[0],0)).sum()
        candidates=[]
        options=policy_candidates(f,baseline[1],baseline[2],self.forecast.data,c)
        rejected_energy=0;rejected_comfort=0
        for label,sat_label,policy,sats in options:
                tr,p,q=rollout(self.model,f,self.current_temperature,self.observer.d,self.forecast.data,policy,sats,self.coeff,c)
                energy=p.sum()*c.control_hours;violation=(np.maximum(tr-upper,0)+np.maximum(lower-tr,0)).sum()
                if energy>base_energy*(1+c.max_hvac_energy_increase_fraction)+1e-7:
                    rejected_energy+=1;continue
                if c.baseline_comfort_guard and violation>base_violation+1e-7:
                    rejected_comfort+=1;continue
                battery=dispatch(f['base']+p,f['pv'],prices,self.start_soc,c) if name=='coordinated_mpc' else None
                # HVAC-only comparator deliberately has no battery/PV/price objective.
                objective=battery['objective']+c.renewable_hvac_weight*energy if battery is not None else c.hvac_only_energy_weight*energy
                risk=(np.maximum(tr-(upper-c.comfort_margin*f['occupied']),0)+np.maximum(lower-tr,0)).sum()*c.control_hours
                movement=np.abs(np.diff(np.vstack([self.command,policy]),axis=0)).sum()
                sat_movement=np.abs(np.diff(np.r_[self.sat,sats])).sum()
                objective+=c.comfort_weight*risk+c.setpoint_movement_weight*movement+c.sat_movement_weight*sat_movement
                candidates.append((objective,label,policy,q,sats,battery,energy,violation,sat_label,risk,movement,sat_movement))
        best=min(candidates,key=lambda v:v[0]);obj,label,policy,q,sats,bat,energy,violation,sat_label,risk,movement,sat_movement=best
        self.command=policy[0];self.planned_cooling=q[0];self.sat=float(sats[0])
        self.battery_command=np.array([bat['charge'][0],bat['discharge'][0]]) if bat else np.zeros(2)
        self.planned_export_ac=float(bat['export'][0]) if bat else 0.
        # Save the entire selected plan, not an interpolated or fabricated schedule.
        selected_t,selected_p,selected_q=rollout(self.model,f,self.current_temperature,self.observer.d,self.forecast.data,policy,sats,self.coeff,c)
        self.horizon_records.append(dict(time=str(self.zone_begin_time),temperature=selected_t,
            hvac_kW=selected_p,cooling_kW=selected_q,setpoint=policy.copy(),sat=sats.copy(),
            upper=upper.copy(),lower=lower.copy(),occupied=f['occupied'].copy(),
            pv=f['pv'].copy(),base=f['base'].copy(),prices=prices.copy(),
            grid=bat['grid'] if bat else np.full(h,np.nan),
            export=bat['export'] if bat else np.full(h,np.nan),
            charge=bat['charge'] if bat else np.zeros(h),discharge=bat['discharge'] if bat else np.zeros(h),
            energy=bat['energy'] if bat else np.full(h,np.nan)))
        self.last_control_time=self.zone_begin_time
        if len(self.decisions)%48==0:
            print(f'{name}: {self.zone_begin_time}; {len(self.decisions)+1} control updates; 45 RC states',flush=True)
        self.decisions.append(dict(time=str(self.zone_begin_time),objective=obj,policy=label,sat_policy=sat_label,supply_C=self.sat,charge_command_kW=self.battery_command[0],discharge_command_kW=self.battery_command[1],soc=self.start_soc,predicted_HVAC_kWh=energy,baseline_predicted_HVAC_kWh=base_energy,predicted_comfort_degree_hours=violation*c.control_hours,
            predicted_grid_kWh=float(bat['grid'].sum()*c.control_hours) if bat else np.nan,
            predicted_import_cost_USD=bat['import_cost'] if bat else np.nan,
            predicted_export_credit_USD=bat['export_credit'] if bat else np.nan,
            predicted_net_energy_cost_USD=bat['import_cost']-bat['export_credit'] if bat else np.nan,
            comfort_objective=c.comfort_weight*risk,setpoint_move_objective=c.setpoint_movement_weight*movement,sat_move_objective=c.sat_movement_weight*sat_movement,
            candidates_evaluated=len(options),candidates_accepted=len(candidates),rejected_energy=rejected_energy,rejected_comfort=rejected_comfort,
            solve_seconds=time.perf_counter()-started))

    def actuate(self,state):
        super().actuate(state)
        self.battery_actuate(state)

    def battery_actuate(self,state):
        if not getattr(self,'battery_active',False):
            for h in self.ba:self.ex.reset_actuator(state,h)
            return
        soc=self.ex.get_variable_value(state,self.bh['soc'])
        pv=max(0,self.ex.get_variable_value(state,self.bh['pv_dc'])/1000)
        load=max(0,self.ex.get_variable_value(state,self.bh['load'])/1000)
        # Respect planned export while responding to measured surplus changes.
        ch,dis=track_export_policy(self.battery_command[1],self.planned_export_ac,pv,load,soc,
                                  self.c.power_kW,self.c.inverter_efficiency,
                                  self.c.soc_min,self.c.soc_max)
        # The native battery model imposes its own voltage/SOC limits; commands are DC.
        for handle,value in zip(self.ba,[ch,dis]):self.ex.set_actuator_value(state,handle,float(value*1000))

    def system_end(self,state):
        super().system_end(state)
        if self.zone_begin_time is None:return
        vals=np.array([self.ex.get_variable_value(state,self.bh[k])/1000 for k in ['charge','discharge','pv_dc','inverter_ac']])
        dt=self.ex.system_time_step(state);self.battery_integral+=vals*dt
        load=self.ex.get_variable_value(state,self.bh['load'])/1000
        soc=self.ex.get_variable_value(state,self.bh['soc'])
        surplus=max(0,vals[2]-load/self.c.inverter_efficiency)
        self.battery_steps.append(dict(time=str(self.zone_begin_time),dt_hours=dt,soc=soc,charge_kW=vals[0],discharge_kW=vals[1],pv_DC_kW=vals[2],load_kW=load,charge_beyond_surplus_kW=max(0,vals[0]-surplus),
            tracker_active=bool(getattr(self,'battery_active',False)),
            planned_export_AC_kW=float(self.planned_export_ac),
            planned_charge_kW=float(self.battery_command[0]),planned_discharge_kW=float(self.battery_command[1]),
            measured_surplus_DC_kW=surplus,
            unused_charge_opportunity_kW=max(0,min(self.c.power_kW,surplus)-vals[0]) if soc<self.c.soc_max-1e-3 else 0.))

    def end(self,state):
        super().end(state)
        ch,dis,pv,ac=self.battery_integral
        self.rows[-1]['net_produced_kWh']=self.rows[-1].pop('pv_kWh')
        self.rows[-1]['pv_dc_kWh']=pv
        self.battery_rows.append(dict(time=str(self.zone_begin_time),phase=self.rows[-1]['phase'],start_soc=self.start_soc,end_soc=self.ex.get_variable_value(state,self.bh['soc']),charge_DC_kWh=ch,discharge_DC_kWh=dis,pv_DC_kWh=pv,inverter_AC_kWh=ac))

    def run(self):
        folder=super().run()
        pd.DataFrame(self.battery_rows).to_csv(folder/'battery.csv',index=False)
        pd.DataFrame(self.battery_steps).to_csv(folder/'battery_system_steps.csv',index=False)
        if self.horizon_records:
            np.savez_compressed(folder/'selected_horizons.npz',**{k:np.array([r[k] for r in self.horizon_records]) for k in self.horizon_records[0]})
        return folder
