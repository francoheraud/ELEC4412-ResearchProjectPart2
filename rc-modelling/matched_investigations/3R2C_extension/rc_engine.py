"""Matched, reciprocal RC identification; units: h, kW, kWh/K, kW/K.

Symmetric 2R1C: each half conductance is 2G and storage C=4G*tau.
Measured boundary temperatures are inputs, never dynamic plenum states.
"""
import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
from dataclasses import dataclass, asdict
from itertools import combinations
import hashlib
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.linalg import expm, qr
from scipy.optimize import lsq_linear
from scipy.signal import lfilter, savgol_filter

TOL = 1e-6
WARM_HOURS = 72
LAMBDAS = np.r_[0., np.logspace(-6, 2, 17)]
METHODS = ['trapezoidal', 'savgol']
TAUS = [.25, 1., 4., 12.]
DEFAULT_IMPLEMENTATION = Path('C:/Users/Franc/OneDrive/Desktop/Uni Documents/2026/Thesis/building_semantic/ornl_frp/implementation')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def floor(name):
    for k, tag in enumerate(['BOT', 'MID', 'TOP']):
        if tag in name:
            return k
    raise ValueError(name)

@dataclass(frozen=True)
class Branch:
    i: int
    j: int  # dynamic zone index for interzone, boundary index otherwise
    kind: str
    tau: float = 0.
    storage_nodes: int = 1
    @property
    def interzone(self):
        return self.kind == 'interzone'

def branches(zones, mask='local', order='2R1C', inter_tau=12.):
    n = len(zones)
    if order not in ['1R', '2R1C', '3R2C']: raise ValueError(order)
    nodes = 2 if order == '3R2C' else 1
    result = [Branch(i, j, 'interzone', inter_tau if order != '1R' else 0., nodes)
              for i, j in combinations(range(n), 2)
              if mask == 'unrestricted' or floor(zones[i]) == floor(zones[j])]
    for i, zone in enumerate(zones):
        # In 1R, the two parallel outdoor paths collapse to ONE total conductance:
        # otherwise their identical regressors cannot be identified separately.
        result.append(Branch(i, 0, 'outdoor_direct'))
        if order != '1R':
            result.append(Branch(i, 0, 'outdoor_storage', 12., nodes))
        for b in range(1, 4):
            if mask == 'local' and b not in [floor(zone)+1] + ([floor(zone)] if floor(zone)>0 else []):
                continue
            lower = b-1 < floor(zone)
            result.append(Branch(i, b, 'plenum_lower' if lower else 'plenum_upper_or_remote',
                                 12. if lower and order != '1R' else 0., nodes))
        result.append(Branch(i, 4, 'ground'))
    return result

def load_inputs(implementation, here):
    p = Path(implementation)/'rc-modelling/results/prepared_data.npz'
    with np.load(p) as f:
        data = {k:f[k] for k in f.files}
    data['times'] = pd.DatetimeIndex(data['time'])
    data['C_air'] = pd.read_csv(here/'inputs/air_priors.csv').set_index('ZoneName').loc[data['zones'], 'C_air_kWh_K'].to_numpy()
    data['wall_prior'] = json.loads((here/'inputs/wall_prior.json').read_text())
    data['source_sha256'] = sha(p)
    dt = float(data['dt_hours'])
    assert abs(dt-1/6) < 1e-10, 'This protocol specifies ten-minute samples and a seven-point SG window.'
    assert data['T'].shape[1] == 15
    for key in ['T','boundaries','hvac_kW','known_gain_kW','radiant_filtered_kW','solar_filtered_kW']:
        if not np.isfinite(data[key]).all():
            raise ValueError('Nonfinite inputs: '+key)
    data['u'] = np.column_stack([data[k] for k in ['hvac_kW','known_gain_kW','radiant_filtered_kW','solar_filtered_kW','boundaries']])
    return data

