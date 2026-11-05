"""Run the three controlled investigations without modifying historical outputs."""
from rc_engine import *
import argparse
import shutil

HERE=Path(__file__).resolve().parent

def save_json(path,value):
    Path(path).write_text(json.dumps(value,indent=2,default=lambda x:x.item() if hasattr(x,'item') else str(x)),encoding='utf-8')

def initialise(implementation):
    target=HERE/'inputs'; target.mkdir(exist_ok=True)
    source=Path(implementation)/'rc-modelling/physical_priors'
    for src,name in [(source/'results/air_priors.csv','air_priors.csv'),
                     (source/'results/construction_references.csv','construction_references.csv'),
                     (source/'single_wall_prior/results/protocol.json','wall_prior.json')]:
        dest=target/name
        if dest.exists() and sha(dest)!=sha(src): raise ValueError('Input changed: '+name)
        if not dest.exists(): shutil.copy2(src,dest)

def parameter_rows(data,bs,x,fixed_air,case,selection):
    refs=pd.read_csv(HERE/'inputs/construction_references.csv'); n=len(data['zones']); nb=len(bs)
    rows=[]
    for e,b in enumerate(bs):
        ref=refs[(refs.i==b.i)&(refs.j==b.j)] if b.interzone else refs.iloc[:0]
        Gref=float(ref.G_with_assumed_films_kW_K.sum()); Cref=float(ref.C_material_kWh_K.sum())
        g=float(x[e]); active=g>TOL
        rows.append(dict(case=case,selection=selection,branch_index=e,node_i=data['zones'][b.i],
                         node_j=data['zones'][b.j] if b.interzone else data['boundary_names'][b.j],kind=b.kind,
                         branch_order=('3R2C' if b.storage_nodes==2 else '2R1C') if b.tau else '1R',retained=active,G_kW_K=g,
                         R_total_K_kW=1/g if active else np.nan,C_storage_kWh_K=4*g*b.tau if active else 0.,tau_hours=b.tau,
                         reference_tau_hours=b.tau,storage_nodes=b.storage_nodes if active and b.tau else 0,
                         R_each_K_kW=1/((b.storage_nodes+1)*g) if active and b.tau else (1/g if active else np.nan),
                         C_each_kWh_K=4*g*b.tau/b.storage_nodes if active and b.tau else 0.,
                         slow_clamped_endpoint_mode_hours=(2*b.tau/3 if b.storage_nodes==2 else b.tau) if b.tau else np.nan,
                         fast_clamped_endpoint_mode_hours=2*b.tau/9 if b.tau and b.storage_nodes==2 else np.nan,
                         direct_IDF_adjacency=bool(len(ref)) if b.interzone else None,
                         reference_G_kW_K=Gref if Gref else np.nan,reference_C_kWh_K=Cref if Cref else np.nan,
                         G_ratio=g/Gref if active and Gref else np.nan,
                         C_ratio=4*g*b.tau/Cref if active and Cref and b.tau else np.nan,
                         reference_is_prior_wall=bool(len(ref) and 'CORE_BOT_ZN_5_WALL_EAST' in ref.surface.tolist())))
    return rows

