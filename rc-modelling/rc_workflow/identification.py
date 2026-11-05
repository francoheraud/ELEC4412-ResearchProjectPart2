"""Derivative/integral balance regression and nonnegative L1 graph discovery.

Reimplements the E.3 QR-reduced bounded least-squares formulation for arbitrary n.
No construction-derived capacitance or conductance priors are used.
"""
import time
import numpy as np
from scipy.linalg import qr, solve_triangular
from scipy.optimize import lsq_linear, minimize
from scipy.signal import savgol_filter

def equations(data,blocks,layout,method,config):
    aa=[];yy=[];half=config.sg_window//2
    for block in blocks:
        if not np.all(np.diff(block)==1):raise ValueError('Differentiation cannot cross gaps')
        if len(block)<config.sg_window+2:raise ValueError('Short fitting block')
        local=np.arange(half,len(block)-half);idx=block[local]
        if method=='savgol':
            derivative=savgol_filter(data.T[block],config.sg_window,config.sg_order,deriv=1,delta=data.dt,axis=0)[local]
            T=data.T[idx];boundary=data.boundaries[idx];rad=data.radiant[idx];solar=data.solar[idx];y=data.base_heat[idx]
        elif method=='trapezoidal':
            derivative=(data.T[idx+1]-data.T[idx])/data.dt
            T=(data.T[idx+1]+data.T[idx])/2
            boundary=(data.boundaries[idx+1]+data.boundaries[idx])/2
            rad=(data.radiant[idx+1]+data.radiant[idx])/2;solar=(data.solar[idx+1]+data.solar[idx])/2
            y=(data.base_heat[idx+1]+data.base_heat[idx])/2
        else:raise ValueError(method)
        a=np.zeros((len(idx),layout.n,layout.p))
        for i in range(layout.n):
            a[:,i,i]=derivative[:,i]
            for b in range(layout.b):a[:,i,layout.bs.start+i*layout.b+b]=T[:,i]-boundary[:,b]
        for e,(i,j) in enumerate(layout.edges):
            delta=T[:,i]-T[:,j];a[:,i,layout.gs.start+e]=delta;a[:,j,layout.gs.start+e]=-delta
        a[:,:,layout.beta.start]=-rad;a[:,:,layout.beta.start+1]=-solar
        aa.append(a.reshape(-1,layout.p));yy.append(y.ravel())
    a=np.vstack(aa);y=np.concatenate(yy)
    if not np.isfinite(a).all() or not np.isfinite(y).all():raise ValueError('Invalid regression inputs')
    return a,y

class Regression:
    def __init__(self,a,y,layout,support=None):
        t=time.perf_counter();self.layout=layout
        support=range(layout.m) if support is None else support
        self.cols=np.array(list(range(layout.n))+[layout.gs.start+e for e in support]+list(range(layout.bs.start,layout.p)))
        x=a[:,self.cols];self.scale=np.sqrt(np.mean(x*x,axis=0))
        if np.any(self.scale<1e-12):raise ValueError('Unexcited parameter column; revise model or excitation explicitly')
        design=x/self.scale/np.sqrt(len(y))
        q,self.R=qr(design,mode='economic',check_finite=False);self.target=q.T@(y/np.sqrt(len(y)))
        self.y2=float(y@y/len(y));self.rank=int(np.linalg.matrix_rank(self.R));self.condition=float(np.linalg.cond(self.R))
        if self.rank!=len(self.cols):raise ValueError(f'Rank deficient regression {self.rank}/{len(self.cols)}; no silent ridge added')
        self.lo=layout.lower[self.cols]*self.scale;self.hi=layout.upper[self.cols]*self.scale
        self.penalty=((self.cols>=layout.gs.start)&(self.cols<layout.gs.stop))/self.scale
        self.setup_s=time.perf_counter()-t;self.rows=len(y)

    def fit(self,lam=0):
        if lam<0 or not np.isfinite(lam):raise ValueError('Invalid lambda')
        t=time.perf_counter()
        # Objective = mean(balance_residual_kW**2) + lambda*sum(interzone_G_kW_per_K).
        target=self.target-solve_triangular(self.R.T,.5*lam*self.penalty,lower=True)
        result=lsq_linear(self.R,target,bounds=(self.lo,self.hi),method='bvls',tol=1e-11,max_iter=3000)
        z=result.x
        def objective(z):
            residual=self.R@z-self.target
            return float(residual@residual+lam*self.penalty@z), 2*self.R.T@residual+lam*self.penalty
        grad=objective(z)[1]
        pg=float(np.max(np.abs(z-np.clip(z-grad,self.lo,self.hi))))
        polished=False
        if pg>1e-6:
            # At high lambda the shifted least-squares target has a huge constant.
            # Polish the ORIGINAL quadratic to avoid premature relative-cost stopping.
            polish=minimize(objective,z,jac=True,method='L-BFGS-B',bounds=list(zip(self.lo,self.hi)),
                            options={'ftol':1e-15,'gtol':1e-10,'maxiter':20000,'maxls':50})
            z=polish.x;grad=objective(z)[1];pg=float(np.max(np.abs(z-np.clip(z-grad,self.lo,self.hi))));polished=True
        theta=np.zeros(self.layout.p);theta[self.cols]=z/self.scale
        if not result.success or not np.isfinite(theta).all() or pg>1e-4:raise RuntimeError(f'QP failure: {result.message}; projected gradient={pg}')
        residual2=max(0.,float(np.sum((self.R@z-self.target)**2)+self.y2-self.target@self.target))
        return theta,dict(equation_rmse_kW=float(np.sqrt(residual2)),objective=residual2+lam*float(theta[self.layout.gs].sum()),
                          success=True,iterations=int(result.nit),polished_original_quadratic=polished,projected_gradient=pg,scaled_condition=self.condition,rank=self.rank,
                          rows=self.rows,setup_seconds=self.setup_s,solve_seconds=time.perf_counter()-t)