def split_blocks(data):
    times = data['times']; dt = float(data['dt_hours'])
    result = {}
    for name, months, lo, hi in [('train',[1,4,7,10],1,14),('validation',[1,4,7,10],15,21),('test',[2,5,8,11],15,21)]:
        ids = np.flatnonzero(np.isin(times.month, months)&(times.day>=lo)&(times.day<=hi))
        cuts = (np.diff(ids)!=1) | (np.diff(times[ids].asi8)!=round(dt*3.6e12))
        result[name] = [b for b in np.split(ids,np.flatnonzero(cuts)+1) if len(b)>round(WARM_HOURS/dt)+10]
    assert not set(np.concatenate(result['train'])) & set(np.concatenate(result['validation']))
    assert not set(np.concatenate(result['test'])) & set(np.concatenate(result['train']))
    return result

def storage_traces(data, block, bs):
    T = data['T'][block]; boundary = data['boundaries'][block]; dt=float(data['dt_hours'])
    if any(b.tau and b.storage_nodes == 2 for b in bs):
        # Equal R/3 sections and Ctotal/2 masses. Preserve Rtotal=1/G
        # and Ctotal=4*G*tau from 2R1C. Here tau is a reference scale,
        # NOT either modal time constant of the two-state branch.
        # Symmetric/antisymmetric modes have time constants 2*tau/3,
        # 2*tau/9 and equilibrium targets (Ti+Tj)/2, (Ti-Tj)/6.
        extra = {e:len(bs)+k for k,e in enumerate(e for e,b in enumerate(bs) if b.tau and b.storage_nodes==2)}
        traces = np.zeros((len(block), len(bs)+len(extra)))
        def foh(signal, timescale):
            decay=np.exp(-dt/timescale)
            b1=1-(1-decay)*timescale/dt; b0=1-decay-b1
            return lfilter([b1,b0],[1,-decay],signal,axis=0,zi=((1-b1)*signal[0])[None,:])[0]
        for tau in sorted({b.tau for b in bs if b.tau>0}):
            for nodes in [1,2]:
                cols=[e for e,b in enumerate(bs) if b.tau==tau and b.storage_nodes==nodes]
                if not cols: continue
                left=np.column_stack([T[:,bs[e].i] for e in cols])
                right=np.column_stack([T[:,bs[e].j] if bs[e].interzone else boundary[:,bs[e].j] for e in cols])
                if nodes==1: traces[:,cols]=foh((left+right)/2,tau)
                else:
                    mean=foh((left+right)/2,2*tau/3)
                    difference=foh((left-right)/6,2*tau/9)
                    traces[:,cols]=mean+difference
                    traces[:,[extra[e] for e in cols]]=mean-difference
        return traces
    traces = np.zeros((len(block), len(bs)))
    for tau in sorted({b.tau for b in bs if b.tau>0}):
        columns = [k for k,b in enumerate(bs) if b.tau==tau]
        mid = np.column_stack([(T[:,bs[k].i]+(T[:,bs[k].j] if bs[k].interzone else boundary[:,bs[k].j]))/2 for k in columns])
        decay=np.exp(-dt/tau); b1=1-(1-decay)*tau/dt; b0=1-decay-b1
        traces[:,columns]=lfilter([b1,b0],[1,-decay],mid,axis=0,zi=((1-b1)*mid[0])[None,:])[0]
    return traces

def extra_trace_columns(bs):
    return {e:len(bs)+k for k,e in enumerate(e for e,b in enumerate(bs) if b.tau and b.storage_nodes==2)}

def state_trace_columns(bs, kept):
    extra=extra_trace_columns(bs)
    return [col for e in kept for col in ([e,extra[e]] if e in extra else [e])]

