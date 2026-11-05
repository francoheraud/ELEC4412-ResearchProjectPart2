"""Export the three investigations, paper figures, and cached-result notebooks."""
from rc_engine import *
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

HERE=Path(__file__).resolve().parent
LABELS={
    'unrestricted_2R1C_wall':'Unrestricted 2R1C',
    'local_2R1C_wall':'Local 2R1C + air/wall priors',
    'local_3R2C_wall':'Local 3R2C + air/wall priors',
    'local_1R_wall':'Local 1R + air/wall-R priors',
    'local_2R1C_free_air':'Local 2R1C, estimated air C',
    'local_2R1C_air_only':'Local 2R1C + air prior',
}

def savefig(fig,path):
    fig.savefig(path.with_suffix('.png'),dpi=220,bbox_inches='tight')
    fig.savefig(path.with_suffix('.pdf'),bbox_inches='tight')
    fig.savefig(path.with_suffix('.svg'),bbox_inches='tight')
    plt.close(fig)

def markdown_table(df):
    # No optional tabulate dependency in the installed scientific Python runtime.
    def fmt(x):
        return f'{x:.5g}' if isinstance(x,(float,np.floating)) else str(x)
    return '\n'.join(['| '+' | '.join(map(str,df.columns))+' |',
                       '| '+' | '.join(['---']*len(df.columns))+' |']+
                      ['| '+' | '.join(fmt(x) for x in row)+' |' for row in df.itertuples(index=False,name=None)])

def graph_figure(data,names,cases,params,rule,path):
    from paper_graphs import graph_figure as export
    return export(data,names,cases,params,rule,path)


def lambda_figure(names,frame,path):
    fig,axes=plt.subplots(len(names),2,figsize=(11,3.1*len(names)),squeeze=False)
    for r,name in enumerate(names):
        f=frame[frame.case==name]
        for (method,tau),v in f.groupby(['method','tau_interzone_hours']):
            label=f'{method}, reference tau={tau:.3g} h'; v=v.sort_values('lambda_value')
            for ax,column in [(axes[r,0],'validation_rmse_C'),(axes[r,1],'interzone_edges')]:
                ax.plot(v.lambda_value,v[column],marker='o',ms=3,lw=1,linestyle='-' if method=='savgol' else '--',label=label)
                ax.set_xscale('symlog',linthresh=1e-6); ax.grid(alpha=.2); ax.set_xlabel('Regularisation strength lambda')
        axes[r,0].set_ylabel('24 h validation RMSE (C)'); axes[r,1].set_ylabel('Retained interzone branches')
        axes[r,0].set_title(LABELS[name],fontsize=10); axes[r,1].legend(fontsize=6,ncol=2)
    fig.tight_layout(); savefig(fig,path)

def trajectories(data,names,rule,chosen_zones,episode_indices,path):
    fig,axes=plt.subplots(2,2,figsize=(12,7),sharex=False)
    colours=['#007c91','#e58b2d','#7c55a1']
    for r,zone in enumerate(chosen_zones):
        i=list(data['zones']).index(zone)
        for c,ep in enumerate(episode_indices):
            ax=axes[r,c]; last_ids=None
            for name,color in zip(names,colours):
                with np.load(HERE/'cases'/name/'test_24h_predictions.npz') as p:
                    ids=p[f'{rule}_{ep}_indices']; pred=p[f'{rule}_{ep}_temperature']
                if last_ids is not None: np.testing.assert_array_equal(ids,last_ids)
                last_ids=ids
                ax.plot(np.arange(len(ids))/6,pred[:,i],color=color,lw=1.3,label=LABELS[name])
            ax.plot(np.arange(len(ids))/6,data['T'][ids,i],color='black',lw=1.3,label='EnergyPlus measured')
            ax.set_title(f'{zone}\n{data["times"][ids[0]].date()}',fontsize=10)
            ax.set_xlabel('Hours from forecast start'); ax.set_ylabel('Temperature (C)'); ax.grid(alpha=.2)
    handles,labels=axes[0,0].get_legend_handles_labels(); fig.legend(handles,labels,loc='lower center',fontsize=8,ncol=2)
    fig.suptitle(f'Test predictions: {rule.replace("_"," ")} models\nZones selected by best/worst reference-model VALIDATION RMSE; same test episodes for all variants',fontsize=10)
    fig.tight_layout(rect=[0,.1,1,.93]); savefig(fig,path)

