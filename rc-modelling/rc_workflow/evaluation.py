import numpy as np
import pandas as pd
from .model import inputs,rollout

def evaluate(data,layout,theta,blocks,horizons,stride_hours=24):
    model=layout.matrices(theta,data.dt);all_u=inputs(data)
    rows=[];episodes=[]
    for horizon in horizons:
        steps=round(horizon/data.dt);stride=round(stride_hours/data.dt)
        errors=[];persist=[]
        for block in blocks:
            for local in range(0,len(block)-steps,stride):
                idx=block[local:local+steps+1]
                # Temperatures and interval-average forcing are collocated on interval centres.
                # Use adjacent forcing average as piecewise constant centre-to-centre input.
                u=(all_u[idx[:-1]]+all_u[idx[1:]])/2
                pred=rollout(model['Ad'],model['Bd'],u,data.T[idx[0]])
                error=pred[1:]-data.T[idx[1:]];errors.append(error)
                persist.append(data.T[idx[0]]-data.T[idx[1:]])
                episodes.append(dict(horizon_hours=horizon,start=str(data.time[idx[0]]),rmse_C=float(np.sqrt(np.mean(error**2)))))
        if not errors:raise ValueError(f'No {horizon}-hour episodes within split')
        error=np.vstack(errors);p=np.vstack(persist)
        rows.append(dict(horizon_hours=horizon,zone='ALL',rmse_C=float(np.sqrt(np.mean(error**2))),mae_C=float(np.abs(error).mean()),
                         bias_C=float(error.mean()),persistence_rmse_C=float(np.sqrt(np.mean(p*p))),episodes=len(errors)))
        for i,z in enumerate(data.zones):rows.append(dict(horizon_hours=horizon,zone=z,rmse_C=float(np.sqrt(np.mean(error[:,i]**2))),
                 mae_C=float(np.abs(error[:,i]).mean()),bias_C=float(error[:,i].mean()),persistence_rmse_C=float(np.sqrt(np.mean(p[:,i]**2))),episodes=len(errors)))
    return pd.DataFrame(rows),pd.DataFrame(episodes)

def select(path,tolerance_C):
    """Smallest support within a declared Celsius margin of minimum validation RMSE."""
    good=path[path.validation_rmse_C<=path.validation_rmse_C.min()+tolerance_C]
    return good.sort_values(['edges','validation_rmse_C','lambda']).iloc[0]