def training_arrays(data, block, bs, method, fixed_air):
    n=len(data['zones']); nb=len(bs); dt=float(data['dt_hours'])
    local=np.arange(round(WARM_HOURS/dt),len(block)-4); ids=block[local]
    z=storage_traces(data,block,bs)
    def sample(arr):
        return arr[ids] if method=='savgol' else (arr[ids]+arr[ids+1])/2
    T=sample(data['T']); bounds=sample(data['boundaries']); heat=sample(data['hvac_kW']+data['known_gain_kW'])
    derivative=(savgol_filter(data['T'][block],7,2,deriv=1,delta=dt,axis=0)[local] if method=='savgol'
                else (data['T'][ids+1]-data['T'][ids])/dt)
    wall=z[local] if method=='savgol' else (z[local]+z[local+1])/2
    X=np.zeros((len(ids),n,nb+2+(0 if fixed_air else n)))
    extra=extra_trace_columns(bs)
    for e,b in enumerate(bs):
        other=T[:,b.j] if b.interzone else bounds[:,b.j]
        multiplier=b.storage_nodes+1
        X[:,b.i,e]=multiplier*(T[:,b.i]-wall[:,e]) if b.tau else T[:,b.i]-other
        if b.interzone:
            X[:,b.j,e]=multiplier*(T[:,b.j]-wall[:,extra.get(e,e)]) if b.tau else other-T[:,b.i]
    X[:,:,nb]=-sample(data['radiant_filtered_kW']); X[:,:,nb+1]=-sample(data['solar_filtered_kW'])
    if fixed_air:
        target=heat-derivative*data['C_air']
    else:
        for i in range(n): X[:,i,nb+2+i]=derivative[:,i]
        target=heat
    return X.reshape(-1,X.shape[-1]),target.ravel(),ids

def regression(data, blocks, bs, method, fixed_air):
    # Incremental QR avoids retaining all seasonal regressors in memory.
    compressed=None; count=0; sumsq=None; ids_all=[]
    for block in blocks:
        X,y,ids=training_arrays(data,block,bs,method,fixed_air)
        ids_all.extend(ids); count+=len(y)
        sumsq=np.sum(X*X,axis=0) if sumsq is None else sumsq+np.sum(X*X,axis=0)
        aug=np.column_stack([X,y]); _,r=qr(aug,mode='economic',check_finite=False)
        compressed=r if compressed is None else qr(np.vstack([compressed,r]),mode='economic',check_finite=False)[1]
    p=len(sumsq); scale=np.maximum(np.sqrt(sumsq/count),1e-12)
    R=compressed[:p,:p]/scale/np.sqrt(count); y=compressed[:p,p]/np.sqrt(count)
    const=float(np.sum(compressed[p:,p]**2)/count)
    return dict(R=R,y=y,scale=scale,constant=const,rank=int(np.linalg.matrix_rank(R)),
                rows=count,indices_sha256=hashlib.sha256(np.asarray(ids_all,dtype=np.int64).tobytes()).hexdigest())

def bounds(data, bs, fixed_air, wall_prior):
    nb=len(bs); n=len(data['zones']); lower=np.zeros(nb+2+(0 if fixed_air else n)); upper=np.full(len(lower),100.)
    upper[nb:nb+2]=2.
    if not fixed_air: lower[nb+2:]=.01; upper[nb+2:]=1000.
    m=sum(b.interzone for b in bs)
    if wall_prior:
        g=data['wall_prior']['reference_G_kW_K']; lower[:m]=.5*g; upper[:m]=2*g
    return lower,upper,m

def fit_refit(stats, lo, hi, m, support, lam=0.):
    p=len(lo); cols=np.r_[list(support),np.arange(m,p)].astype(int)
    R=stats['R'][:,cols]; scale=stats['scale'][cols]; y=stats['y'].copy()
    if lam:
        penalty=(cols<m)/scale
        shift=np.linalg.lstsq(R.T,.5*lam*penalty,rcond=1e-12)[0]
        if not np.allclose(R.T@shift,.5*lam*penalty,rtol=1e-6,atol=1e-8):
            raise ValueError('Penalty shift requires identifiable penalty direction.')
        y-=shift
    sol=lsq_linear(R,y,bounds=(lo[cols]*scale,hi[cols]*scale),method='bvls',tol=1e-10,max_iter=2500)
    if not sol.success: raise RuntimeError(sol.message)
    x=np.zeros(p); x[cols]=sol.x/scale
    return x,float(sol.optimality)

