"""Reciprocal conductance graph and exact zero-order-hold state-space export."""
from itertools import combinations
import numpy as np
from scipy.linalg import expm

class Layout:
    def __init__(self,zones,boundaries,config):
        self.zones=list(zones);self.boundaries=list(boundaries)
        self.n=len(zones);self.b=len(boundaries);self.edges=list(combinations(range(self.n),2));self.m=len(self.edges)
        self.cs=slice(0,self.n);self.gs=slice(self.n,self.n+self.m)
        self.bs=slice(self.n+self.m,self.n+self.m+self.n*self.b)
        self.beta=slice(self.bs.stop,self.bs.stop+2);self.p=self.beta.stop
        self.names=([f'C::{z}' for z in zones]+[f'G::{zones[i]}::{zones[j]}' for i,j in self.edges]
                    +[f'Gb::{z}::{b}' for z in zones for b in boundaries]+['beta_radiant','beta_solar'])
        self.units=['kWh/K']*self.n+['kW/K']*(self.m+self.n*self.b)+['dimensionless']*2
        self.lower=np.r_[[config.c_bounds[0]]*self.n,[config.g_bounds[0]]*(self.m+self.n*self.b),[config.beta_bounds[0]]*2]
        self.upper=np.r_[[config.c_bounds[1]]*self.n,[config.g_bounds[1]]*(self.m+self.n*self.b),[config.beta_bounds[1]]*2]
        self.E=np.zeros((self.n,self.m))
        for e,(i,j) in enumerate(self.edges):self.E[i,e]=1;self.E[j,e]=-1

    def matrices(self,theta,dt):
        theta=np.asarray(theta)
        if theta.shape!=(self.p,) or not np.isfinite(theta).all():raise ValueError('Invalid RC vector')
        if np.any(theta<self.lower-1e-9) or np.any(theta>self.upper+1e-7):raise ValueError('RC bounds violated')
        C=theta[self.cs];g=theta[self.gs];gb=theta[self.bs].reshape(self.n,self.b)
        L=(self.E*g)@self.E.T
        Bq=np.diag(1/C);A=-Bq@(L+np.diag(gb.sum(axis=1)));Bb=Bq@gb
        # Inputs: zone sensible HVAC (kW), fixed known gains (kW), filtered radiant and solar
        # gains (kW), then measured boundary temperatures (C).
        B=np.column_stack([Bq,Bq,theta[-2]*Bq,theta[-1]*Bq,Bb])
        aug=np.zeros((self.n+B.shape[1],self.n+B.shape[1]));aug[:self.n,:self.n]=A;aug[:self.n,self.n:]=B
        disc=expm(aug*dt)
        eigen=np.linalg.eigvals(A)
        if eigen.real.max()>1e-8:raise ValueError('Non-passive unstable model')
        return dict(A=A,B=B,Ad=disc[:self.n,:self.n],Bd=disc[:self.n,self.n:],L=L,C=C,G_boundary=gb,
                    eigenvalues=eigen,input_names=([f'HVAC_kW::{z}' for z in self.zones]+[f'known_gain_kW::{z}' for z in self.zones]
                    +[f'radiant_filtered_kW::{z}' for z in self.zones]+[f'solar_filtered_kW::{z}' for z in self.zones]+[f'boundary_C::{b}' for b in self.boundaries]))

def inputs(data):
    return np.column_stack([data.hvac,data.convective+data.outdoor_air,data.radiant,data.solar,data.boundaries])

def rollout(Ad,Bd,u,initial):
    pred=np.empty((len(u)+1,len(initial)));pred[0]=initial
    for k in range(len(u)):pred[k+1]=Ad@pred[k]+Bd@u[k]
    if not np.isfinite(pred).all():raise ValueError('Nonfinite rollout; never silently discard it')
    return pred
