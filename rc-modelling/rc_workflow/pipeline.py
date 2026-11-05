from pathlib import Path
import json,time,platform
import numpy as np
import pandas as pd
from .energyplus import prepare_and_run,digest
from .data import load,split_blocks
from .model import Layout,inputs,rollout
from .identification import equations,Regression
from .evaluation import evaluate,select
from .prices import load_prices

def run(config,force_energyplus=False):
    start=time.perf_counter();out=config.output;out.mkdir(parents=True,exist_ok=True)
    (out/'config.json').write_text(json.dumps(config.serializable(),indent=2))
    print('Preparing instrumented EnergyPlus run...',flush=True)
    sql,meta=prepare_and_run(config,force_energyplus)
    print('Loading zone thermal inputs...',flush=True)
    data=load(sql,meta,config);splits=split_blocks(data,config);layout=Layout(data.zones,data.boundary_names,config)
    np.savez_compressed(out/'prepared_data.npz',time=data.time.astype(str).to_numpy(dtype=str),T=data.T,boundaries=data.boundaries,
                        hvac_kW=data.hvac,known_gain_kW=data.convective+data.outdoor_air,radiant_filtered_kW=data.radiant,
                        solar_filtered_kW=data.solar,setpoints=data.setpoints,occupancy=data.occupancy,electric_kWh=data.electric,
                        zones=np.array(data.zones),boundary_names=np.array(data.boundary_names),dt_hours=data.dt)
    pd.DataFrame([dict(split=k,block=j,start=str(data.time[b[0]]),end=str(data.time[b[-1]]),samples=len(b)) for k,v in splits.items() for j,b in enumerate(v)]).to_csv(out/'splits.csv',index=False)
    prices,audit=load_prices(config.implementation/'ep-data'/'RealTime_BES-H_Prices_Annual.csv')
    prices.to_csv(out/'prices_audited.csv');(out/'price_audit.json').write_text(json.dumps(audit,indent=2))
    (out/'metadata.json').write_text(json.dumps(meta,indent=2))
    paths=[];edges=[];comparisons=[];parameters=[];diags=[];allmodels={};selections={};episode_tables=[]
    for method in config.methods:
        print(f'{method}: constructing {layout.m}-edge candidate regression...',flush=True)
        a,y=equations(data,splits['train'],layout,method,config);reg=Regression(a,y,layout)
        # Sufficient statistics retain the exact unpenalised quadratic for fast support refits.
        compressed_a=reg.R*reg.scale*np.sqrt(layout.p);compressed_y=reg.target*np.sqrt(layout.p)
        del a,y
        fitted={};path=[]
        def refit(support):
            key=tuple(support)
            if key not in fitted:
                reduced=Regression(compressed_a,compressed_y,layout,key);reduced.y2=reg.y2
                theta,diag=reduced.fit();diag['rows']=reg.rows
                fitted[key]=(theta,diag)
            return fitted[key]
        for lam in config.lambdas:
            shrunk,diag=reg.fit(lam);support=tuple(np.flatnonzero(shrunk[layout.gs]>config.support_tol))
            theta,refitdiag=refit(support)
            val,_=evaluate(data,layout,theta,splits['validation'],[config.selection_horizon_hours])
            score=float(val.loc[val.zone=='ALL','rmse_C'].iloc[0])
            row=dict(method=method,**{'lambda':lam},edges=len(support),refit_nonzero_edges=int((theta[layout.gs]>config.support_tol).sum()),
                     validation_rmse_C=score,parameter_count=layout.p-layout.m+len(support))
            path.append(row);diags.append(dict(method=method,stage='discovery',**{'lambda':lam},**diag))
            allmodels[(method,float(lam))]=theta
            for e,(i,j) in enumerate(layout.edges):edges.append(dict(method=method,**{'lambda':lam},zone_i=data.zones[i],zone_j=data.zones[j],
                    discovery_G_kW_per_K=shrunk[layout.gs.start+e],retained=e in support,refit_G_kW_per_K=theta[layout.gs.start+e]))
            print(f'  lambda={lam:g}: {len(support)} edges, validation 24h RMSE={score:.4f} C',flush=True)
        path=pd.DataFrame(path);chosen=select(path,config.selection_tolerance_C);selections[method]=chosen.to_dict();paths.append(path)
        manual=tuple(e for e,pair in enumerate(layout.edges) if pair in [tuple(x) for x in meta['manual_edges']])
        baseline_supports={'dense':tuple(range(layout.m)),'manual_surface_adjacency':manual,'no_interzone':()}
        models={'selected_laplacian':allmodels[(method,float(chosen['lambda']))]}
        for name,support in baseline_supports.items():models[name],diag=refit(support)
        for name,theta in models.items():
            matrix=layout.matrices(theta,data.dt)
            metrics,episodes=evaluate(data,layout,theta,splits['test'],config.horizons_hours)
            metrics.insert(0,'model',name);metrics.insert(0,'method',method);comparisons.append(metrics)
            episodes.insert(0,'model',name);episodes.insert(0,'method',method);episode_tables.append(episodes)
            for p,value in enumerate(theta):parameters.append(dict(method=method,model=name,parameter=layout.names[p],value=value,unit=layout.units[p],
                      at_lower_bound=bool(np.isclose(value,layout.lower[p],atol=1e-6,rtol=0)),at_upper_bound=bool(np.isclose(value,layout.upper[p],atol=1e-6,rtol=0))))
            modeldir=out/'models';modeldir.mkdir(exist_ok=True)
            np.savez(modeldir/f'{method}_{name}.npz',theta=theta,A=matrix['A'],B=matrix['B'],Ad=matrix['Ad'],Bd=matrix['Bd'],L=matrix['L'],
                     zones=np.array(data.zones),input_names=np.array(matrix['input_names']),dt_hours=data.dt,eigenvalues=matrix['eigenvalues'])
        # Example held-out summer trajectory, 72h with exactly one initialisation.
        block=splits['test'][2][:round(72/data.dt)+1];theta=models['selected_laplacian'];mat=layout.matrices(theta,data.dt);u=inputs(data)
        pred=rollout(mat['Ad'],mat['Bd'],(u[block[:-1]]+u[block[1:]])/2,data.T[block[0]])
        np.savez(out/f'{method}_example.npz',time=data.time[block].astype(str).to_numpy(dtype=str),actual=data.T[block],predicted=pred,zones=np.array(data.zones))
    path=pd.concat(paths,ignore_index=True);path.to_csv(out/'lambda_path.csv',index=False)
    pd.DataFrame(edges).to_csv(out/'edge_path.csv',index=False)
    pd.concat(comparisons,ignore_index=True).to_csv(out/'test_metrics.csv',index=False)
    pd.concat(episode_tables,ignore_index=True).to_csv(out/'test_episodes.csv',index=False)
    pd.DataFrame(parameters).to_csv(out/'parameters.csv',index=False);pd.DataFrame(diags).to_csv(out/'solver_diagnostics.csv',index=False)
    # Choose differentiation method on validation only. Never select on test metrics.
    preferred=min(selections,key=lambda m:selections[m]['validation_rmse_C'])
    selection=dict(rule=f'Fewest discovery edges within {config.selection_tolerance_C} C of minimum validation 24h RMSE, within each method',
                   by_method=selections,preferred_method=preferred,exported_model=f'models/{preferred}_selected_laplacian.npz')
    (out/'selection.json').write_text(json.dumps(selection,indent=2))
    provenance=dict(source_idf=str(config.locate('.idf')),source_sha256=digest(config.locate('.idf')),sql=str(sql),
                    elapsed_seconds=time.perf_counter()-start,python=platform.python_version(),numpy=np.__version__,
                    validation_protocol='held-out seasonal blocks, not cross-validation; final test untouched by selection',
                    deployment_status='Offline known-input validation only; no HVAC actuator mapping or MPC controller implemented')
    (out/'provenance.json').write_text(json.dumps(provenance,indent=2))
    from .reporting import make_figures,write_summary
    make_figures(out);write_summary(out)
    print(f'Complete: {out}',flush=True)
    return selection