def write_notebook(path,title,body):
    def cell(kind,text):
        out=dict(cell_type=kind,metadata={},source=text.splitlines(keepends=True))
        if kind=='code': out.update(execution_count=None,outputs=[])
        return out
    cells=[cell('markdown',f'# {title}\n\n'+body),cell('code',
        "from pathlib import Path\nimport pandas as pd\nfrom IPython.display import display, Image, Markdown\n"
        "HERE = Path.cwd()\nif not (HERE / 'summary.csv').exists():\n"
        f"    HERE = HERE / {path.parent.name!r}\n"
        "assert (HERE / 'summary.csv').exists(), 'Open this notebook from its experiment folder or its parent.'\n"
        "display(pd.read_csv(HERE / 'summary.csv'))\n"),
        cell('code',"display(Markdown((HERE / 'INTERPRETATION.md').read_text(encoding='utf-8')))\n"),
        cell('code',"display(pd.read_csv(HERE / 'per_zone_RMSE_24h.csv', header=[0, 1], index_col=0))\n"),
        cell('code',"display(Image(filename=str(HERE / 'figures/lambda_sweeps.png')))\n"),
        cell('code',"import json\nfor filename in json.loads((HERE/'figures/graph_pages.json').read_text())['best_accuracy']:\n    display(Image(filename=str(HERE/'figures'/filename)))\n"),
        cell('code',"import json\nfor filename in json.loads((HERE/'figures/graph_pages.json').read_text())['sparse']:\n    display(Image(filename=str(HERE/'figures'/filename)))\n"),
        cell('code',"display(Image(filename=str(HERE / 'figures/temperatures_best_accuracy.png')))\ndisplay(Image(filename=str(HERE / 'figures/temperatures_sparse.png')))\n"),
        cell('code',"edges = pd.read_csv(HERE / 'retained_edges.csv')\ndisplay(edges)\n"),
        cell('markdown',"The notebook reads cached results. It does not refit models or invoke EnergyPlus. Full parameter tables include boundary paths; the graph drawings omit outdoor and ground paths for readability.")]
    path.write_text(json.dumps(dict(cells=cells,metadata=dict(kernelspec=dict(display_name='Python 3',language='python',name='python3')),nbformat=4,nbformat_minor=5),indent=2),encoding='utf-8')

