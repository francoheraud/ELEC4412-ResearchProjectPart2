"""EnergyPlus Python API callbacks and guarded thermostat actuation."""
from pathlib import Path
import sys,json,re,traceback
import numpy as np
import pandas as pd
from .thermal import ThermalModel,DisturbanceObserver
from .forecast import Forecast
from .optimizer import solve

def idf_objects(text):return [[f.strip() for f in s.split(',')] for s in re.sub(r'!.*','',text).split(';') if s.strip()]

def replace(text,kind,fields):
    pattern=re.compile(r'(?mi)^\s*'+re.escape(kind)+r'\s*,[^;]*;');matches=list(pattern.finditer(text))
    if len(matches)!=1:raise ValueError(f'{kind}: {len(matches)} objects')
    m=matches[0];return text[:m.start()]+'\n'+kind+',\n'+',\n'.join(fields)+';'+text[m.end():]

def make_idf(config,folder):
    source=next(config.source.glob('*.idf'));text=source.read_text(encoding='utf-8-sig');obs=idf_objects(text)
    start=pd.Timestamp(config.start)-pd.Timedelta(days=config.preconditioning_days)
    end=pd.Timestamp(config.start)+pd.Timedelta(days=config.days+config.recovery_days-1)
    run=next(o[1:] for o in obs if o[0].lower()=='runperiod')
    run[:8]=['MPC controlled benchmark',str(start.month),str(start.day),str(start.year),str(end.month),str(end.day),str(end.year),start.day_name()]
    text=replace(text,'RunPeriod',run)
    # Sizing is preserved, but simulation callbacks skip all sizing and warmup environments.
    additions=['Output:Variable,*,Zone Thermostat Cooling Setpoint Temperature,Timestep;',
               'Output:Variable,*,Zone Thermostat Heating Setpoint Temperature,Timestep;',
               'Output:Variable,*,Zone Air System Sensible Heating Rate,Timestep;',
               'Output:Variable,*,Zone Air System Sensible Cooling Rate,Timestep;']
    known={tuple(f.lower() for f in o) for o in idf_objects(text)}
    for item in additions:
        if tuple(f.lower() for f in idf_objects(item)[0]) not in known:text+='\n'+item
    path=folder/'model.idf';path.write_text(text,encoding='utf-8');return path