def fit_conditional(stats, lo, hi, m, lam, initial, max_sweeps=12000):
    R=stats['R']; y=stats['y']; scale=stats['scale']; H=R.T@R; b=R.T@y
    low=lo*scale; high=hi*scale; penalty=np.r_[np.full(m,lam),np.zeros(len(lo)-m)]/scale
    z=np.minimum(np.maximum(initial*scale,low),high)
    z[:m]=np.where(initial[:m]>TOL,z[:m],0.)
    residual=H@z-b; diag=H.diagonal(); H=np.asfortranarray(H)
    converged=False
    for sweep in range(max_sweeps):
        largest=0.
        for j in range(len(z)):
            h=diag[j]
            if h<1e-20: continue
            linear=residual[j]-h*z[j]+penalty[j]/2
            proposed=min(max(-linear/h,low[j]),high[j])
            if j<m and h*proposed*proposed+2*linear*proposed>=0: proposed=0.
            change=proposed-z[j]
            if change:
                z[j]=proposed; residual+=H[:,j]*change; largest=max(largest,abs(change))
        if largest<1e-9*(1+max(abs(z))): converged=True; break
    x=z/scale
    return x,float(np.sum((R@z-y)**2)+stats['constant']+lam*x[:m].sum()),sweep+1,converged

def state_matrices(data, bs, x, fixed_air):
    n=len(data['zones']); nb=len(bs); C=data['C_air'] if fixed_air else x[nb+2:]
    kept=[e for e,b in enumerate(bs) if b.tau>0 and x[e]>TOL]
    caps=np.r_[C,[4*x[e]*bs[e].tau/bs[e].storage_nodes for e in kept for _ in range(bs[e].storage_nodes)]]; N=len(caps)
    K=np.zeros((N,N)); B=np.zeros((N,4*n+5)); storage={}; offset=n
    for e in kept:
        storage[e]=list(range(offset,offset+bs[e].storage_nodes)); offset+=bs[e].storage_nodes
    def link(i,j,g):
        K[i,i]+=g; K[j,j]+=g; K[i,j]-=g; K[j,i]-=g
    for e,b in enumerate(bs):
        g=x[e]
        if g<=TOL: continue
        if b.tau:
            chain=[b.i]+storage[e]; leg_g=(b.storage_nodes+1)*g
            for left,right in zip(chain[:-1],chain[1:]): link(left,right,leg_g)
            w=chain[-1]
            if b.interzone: link(b.j,w,leg_g)
            else: K[w,w]+=leg_g; B[w,4*n+b.j]+=leg_g
        elif b.interzone: link(b.i,b.j,g)
        else: K[b.i,b.i]+=g; B[b.i,4*n+b.j]+=g
    for i in range(n):
        B[i,i]=1.; B[i,n+i]=1.; B[i,2*n+i]=x[nb]; B[i,3*n+i]=x[nb+1]
    A=-K/caps[:,None]; B=B/caps[:,None]
    aug=np.zeros((N+B.shape[1],N+B.shape[1])); aug[:N,:N]=A; aug[:N,N:]=B
    discrete=expm(aug*float(data['dt_hours']))
    return A,B,discrete[:N,:N],discrete[:N,N:],caps,kept

def verify_model(data, bs, x, fixed_air, lo, hi):
    A,B,Ad,Bd,C,kept=state_matrices(data,bs,x,fixed_air)
    assert np.all(C>0) and np.isfinite(Ad).all()
    np.testing.assert_allclose(-C[:,None]*A,(-C[:,None]*A).T,atol=1e-8)
    assert np.min(A-np.diag(np.diag(A)))>=-1e-10
    maxeig=float(np.max(np.linalg.eigvals(A).real)); assert maxeig<1e-8
    n=len(data['zones']); eq=A@np.full(len(C),20.)+B@np.r_[np.zeros(4*n),np.full(5,20.)]
    assert np.max(abs(eq))<1e-8
    assert np.all(x<=hi+1e-7)
    for j in range(len(x)):
        assert x[j]>=lo[j]-1e-7 or (j<len(bs) and bs[j].interzone and x[j]<=TOL)
    return dict(max_real_eigenvalue=maxeig,equilibrium_residual=float(np.max(abs(eq))),reciprocity_passed=True,bounds_passed=True)

