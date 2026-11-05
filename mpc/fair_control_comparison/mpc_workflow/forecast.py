import numpy as np
import pandas as pd

class Forecast:
    def __init__(self,path,config):
        # NPZ indexing decompresses a complete annual array each time. Materialise
        # once so horizon construction only slices in-memory arrays in callbacks.
        with np.load(path) as archive:self.data={key:archive[key] for key in archive.files}
        self.time=pd.DatetimeIndex(pd.to_datetime(self.data['time']));self.config=config
        self.positions={t.strftime('%m-%d %H:%M'):i for i,t in enumerate(self.time)}
    def index(self,t):return self.positions[pd.Timestamp(t).strftime('%m-%d %H:%M')]
    def at(self,t):
        k=self.index(t);d=self.data
        return dict(lower=d['setpoints'][k,:,0],upper=d['setpoints'][k,:,1],occupancy=d['occupancy'][k],
                    pv=d['pv_kW'][k],non_hvac=d['non_hvac_kW'][k])
    def forcing(self,t,T,plenums):
        d=self.data;k=self.index(t)
        outside=d['oa_coefficient']*(d['outdoor'][k]-T)
        return np.r_[d['convective'][k]+outside,d['radiant'][k],d['solar'][k],d['outdoor'][k],plenums,d['ground'][k]]
    def horizon(self,t,T,plenums):
        c=self.config;h=round(c.horizon_hours/c.control_hours);ratio=round(c.control_hours/c.dt_hours)
        times=[pd.Timestamp(t)+pd.Timedelta(hours=j*c.control_hours) for j in range(h)]
        forces=[];lo=[];hi=[];pv=[];base=[];occupied=[]
        for tm in times:
            fine=[tm+pd.Timedelta(hours=l*c.dt_hours) for l in range(ratio)]
            forces.append(np.mean([self.forcing(v,T,plenums) for v in fine],axis=0))
            info=[self.at(v) for v in fine]
            lo.append(np.max([v['lower'] for v in info],axis=0));hi.append(np.min([v['upper'] for v in info],axis=0))
            occupied.append(np.max([v['occupancy'] for v in info],axis=0)>.01)
            pv.append(np.mean([v['pv'] for v in info]));base.append(np.mean([v['non_hvac'] for v in info]))
        return dict(forcing=np.array(forces),lower=np.array(lo),upper=np.array(hi),pv=np.array(pv),base=np.array(base),occupied=np.array(occupied))