class CoupledRun:
    def __init__(self,config,scenario):
        self.c=config;self.scenario=scenario;self.folder=config.output/'runs'/scenario;self.folder.mkdir(parents=True,exist_ok=True)
        self.model=ThermalModel(config.rc/'thermal_model.npz')
        self.forecast=Forecast(config.output/'forecast_profiles.npz',config)
        if self.model.zones!=self.forecast.data['zones'].tolist():raise ValueError('RC model and forecast zone orders differ')
        if self.model.B.shape[1]!=4*self.model.n+5:raise ValueError('Unexpected exported RC input layout')
        self.meta=json.loads((config.output/'preparation.json').read_text())
        self.observer=DisturbanceObserver(self.model.n,config.observer_gain,config.disturbance_limit_kW)
        self.rows=[];self.zone_rows=[];self.decisions=[];self.failures=[];self.handles=None;self.command=None
        self.previous=None;self.current_key=None;self.zone_begin_time=None;self.last_control_time=None;self.failed=False
        self.heat_integral=np.zeros(self.model.n);self.system_hours=0.;self.future_forcing=None
        self.storage_rows=[]
        sys.path.insert(0,str(config.energyplus_root))
        from pyenergyplus.api import EnergyPlusAPI
        self.api=EnergyPlusAPI();self.state=self.api.state_manager.new_state()
        self.ex=self.api.exchange
        self.api.runtime.set_console_output_status(self.state,False)
        self.zone_vars=['Zone Mean Air Temperature','Zone Air System Sensible Heating Rate','Zone Air System Sensible Cooling Rate',
                        'Zone Thermostat Heating Setpoint Temperature','Zone Thermostat Cooling Setpoint Temperature']
        for name in self.zone_vars:
            for z in self.model.zones:self.ex.request_variable(self.state,name,z)
        for z in self.meta['plenums']:self.ex.request_variable(self.state,'Zone Mean Air Temperature',z)
        for name in ['Facility Total HVAC Electricity Demand Rate','Facility Total Building Electricity Demand Rate',
                     'Facility Total Produced Electricity Rate','Facility Total Purchased Electricity Rate','Facility Total Surplus Electricity Rate']:
            self.ex.request_variable(self.state,name,'Whole Building')
        self.api.runtime.callback_begin_zone_timestep_after_init_heat_balance(self.state,self.guard(self.begin))
        # Thermostat overrides must precede zone load prediction; applying them
        # after HVAC managers delays the effective reference by a timestep.
        self.api.runtime.callback_begin_system_timestep_before_predictor(self.state,self.guard(self.actuate))
        self.api.runtime.callback_end_system_timestep_after_hvac_reporting(self.state,self.guard(self.system_end))
        self.api.runtime.callback_end_zone_timestep_after_zone_reporting(self.state,self.guard(self.end))

    def guard(self,fn):
        def callback(state):
            if self.failed:return
            try:
                if self.ex.warmup_flag(state) or self.ex.kind_of_sim(state)!=3 or not self.ex.api_data_fully_ready(state):return
                if self.handles is None:self.acquire(state)
                fn(state)
            except BaseException:
                self.failed=True;self.failures.append(traceback.format_exc());self.api.runtime.stop_simulation(state)
        return callback

    def acquire(self,state):
        self.handles={}
        for name in self.zone_vars:self.handles[name]=[self.ex.get_variable_handle(state,name,z) for z in self.model.zones]
        self.handles['plenums']=[self.ex.get_variable_handle(state,'Zone Mean Air Temperature',z) for z in self.meta['plenums']]
        self.handles['cool_actuator']=[self.ex.get_actuator_handle(state,'Zone Temperature Control','Cooling Setpoint',z) for z in self.model.zones]
        self.handles['heat_actuator']=[self.ex.get_actuator_handle(state,'Zone Temperature Control','Heating Setpoint',z) for z in self.model.zones]
        self.handles['meters']=[self.ex.get_meter_handle(state,x) for x in ['ElectricityProduced:Facility','ElectricityPurchased:Facility','ElectricitySurplusSold:Facility',
                                                                                 'Cooling:Electricity','Fans:Electricity','Heating:Electricity','NaturalGas:Facility']]
        missing={k:v for k,v in self.handles.items() if any(h<0 for h in v)}
        if missing:raise RuntimeError(f'Missing EnergyPlus API handles: {missing}')
        (self.folder/'actuator_handles.json').write_text(json.dumps(self.handles,indent=2))
    def values(self,state,key):return np.array([self.ex.get_variable_value(state,h) for h in self.handles[key]])

    def begin(self,state):
        # Use the zone clock, not current_time (which can reflect an adaptive HVAC substep).
        midnight=pd.Timestamp(year=2017,month=self.ex.month(state),day=self.ex.day_of_month(state))
        self.zone_begin_time=midnight+pd.Timedelta(minutes=self.ex.hour(state)*60+(self.ex.zone_time_step_number(state)-1)*round(self.c.dt_hours*60))
        self.heat_integral=np.zeros(self.model.n);self.system_hours=0.
        self.current_temperature=self.values(state,'Zone Mean Air Temperature')
        self.current_plenums=self.values(state,'plenums')
        self.future_forcing=self.forecast.forcing(self.zone_begin_time,self.current_temperature,self.current_plenums)
        self.model.observe_begin(self.zone_begin_time,self.current_temperature,self.future_forcing[-5:])
        if self.command is None:self.command=self.forecast.at(self.zone_begin_time)['upper'].copy()
        active=pd.Timestamp(self.c.start)<=self.zone_begin_time<pd.Timestamp(self.c.start)+pd.Timedelta(days=self.c.days)
        self.active=bool(active and self.scenario!='conventional')
        if not self.active:
            self.command=self.forecast.at(self.zone_begin_time)['upper'].copy()
            self.last_control_time=None
            return
        if self.last_control_time is None or (self.zone_begin_time-self.last_control_time).total_seconds()>=self.c.control_hours*3600-1:
            forecast=self.forecast.horizon(self.zone_begin_time,self.current_temperature,self.current_plenums)
            result,diag=solve(self.model,forecast,self.current_temperature,self.command,self.observer.d,
                              self.forecast.data,self.c,'renewable' in self.scenario)
            diag['time']=str(self.zone_begin_time);self.decisions.append(diag);self.last_control_time=self.zone_begin_time
            if len(self.decisions)%48==0:print(f'{self.scenario}: {self.zone_begin_time}, {len(self.decisions)} control updates',flush=True)
            if result is None:
                self.command=forecast['upper'][0].copy();self.planned_cooling=np.zeros(self.model.n)
            else:self.command=result['command'];self.planned_cooling=result['planned_cooling']

    def actuate(self,state):
        if not hasattr(self,'active'):return
        if not self.active:
            for key in ['cool_actuator','heat_actuator']:
                for h in self.handles[key]:self.ex.reset_actuator(state,h)
            return
        lower=self.forecast.at(self.zone_begin_time)['lower']
        for i in range(self.model.n):
            self.ex.set_actuator_value(state,self.handles['cool_actuator'][i],float(self.command[i]))
            self.ex.set_actuator_value(state,self.handles['heat_actuator'][i],float(min(lower[i],self.command[i]-.5)))

    def system_end(self,state):
        if self.zone_begin_time is None:return
        dt=self.ex.system_time_step(state)
        net=(self.values(state,'Zone Air System Sensible Heating Rate')-self.values(state,'Zone Air System Sensible Cooling Rate'))/1000
        self.heat_integral+=net*dt;self.system_hours+=dt

    def end(self,state):
        if self.zone_begin_time is None:return
        t=self.zone_begin_time;T=self.values(state,'Zone Mean Air Temperature');info=self.forecast.at(t)
        if abs(self.system_hours-self.c.dt_hours)>1e-6:raise RuntimeError(f'System integration duration {self.system_hours} differs from zone timestep')
        q=self.heat_integral/self.c.dt_hours
        matrices=self.model.discretize(self.c.dt_hours)
        d_before=self.observer.d.copy()
        if 'no_correction' not in self.scenario and self.scenario!='conventional':
            predicted,innovation=self.observer.update(self.model.state,T,q,self.future_forcing,matrices)
        else:
            A,Bq,Bd=matrices;predicted=(A@self.model.state+Bq@q+Bd@self.future_forcing)[:self.model.n];innovation=T-predicted
        endpoint_time=t+pd.Timedelta(hours=self.c.dt_hours)
        endpoint_forcing=self.forecast.forcing(endpoint_time,T,self.values(state,'plenums'))
        self.model.observe_end(self.current_temperature,T,self.future_forcing[-5:],endpoint_forcing[-5:],self.c.dt_hours)
        self.storage_rows.append(dict(time=str(endpoint_time),**{
            f'storage_{int(e)}_C':float(v) for e,v in zip(self.model.storage_ids,self.model.state[self.model.n:])}))
        metered=np.array([self.ex.get_meter_value(state,h) for h in self.handles['meters']])/3.6e6
        # This installed API does not resolve Electricity:Facility although SQL reports it.
        # Derive demand from production/purchases/exports and independently verify against SQL.
        energy=np.r_[metered[0]+metered[1]-metered[2],metered]
        phase='control' if pd.Timestamp(self.c.start)<=t<pd.Timestamp(self.c.start)+pd.Timedelta(days=self.c.days) else 'conditioning' if t<pd.Timestamp(self.c.start) else 'recovery'
        self.rows.append(dict(time=str(t),phase=phase,demand_kWh=energy[0],pv_kWh=energy[1],import_kWh=energy[2],export_kWh=energy[3],
                    cooling_kWh=energy[4],fan_kWh=energy[5],heating_electric_kWh=energy[6],gas_kWh=energy[7],hvac_kWh=float(energy[4:7].sum())))
        for i,z in enumerate(self.model.zones):
            self.zone_rows.append(dict(time=str(t),phase=phase,zone=z,temperature_C=T[i],lower_C=info['lower'][i],upper_C=info['upper'][i],
                occupied=bool(info['occupancy'][i]>.01),cooling_command_C=self.command[i],actual_cooling_setpoint_C=self.values(state,'Zone Thermostat Cooling Setpoint Temperature')[i],
                delivered_heat_kW=q[i],planned_cooling_kW=float(getattr(self,'planned_cooling',np.zeros(self.model.n))[i]),
                predicted_temperature_C=predicted[i],innovation_C=innovation[i],disturbance_kW=self.observer.d[i],prior_disturbance_kW=d_before[i]))

    def run(self):
        import faulthandler,os
        trace=(self.folder/'runtime_trace.log').open('w')
        # Repeated asynchronous traceback dumps can interrupt native callbacks
        # in the bundled Windows runtime. Enable this diagnostic only explicitly.
        debug_trace=os.environ.get('MPC_DEBUG_TRACE','0')=='1'
        if debug_trace:faulthandler.dump_traceback_later(60,repeat=True,file=trace)
        else:trace.write('Timed diagnostic traceback disabled. Set MPC_DEBUG_TRACE=1 to enable.\n');trace.flush()
        idf=make_idf(self.c,self.folder);weather=next(self.c.source.glob('*.epw'))
        code=self.api.runtime.run_energyplus(self.state,['-w',str(weather),'-d',str(self.folder/'energyplus'),str(idf)])
        if debug_trace:faulthandler.cancel_dump_traceback_later()
        trace.close()
        self.api.state_manager.delete_state(self.state)
        pd.DataFrame(self.rows).to_csv(self.folder/'energy.csv',index=False)
        pd.DataFrame(self.zone_rows).to_csv(self.folder/'zones.csv',index=False)
        pd.DataFrame(self.decisions).to_csv(self.folder/'decisions.csv',index=False)
        pd.DataFrame(self.storage_rows).to_csv(self.folder/'storage_states.csv',index=False)
        (self.folder/'state_initialisation.json').write_text(json.dumps(self.model.initialisation,indent=2))
        (self.folder/'callback_errors.txt').write_text('\n'.join(self.failures))
        if code or self.failed:raise RuntimeError(f'{self.scenario} failed; inspect {self.folder}')
        expected=(self.c.days+self.c.preconditioning_days+self.c.recovery_days)*round(24/self.c.dt_hours)
        if len(self.rows)!=expected:raise RuntimeError(f'{self.scenario}: {len(self.rows)} rows, expected {expected}')
        return self.folder
