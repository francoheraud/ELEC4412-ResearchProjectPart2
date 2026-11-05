from pathlib import Path
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def make_figures(out):
    out=Path(out);figdir=out/'figures';figdir.mkdir(exist_ok=True)
    path=pd.read_csv(out/'lambda_path.csv');edges=pd.read_csv(out/'edge_path.csv')
    fig,axs=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for method,df in path.groupby('method',sort=False):
        axs[0].plot(df['lambda'],df.edges,'o-',label=method)
        axs[1].scatter(df.edges,df.validation_rmse_C,label=method)
    axs[0].set_xscale('symlog',linthresh=1e-6)
    axs[0].set(xlabel='Lambda (kW K)',ylabel='Retained candidate interzone edges',title='Complete lambda sweep')
    axs[1].set(xlabel='Retained candidate interzone edges',ylabel='Validation 24h rollout RMSE (C)',title='Accuracy versus sparsity after refitting')
    for ax in axs:ax.grid(alpha=.2);ax.legend()
    fig.savefig(figdir/'lambda_sweep.png',dpi=160);plt.close(fig)
    for method,df in edges.groupby('method'):
        df=df.copy();df['edge']=df.zone_i+' / '+df.zone_j
        pivot=df.pivot(index='edge',columns='lambda',values='retained').astype(float)
        fig,ax=plt.subplots(figsize=(10,7),layout='constrained')
        ax.imshow(pivot.to_numpy(),aspect='auto',interpolation='nearest',cmap='Blues',vmin=0,vmax=1)
        ax.set(xticks=np.arange(len(pivot.columns)),xticklabels=[f'{v:g}' for v in pivot.columns],xlabel='Lambda',ylabel='Candidate edge (see edge_path.csv for names)',title=f'{method}: retained edges across lambda')
        ax.tick_params(axis='x',rotation=60);fig.savefig(figdir/f'{method}_edge_retention.png',dpi=150);plt.close(fig)
        sample=np.load(out/f'{method}_example.npz');fig,axs=plt.subplots(3,1,figsize=(11,7),layout='constrained',sharex=True)
        for i,ax in enumerate(axs):
            ax.plot(pd.to_datetime(sample['time']),sample['actual'][:,i],label='EnergyPlus')
            ax.plot(pd.to_datetime(sample['time']),sample['predicted'][:,i],label='RC rollout');ax.set(ylabel='Temperature (C)',title=str(sample['zones'][i]));ax.legend();ax.grid(alpha=.2)
        fig.suptitle(f'{method}: held-out August 72h example, known future thermal inputs')
        fig.savefig(figdir/f'{method}_rollout.png',dpi=150);plt.close(fig)

def write_summary(out):
    out=Path(out);selection=json.loads((out/'selection.json').read_text());metrics=pd.read_csv(out/'test_metrics.csv')
    rows=metrics[(metrics.zone=='ALL')&(metrics.horizon_hours==24)]
    text='# RC workflow results\n\n'
    text+='Validation-based selections:\n\n'+json.dumps(selection,indent=2)+'\n\n'
    text+='Held-out test 24h rollout metrics (all zones):\n\n'+rows.to_string(index=False)+'\n\n'
    text+='These are effective, positive-capacitance, reciprocal-conductance models. Low temperature error does not establish material-property recovery, physical adjacency, or closed-loop MPC performance. The full edge and lambda paths are primary outputs.\n\n'
    text+='Validation uses measured future HVAC heat, outdoor-air heat transfer, gains and plenum temperatures. This is an offline known-input test, not a forecast that could be deployed unchanged. An HVAC response/power model and disturbance/boundary forecasts are still required for MPC.\n\n'
    text+='Ground temperature comes from the supplied IDF monthly boundary schedule. Manual adjacency comes only from direct office-to-office EnergyPlus surface links; plenum-mediated floor paths are not collapsed into manual interzone edges. All models retain the same candidate boundary connections.\n'
    (out/'SUMMARY.md').write_text(text)