def make_reports(data,cases):
    all_summaries=[]; all_checks={}; plot_reference=HERE/'cases/local_2R1C_wall'
    zones=pd.read_csv(plot_reference/'best_accuracy_validation_by_zone.csv').query('zone != "ALL"').sort_values('rmse_C')
    chosen_zones=[zones.iloc[0].zone,zones.iloc[-1].zone]
    with np.load(plot_reference/'test_24h_predictions.npz') as p:
        episodes=sorted(int(k.split('_')[-2]) for k in p.files if k.startswith('best_accuracy_') and k.endswith('_indices'))
        episode_indices=[]
        for month in [2,8]:
            episode_indices.append(next(k for k in episodes if data['times'][p[f'best_accuracy_{k}_indices'][0]].month==month))
    for group,names in GROUPS.items():
        out=HERE/group; figs=out/'figures'; figs.mkdir(parents=True,exist_ok=True)
        metrics=pd.concat([pd.read_csv(HERE/'cases'/n/'test_metrics.csv') for n in names],ignore_index=True)
        params=pd.concat([pd.read_csv(HERE/'cases'/n/'branch_parameters.csv') for n in names],ignore_index=True)
        air=pd.concat([pd.read_csv(HERE/'cases'/n/'air_parameters.csv') for n in names],ignore_index=True)
        paths=pd.concat([pd.read_csv(HERE/'cases'/n/'lambda_path.csv') for n in names],ignore_index=True)
        edgepaths=pd.concat([pd.read_csv(HERE/'cases'/n/'edge_path.csv') for n in names],ignore_index=True)
        summary=[]
        for name in names:
            sels=json.loads((HERE/'cases'/name/'selection.json').read_text()); all_checks[name]=json.loads((HERE/'cases'/name/'verification.json').read_text())
            for rule,row in sels.items():
                met=metrics[(metrics.case==name)&(metrics.selection==rule)&(metrics.zone=='ALL')].set_index('horizon_hours')
                p=params[(params.case==name)&(params.selection==rule)&(params.kind=='interzone')&params.retained]
                summary.append(dict(case=name,selection=rule,method=row['method'],lambda_value=row['lambda_value'],
                    tau_interzone_hours=row['tau_interzone_hours'],candidate_interzone=row['candidate_interzone'],
                    interzone_edges=row['interzone_edges'],direct_IDF_matches=int((p.direct_IDF_adjacency==True).sum()),states=row['states'],
                    independent_fitted_parameters=row['independent_fitted_parameters'],active_conductances=row['active_conductances'],
                    validation_24h_C=row['validation_rmse_C'],**{f'test_{h}h_C':met.loc[h,'rmse_C'] for h in [1,6,24,72]}))
        summary=pd.DataFrame(summary); summary.to_csv(out/'summary.csv',index=False); all_summaries.append(summary.assign(investigation=group))
        metrics.to_csv(out/'test_metrics.csv',index=False); paths.to_csv(out/'lambda_path.csv',index=False); edgepaths.to_csv(out/'edge_path.csv',index=False)
        params.to_csv(out/'all_branch_parameters.csv',index=False); air.to_csv(out/'air_capacitances.csv',index=False)
        params[params.retained].to_csv(out/'retained_edges.csv',index=False)
        params[params.retained][['case','selection','node_i','node_j','branch_order','R_total_K_kW','C_storage_kWh_K','direct_IDF_adjacency']].to_csv(out/'simplified_RC_parameters.csv',index=False)
        metrics[(metrics.horizon_hours==24)&(metrics.zone!='ALL')].pivot(index='zone',columns=['case','selection'],values='rmse_C').to_csv(out/'per_zone_RMSE_24h.csv')
        comparison=[]
        for name in names:
            # Include forbidden interzone pairs explicitly in the before/after list.
            for i,j in combinations(range(len(data['zones'])),2):
                for rule in ['best_accuracy','sparse']:
                    match=params[(params.case==name)&(params.selection==rule)&(params.node_i==data['zones'][i])&(params.node_j==data['zones'][j])&(params.kind=='interzone')]
                    comparison.append(dict(case=name,selection=rule,node_i=data['zones'][i],node_j=data['zones'][j],candidate_allowed=len(match)>0,
                                           retained=bool(len(match) and match.iloc[0].retained),G_kW_K=float(match.iloc[0].G_kW_K) if len(match) else 0.))
        pd.DataFrame(comparison).to_csv(out/'interzone_before_after.csv',index=False)
        lambda_figure(names,paths,figs/'lambda_sweeps')
        for rule in ['best_accuracy','sparse']:
            graph_figure(data,names,cases,params,rule,figs/f'graphs_{rule}')
            trajectories(data,names,rule,chosen_zones,episode_indices,figs/f'temperatures_{rule}')
        title=group.replace('_',' ').title()
        notes={
            '01_candidate_connectivity':'Only candidate connectivity changes. Air/wall priors and branch dynamics are held constant. Local connectivity excludes cross-floor zone pairs and remote plenum paths; it does not supply exact within-floor adjacency.',
            '02_branch_complexity':'All designated storage branches change between 1R and 2R1C under the same local geometry and fixed air capacitances. Interzone resistance bounds match; wall capacitance applies only when storage exists. Parallel direct/storage outdoor paths merge into one conductance in 1R. Each model family repeats discovery; this does not isolate order at one frozen topology.',
            '03_physical_information':'The free-air and air-only configurations share the same broad bounds and interzone tau grid. The wall-prior configuration additionally ties G and C through a representative construction, fixes interzone tau, and imposes conditional conductance bounds. Improved agreement with imposed values is not independent recovery of physical properties.',
        }[group]
        best=summary[summary.selection=='best_accuracy'].reset_index(drop=True)
        delta=best.iloc[-1].test_24h_C-best.iloc[0].test_24h_C
        text=f'# {title}\n\n{notes}\n\n## Matched results\n\n'+markdown_table(summary[['case','selection','interzone_edges','states','independent_fitted_parameters','validation_24h_C','test_24h_C','test_72h_C']])
        text+=f'\n\nFor the minimum-validation-error models, the final listed variant changes 24-hour test RMSE by {delta:+.5f} C relative to the first listed variant. This is descriptive exploratory evidence, not a significance test. The sparse selection is a different result and must not be labelled the minimum-error model.\n'
        text+='\n## Interpretation limits\n\n- Training and evaluation episodes are identical across variants; test periods have been used in earlier experiments.\n- Report full lambda paths, not just one selected model. Supports need not be nested as lambda increases.\n- Zero direct interzone edges does not imply zero physical heat exchange; measured boundary temperatures and supplied heat inputs can explain shared variation.\n- Predictions use realized future heat inputs and boundary temperatures, with no observer during each rollout. This does not demonstrate response to new HVAC commands.\n- State count is a computational proxy, not measured MPC solve time. These models are not installed in the MPC.\n- Parameter count excludes imposed capacitances and derived storage capacitances. A validation-selected common time constant is an additional hyperparameter.\n- Boundary and slab parameters retain broad bounds; interior-wall information is not transferred to slabs or outdoor constructions.\n'
        text+=f'\nPlot zones are {chosen_zones}, selected from the shared reference model\'s validation errors. The same first February and August test episodes are used throughout.\n'
        (out/'INTERPRETATION.md').write_text(text,encoding='utf-8')
        write_notebook(out/'Review.ipynb',title,notes)
    combined=pd.concat(all_summaries,ignore_index=True); combined.to_csv(HERE/'all_investigations_summary.csv',index=False)
    hashes=[]
    for name in cases:
        d=pd.read_csv(HERE/'cases'/name/'regression_diagnostics.csv'); hashes.extend(d.training_indices_sha256.tolist())
    assert len(set(hashes))==1, 'Unequal training sample indices across variants'
    verification=dict(all_cases_complete=True,matched_training_indices=True,training_indices_sha256=hashes[0],
                      physics_checks=all_checks,shared_reference='local_2R1C_wall reused identically in all three investigations',
                      plot_zones=chosen_zones,plot_episode_indices=episode_indices)
    (HERE/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
    (HERE/'RESULTS.md').write_text('# Three matched RC investigations\n\n'+markdown_table(combined[['investigation','case','selection','states','independent_fitted_parameters','test_24h_C']])+'\n\nRead the individual INTERPRETATION.md files before drawing physical or MPC conclusions.\n',encoding='utf-8')
    print(combined.to_string(index=False),flush=True)