def evaluate(data, blocks, bs, x, fixed_air, horizons=(24,), predictions=False):
    A,B,Ad,Bd,C,kept=state_matrices(data,bs,x,fixed_air)
    n=len(data['zones']); dt=float(data['dt_hours']); warm=round(WARM_HOURS/dt)
    metrics=[]; episodes=[]; traces_out=[]
    for h in horizons:
        errors=[]; steps=round(h/dt)
        for block in blocks:
            wall=storage_traces(data,block,bs)
            for start in range(warm,len(block)-steps,round(24/dt)):
                ids=block[start:start+steps+1]; state=np.r_[data['T'][ids[0]],wall[start,state_trace_columns(bs,kept)]]
                pred=np.empty((steps+1,n)); pred[0]=state[:n]
                for k in range(steps):
                    state=Ad@state+Bd@((data['u'][ids[k]]+data['u'][ids[k+1]])/2)
                    pred[k+1]=state[:n]
                err=pred[1:]-data['T'][ids[1:]]
                if not np.isfinite(err).all(): raise ValueError('Nonfinite rollout')
                errors.append(err)
                episodes.append(dict(horizon_hours=h,start=str(data['times'][ids[0]]),rmse_C=float(np.sqrt(np.mean(err**2)))))
                if predictions and h==24: traces_out.append((ids,pred))
        allerr=np.vstack(errors)
        for i,name in [(-1,'ALL')]+list(enumerate(data['zones'])):
            e=allerr if i<0 else allerr[:,i]
            metrics.append(dict(horizon_hours=h,zone=name,rmse_C=float(np.sqrt(np.mean(e*e))),mae_C=float(np.mean(abs(e))),bias_C=float(np.mean(e)),episodes=len(errors)))
    return metrics,episodes,traces_out

def complexity(data, bs, x, fixed_air):
    nb=len(bs); active=int(np.sum(x[:nb]>TOL))
    return dict(states=len(data['zones'])+sum(b.storage_nodes for e,b in enumerate(bs) if b.tau>0 and x[e]>TOL),
                interzone_edges=sum(b.interzone and x[e]>TOL for e,b in enumerate(bs)),
                active_conductances=active,
                independent_fitted_parameters=active+2+(0 if fixed_air else len(data['zones'])))

def case_definitions(data):
    walltau=data['wall_prior']['interzone_tau_hours']
    return {
        'unrestricted_2R1C_wall':dict(mask='unrestricted',order='2R1C',fixed_air=True,wall_prior=True,taus=[walltau]),
        'local_2R1C_wall':dict(mask='local',order='2R1C',fixed_air=True,wall_prior=True,taus=[walltau]),
        'local_3R2C_wall':dict(mask='local',order='3R2C',fixed_air=True,wall_prior=True,taus=[walltau]),
        'local_1R_wall':dict(mask='local',order='1R',fixed_air=True,wall_prior=True,taus=[0.]),
        'local_2R1C_free_air':dict(mask='local',order='2R1C',fixed_air=False,wall_prior=False,taus=TAUS),
        'local_2R1C_air_only':dict(mask='local',order='2R1C',fixed_air=True,wall_prior=False,taus=TAUS),
    }

GROUPS = {
    '01_candidate_connectivity':['unrestricted_2R1C_wall','local_2R1C_wall'],
    '02_branch_complexity':['local_1R_wall','local_2R1C_wall'],
    '03_physical_information':['local_2R1C_free_air','local_2R1C_air_only','local_2R1C_wall'],
}
