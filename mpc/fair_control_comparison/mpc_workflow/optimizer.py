"""Sparse linear MPC with exact RC dynamics and soft comfort constraints.

The optimiser plans delivered cooling and temperature references. EnergyPlus's
local thermostats track those references; achieved heat is measured, never assumed.
"""
import time
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix

def solve(model,forecast,current,last_command,disturbance,profiles,config,renewable):
    started=time.perf_counter();n=model.n;h=len(forecast['pv']);N=h*n
    # Blocks: predicted temperatures, cooling heat, low/high comfort slack, command variation, grid import.
    x0=0;q0=N;lo0=2*N;hi0=3*N;move0=4*N;grid0=5*N;size=grid0+h
    A,Bq,Bd=model.discretize(config.control_hours)
    eq=lil_matrix((N,size));rhs=np.empty(N)
    ub=lil_matrix((4*N+h*4,size));bound=[];row=0
    costs=np.zeros(size);bounds=[(None,None)]*N
    cap=profiles['capacity'];groups=profiles['groups'];gc=profiles['group_capacity']
    power=profiles['power_coefficient'][groups]
    bounds+=list(zip(np.zeros(N),np.tile(cap,h)))
    bounds += [(0,None)]*(3*N+h)
    costs[q0:q0+N]=np.tile(power,h)*config.control_hours*(config.renewable_hvac_weight if renewable else 1.)
    costs[lo0:hi0+N]=config.comfort_weight*config.control_hours
    costs[move0:move0+N]=config.movement_weight
    if renewable:costs[grid0:]=config.control_hours
    for k in range(h):
        rows=slice(k*n,(k+1)*n);xx=slice(x0+k*n,x0+(k+1)*n);qq=slice(q0+k*n,q0+(k+1)*n)
        eq[rows,xx]=np.eye(n);eq[rows,qq]=Bq
        rhs[rows]=Bd@forecast['forcing'][k]+Bq@disturbance
        if k==0:rhs[rows]+=A@current
        else:eq[rows,slice(x0+(k-1)*n,x0+k*n)]=-A
        for i in range(n):
            j=k*n+i
            ub[row,x0+j]=-1;ub[row,lo0+j]=-1;bound.append(-forecast['lower'][k,i]);row+=1
            ub[row,x0+j]=1;ub[row,hi0+j]=-1;bound.append(forecast['upper'][k,i]);row+=1
            ub[row,x0+j]=1;ub[row,move0+j]=-1
            if k:ub[row,x0+j-n]=-1;bound.append(0.)
            else:bound.append(last_command[i])
            row+=1
            ub[row,x0+j]=-1;ub[row,move0+j]=-1
            if k:ub[row,x0+j-n]=1;bound.append(0.)
            else:bound.append(-last_command[i])
            row+=1
        for group in range(3):
            for i in np.flatnonzero(groups==group):ub[row,q0+k*n+i]=1
            bound.append(gc[group]);row+=1
        ub[row,qq]=power;ub[row,grid0+k]=-1
        # Coefficient[-1] is an on-state electrical overhead; conservative always-on prediction.
        bound.append(forecast['pv'][k]-forecast['base'][k]-profiles['power_coefficient'][-1]);row+=1
    result=linprog(costs,A_ub=ub[:row].tocsr(),b_ub=np.array(bound),A_eq=eq.tocsr(),b_eq=rhs,
                   bounds=bounds,method='highs',options={'time_limit':20.,'dual_feasibility_tolerance':1e-7,'primal_feasibility_tolerance':1e-7})
    diag=dict(success=bool(result.success),status=int(result.status),message=result.message,solve_seconds=time.perf_counter()-started)
    if not result.success:return None,diag
    residual=float(np.max(np.abs(eq@result.x-rhs)));diag.update(objective=float(result.fun),dynamics_residual=residual,
            predicted_comfort_degree_hours=float(result.x[lo0:hi0+N].sum()*config.control_hours))
    if residual>1e-5:raise RuntimeError('MPC dynamics equality residual exceeds tolerance')
    planned=result.x[:N].reshape(h,n);cool=result.x[q0:q0+N].reshape(h,n)
    # Receding target governor. Do not claim cooling q is a direct EnergyPlus actuator.
    # A passive prediction below the comfort ceiling is not a request to cool
    # to that temperature. Release cooling demand when the plan requests none.
    target=np.where(cool[0]>1e-6,planned[0],forecast['upper'][0])
    command=np.clip(target,forecast['lower'][0]+.5,forecast['upper'][0])
    command=np.clip(command,last_command-config.max_setpoint_change_C,last_command+config.max_setpoint_change_C)
    # Scheduled comfort changes and the heating/cooling deadband take priority
    # over the normal target ramp limit.
    command=np.clip(command,forecast['lower'][0]+.5,forecast['upper'][0])
    return dict(command=command,planned_cooling=cool[0],planned_temperature=planned[0],trajectory=planned),diag