def run_case(data,splits,name,cfg):
    out=HERE/'cases'/name; out.mkdir(parents=True,exist_ok=True)
    contract=dict(config=cfg,data_sha256=data['source_sha256'],engine_sha256=sha(HERE/'rc_engine.py'),
                  lambdas=LAMBDAS.tolist(),methods=METHODS)
    if (out/'contract.json').exists():
        if json.loads((out/'contract.json').read_text())!=contract: raise RuntimeError('Run contract changed; use a new output folder.')
    else: save_json(out/'contract.json',contract)
    if (out/'complete.json').exists():
        print('REUSE completed case',name,flush=True); return
    started=time.perf_counter(); rows=[]; edgepath=[]; diagnostics=[]
    for tau in cfg['taus']:
      bs=branches(data['zones'],cfg['mask'],cfg['order'],tau); lo,hi,m=bounds(data,bs,cfg['fixed_air'],cfg['wall_prior'])
      for method in METHODS:
        variant=f'{method}_tau{tau:.9g}'; vout=out/variant; vout.mkdir(exist_ok=True)
        if (vout/'complete.json').exists():
            rows.extend(pd.read_csv(vout/'lambda_path.csv').to_dict('records'))
            edgepath.extend(pd.read_csv(vout/'edge_path.csv').to_dict('records'))
            diagnostics.append(json.loads((vout/'diagnostics.json').read_text())); continue
        tic=time.perf_counter(); stats=regression(data,splits['train'],bs,method,cfg['fixed_air'])
        diagnostics.append(dict(variant=variant,rank=stats['rank'],columns=len(lo),rows=stats['rows'],
                                training_indices_sha256=stats['indices_sha256'],condition=float(np.linalg.cond(stats['R']))))
        if stats['rank']<len(lo): raise ValueError(f'Rank-deficient regression: {name}/{variant}')
        print('FITTING',name,variant,'columns',len(lo),flush=True)
        cache={}; warm=None; vr=[]; ve=[]
        zero,_=fit_refit(stats,lo,hi,m,[]); full,_=fit_refit(stats,lo,hi,m,range(m))
        for index,lam in enumerate(LAMBDAS):
            fit_start=time.perf_counter()
            if cfg['wall_prior']:
                starts=[zero,full] + ([] if warm is None else [warm])
                trials=[fit_conditional(stats,lo,hi,m,float(lam),initial) for initial in starts]
                valid=[t for t in trials if t[3]]
                if len(valid)!=len(trials): raise RuntimeError(f'Coordinate convergence failure: {name} {variant} {lam}')
                warm,obj,sweeps,_=min(valid,key=lambda a:a[1]); shrunk=warm
                spread=max(t[1] for t in trials)-min(t[1] for t in trials)
            else:
                shrunk,opt=fit_refit(stats,lo,hi,m,range(m),float(lam))
                obj=float(np.sum((stats['R']@(shrunk*stats['scale'])-stats['y'])**2)+stats['constant']+lam*shrunk[:m].sum())
                sweeps=0; spread=0.
            support=tuple(np.flatnonzero(shrunk[:m]>TOL))
            if support not in cache:
                x,opt=fit_refit(stats,lo,hi,m,support)
                # Values below the declared reporting tolerance are absent in the
                # exported model as well as evaluation; this includes boundaries.
                x[:len(bs)][x[:len(bs)]<=TOL]=0.
                met,_,_=evaluate(data,splits['validation'],bs,x,cfg['fixed_air'])
                cache[support]=(x,met[0]['rmse_C'],opt)
            x,rmse,opt=cache[support]; key=f'{variant}_L{index:02d}'
            np.savez(vout/f'L{index:02d}.npz',theta=x,discovery_theta=shrunk)
            row=dict(case=name,key=key,method=method,tau_interzone_hours=tau,lambda_value=float(lam),
                     candidate_interzone=m,candidate_branches=len(bs),**complexity(data,bs,x,cfg['fixed_air']),
                     validation_rmse_C=rmse,penalized_training_objective=obj,refit_optimality=opt,
                     start_objective_spread=spread,coordinate_sweeps=sweeps,seconds=time.perf_counter()-fit_start,
                     selected_timescale_hyperparameters=0 if cfg['wall_prior'] or cfg['order']=='1R' else 1)
            vr.append(row)
            for e,b in enumerate(bs):
                ve.append(dict(case=name,key=key,branch_index=e,kind=b.kind,node_i=data['zones'][b.i],
                               node_j=data['zones'][b.j] if b.interzone else data['boundary_names'][b.j],
                               discovery_G_kW_K=shrunk[e],refit_G_kW_K=x[e],retained=bool(x[e]>TOL)))
            pd.DataFrame(vr).to_csv(vout/'lambda_path.csv',index=False)
            print(f'  lambda={lam:g}, edges={row["interzone_edges"]}, states={row["states"]}, val={rmse:.6f}',flush=True)
        pd.DataFrame(ve).to_csv(vout/'edge_path.csv',index=False); save_json(vout/'diagnostics.json',diagnostics[-1])
        save_json(vout/'complete.json',dict(seconds=time.perf_counter()-tic)); rows.extend(vr); edgepath.extend(ve)
    path=pd.DataFrame(rows); path.to_csv(out/'lambda_path.csv',index=False)
    pd.DataFrame(edgepath).to_csv(out/'edge_path.csv',index=False); pd.DataFrame(diagnostics).to_csv(out/'regression_diagnostics.csv',index=False)
    best=path.sort_values(['validation_rmse_C','states','independent_fitted_parameters']).iloc[0]
    eligible=path[path.validation_rmse_C<=best.validation_rmse_C+.02]
    sparse=eligible.sort_values(['states','active_conductances','validation_rmse_C']).iloc[0]
    selected={'best_accuracy':best.to_dict(),'sparse':sparse.to_dict()}; metrics=[]; eps=[]; params=[]; air=[]; verifications={}; predictions={}
    for rule,row in selected.items():
        variant,idx=row['key'].rsplit('_L',1)
        x=np.load(out/variant/f'L{idx}.npz')['theta']; bs=branches(data['zones'],cfg['mask'],cfg['order'],row['tau_interzone_hours'])
        lo,hi,m=bounds(data,bs,cfg['fixed_air'],cfg['wall_prior']); verifications[rule]=verify_model(data,bs,x,cfg['fixed_air'],lo,hi)
        A,B,Ad,Bd,C,kept=state_matrices(data,bs,x,cfg['fixed_air'])
        np.savez(out/f'{rule}.npz',theta=x,A=A,B=B,Ad=Ad,Bd=Bd,C=C,storage_branch_indices=kept,storage_trace_columns=state_trace_columns(bs,kept),zones=data['zones'],boundary_names=data['boundary_names'],dt_hours=data['dt_hours'])
        save_json(out/f'{rule}_branches.json',[asdict(b) for b in bs])
        met,ep,pred=evaluate(data,splits['test'],bs,x,cfg['fixed_air'],[1,6,24,72],True)
        metrics.extend([dict(case=name,selection=rule,**r) for r in met]); eps.extend([dict(case=name,selection=rule,**r) for r in ep])
        params.extend(parameter_rows(data,bs,x,cfg['fixed_air'],name,rule))
        for i,z in enumerate(data['zones']):
            air.append(dict(case=name,selection=rule,zone=z,C_kWh_K=C[i],reference_C_kWh_K=data['C_air'][i],ratio=C[i]/data['C_air'][i],fixed_by_prior=cfg['fixed_air']))
        for k,(ids,p) in enumerate(pred): predictions[f'{rule}_{k}_indices']=ids; predictions[f'{rule}_{k}_temperature']=p
        # Validation-selected plotting zones, held fixed across each investigation later.
        val,_,_=evaluate(data,splits['validation'],bs,x,cfg['fixed_air'],[24])
        pd.DataFrame(val).to_csv(out/f'{rule}_validation_by_zone.csv',index=False)
    pd.DataFrame(metrics).to_csv(out/'test_metrics.csv',index=False); pd.DataFrame(eps).to_csv(out/'test_episodes.csv',index=False)
    pd.DataFrame(params).to_csv(out/'branch_parameters.csv',index=False); pd.DataFrame(air).to_csv(out/'air_parameters.csv',index=False)
    np.savez_compressed(out/'test_24h_predictions.npz',**predictions)
    save_json(out/'selection.json',selected); save_json(out/'verification.json',verifications)
    save_json(out/'complete.json',dict(seconds=time.perf_counter()-started,case=name))

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--implementation',type=Path); p.add_argument('--case'); p.add_argument('--report-only',action='store_true'); args=p.parse_args()
    implementation=args.implementation or (HERE.parent.parent if (HERE.parent/'results/prepared_data.npz').exists() else DEFAULT_IMPLEMENTATION)
    initialise(implementation); data=load_inputs(implementation,HERE); splits=split_blocks(data); cases=case_definitions(data)
    protocol=dict(groups=GROUPS,cases=cases,data_sha256=data['source_sha256'],source=str(implementation/'rc-modelling/results/prepared_data.npz'),
        lambdas=LAMBDAS.tolist(),methods=METHODS,train='Days 1-14 January/April/July/October',validation='Days 15-21 of the same months',test='Days 15-21 February/May/August/November',
        conditioning_hours=72,sg='Seven points, degree 2, 60-minute span; common valid training indices with trapezoidal method',
        trapezoidal='Secant temperature derivative and endpoint-averaged temperatures, reconstructed storage and heat inputs',
        prediction='Exact matrix exponential; interval-average realized inputs held constant per step; no within-rollout resetting or observer',
        selection='Per configuration across methods and tau candidates: minimum validation error; plus fewest states then active conductances then RMSE within 0.02 C of minimum',
        geometry='Local means same-floor zone pairs and physically bordering plenums only. Outdoor and ground candidates unchanged. Unrestricted permits all zone pairs/all plenums; lower-floor plenum candidates use slab-type storage in 2R1C.',
        complexity='All designated storage branches change together: interzone, outdoor envelope and lower-plenum slab. Direct outdoor and collapsed envelope path merge into one G in 1R. Upper-plenum and ground paths remain 1R. Discovery is repeated: comparison concerns model families, not order at a frozen topology.',
        physical_information='Free-air versus fixed-air uses identical broad conductance bounds and tau grid. Adding wall prior also fixes interzone tau to Cref/(4Gref); this changes the admissible dynamics, not just the optimiser.',
        fixed_boundary_timescales='Outdoor and slab tau=12 h from previous exploratory validation; held identical across 2R1C comparisons, not newly inferred material values.',
        air_bounds_kWh_K=[.01,1000.],broad_conductance_bounds_kW_K=[0,100],gain_bounds=[0,2],wall_area_factor=[.5,2],
        parameter_count='Active conductances + two estimated gain coefficients + 15 air capacities only when free. Storage C is tied to G/tau, not independent. Selected common tau reported separately as a hyperparameter.',
        limitations=['Reused test periods: exploratory, not a fresh blind holdout.','Known future heat inputs and plenum temperatures: conditional prediction, not an operational forecast.','Nonconvex conditional wall bounds: multistart coordinate optimum, no global guarantee.','Physical agreement imposed by a prior is not independent validation.','No MPC plant or controller is changed.','No 3R2C.'],
        source_hashes={f.name:sha(f) for f in HERE.glob('*.py')})
    if not args.report_only: save_json(HERE/'protocol.json',protocol)
    if not args.report_only:
        for name,cfg in cases.items():
            if args.case and args.case!=name: continue
            run_case(data,splits,name,cfg)
    if all((HERE/'cases'/name/'complete.json').exists() for name in cases):
        from make_reports import make_reports
        make_reports(data,cases)
    elif not args.case: raise RuntimeError('Incomplete case outputs')

if __name__=='__main__':
    raise SystemExit('For this isolated extension use: python run_3r2c.py')
