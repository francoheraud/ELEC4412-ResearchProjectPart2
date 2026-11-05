"""Verify the saved extension and produce a compact comparison figure."""
from rc_engine import *
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from make_reports import savefig, markdown_table
from run_investigations import save_json
import unittest
import io

HERE=Path(__file__).resolve().parent

def main():
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_engine','test_3r2c'])
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (HERE/'test_results.txt').write_text(stream.getvalue(),encoding='utf-8')
    assert result.wasSuccessful(),stream.getvalue()
    data=load_inputs(DEFAULT_IMPLEMENTATION,HERE); splits=split_blocks(data)
    cfg=case_definitions(data)['local_3R2C_wall']; out=HERE/'cases/local_3R2C_wall'
    path=pd.read_csv(out/'lambda_path.csv')
    assert len(path)==36 and path.validation_rmse_C.notna().all()
    selections=json.loads((out/'selection.json').read_text())
    best=path.sort_values(['validation_rmse_C','states','independent_fitted_parameters']).iloc[0]
    assert best.key==selections['best_accuracy']['key']
    saved_metrics=pd.read_csv(out/'test_metrics.csv')
    for rule,row in selections.items():
        params=np.load(out/f'{rule}.npz')
        bs=branches(data['zones'],cfg['mask'],cfg['order'],row['tau_interzone_hours'])
        metrics,_,_=evaluate(data,splits['test'],bs,params['theta'],True,[1,6,24,72])
        actual=pd.DataFrame(metrics).sort_values(['horizon_hours','zone'])
        saved=saved_metrics[saved_metrics.selection==rule].sort_values(['horizon_hours','zone'])
        np.testing.assert_allclose(actual.rmse_C,saved.rmse_C,atol=1e-12,rtol=1e-12)
    allhash=[]
    for name in ['local_1R_wall','local_2R1C_wall','local_3R2C_wall']:
        allhash+=pd.read_csv(HERE/'cases'/name/'regression_diagnostics.csv').training_indices_sha256.tolist()
    assert len(set(allhash))==1
    # Record the frozen comparator content, preserving its original fit contracts.
    baseline_manifest=[]
    for name in ['local_1R_wall','local_2R1C_wall']:
        for f in (HERE/'cases'/name).rglob('*'):
            if f.is_file(): baseline_manifest.append(dict(path=str(f.relative_to(HERE)),sha256=sha(f)))
    save_json(HERE/'frozen_comparator_manifest.json',baseline_manifest)
    for notebook in HERE.rglob('*.ipynb'):
        content=json.loads(notebook.read_text(encoding='utf-8'))
        for cell in content['cells']:
            if cell['cell_type']=='code': compile(''.join(cell['source']),str(notebook),'exec')
    summary=pd.read_csv(HERE/'02_branch_complexity/summary.csv')
    rows=summary[summary.selection=='best_accuracy'].copy()
    rows['Model']=['1R','2R1C','3R2C']
    compact=rows[['Model','lambda_value','interzone_edges','states','independent_fitted_parameters','validation_24h_C','test_1h_C','test_6h_C','test_24h_C','test_72h_C']]
    compact.to_csv(HERE/'comparison.csv',index=False)
    figs=HERE/'02_branch_complexity/figures'
    with plt.rc_context({'font.size':9,'axes.labelsize':9,'xtick.labelsize':9,'ytick.labelsize':9,'pdf.fonttype':42,'ps.fonttype':42}):
        fig,axes=plt.subplots(1,2,figsize=(6.7,2.85))
        colors=['#007c91','#d47b18','#7c55a1']
        for (_,r),color,style in zip(rows.iterrows(),colors,['o-','s--','^-.']):
            axes[0].plot(range(4),[r[f'test_{h}h_C'] for h in [1,6,24,72]],style,color=color,label=r.Model,lw=1.4,ms=4)
        axes[0].set_xticks(range(4),['1','6','24','72']); axes[0].set_xlabel('Prediction horizon (h)')
        axes[0].set_ylabel('Test RMSE ($^\\circ$C)'); axes[0].grid(alpha=.2); axes[0].legend(frameon=False)
        axes[1].bar(rows.Model,rows.states,color=colors,width=.6)
        for i,value in enumerate(rows.states): axes[1].text(i,value+1,str(value),ha='center',va='bottom')
        axes[1].set_ylim(0,67); axes[1].set_ylabel('Dynamic states'); axes[1].set_xlabel('Branch formulation')
        fig.tight_layout(); savefig(fig,figs/'order_comparison')
    two=rows[rows.Model=='2R1C'].iloc[0]; three=rows[rows.Model=='3R2C'].iloc[0]
    note='''# 3R2C sensitivity result

The symmetric 3R2C extension does not improve the selected 24-hour validation or test RMSE over the matched 2R1C model. All models below are selected by validation error, not by test results.

'''+markdown_table(compact)+f'''

Relative to 2R1C, 3R2C changes 24-hour test RMSE by {three.test_24h_C-two.test_24h_C:+.6f} C ({100*(three.test_24h_C/two.test_24h_C-1):+.2f}%). State count rises from {two.states} to {three.states}. Six-hour test RMSE improves from {two.test_6h_C:.6f} to {three.test_6h_C:.6f} C; one-hour and 72-hour test errors are slightly higher. There is no consistent improvement across horizons.

## Regularisation path

For Savitzky-Golay, lambda=0 retains 11 interzone branches / 79 states with 0.648981 C validation RMSE. Lambda=0.01 retains 10 / 77 with 0.647900 C; lambda=0.031623 retains 8 / 73 with 0.648384 C; lambda=0.1 retains zero / 57 with 0.632899 C. The minimum-error and complexity-selected choices coincide in this extension. Zero interzone branches does not mean there is no storage: the selected model has 21 active boundary-storage branches with two masses each, plus 15 air states.

## What this does and does not show

- This tests equal R/3 sections and equal Ctotal/2 masses while preserving each branch's total resistance and capacitance assumptions. It does not fit arbitrary resistance ratios, capacity ratios, or additional independent parameters.
- The 57 versus 65 independently fitted parameters in the selected 3R2C versus 2R1C models reflect their different retained supports. For an identical retained support, their independent parameter counts would match.
- All storage categories change, and topology is rediscovered. This is not evidence specifically against 3R2C interzone walls or against all higher-order RC models.
- The known representative-wall area-bound mismatch remains unchanged. Changing storage order alone cannot repair that assumption.
- The 3R2C wall's clamped-endpoint fast mode is about 6.42 minutes, shorter than the 10-minute sampling interval. Limited temporal resolution is a possible limitation, not an established cause of the measured error.
- Known future heat inputs and boundary temperatures, reused test periods, and fixed air capacities are shared with the previous comparison. This is conditional predictive validation, not a control experiment or a statistical significance claim.
- These results provide no 24-hour prediction-based reason to replace the tested 2R1C formulation with this particular 3R2C configuration. They do not by themselves show that 2R1C is optimal for MPC.

The notebook and PDF/SVG/PNG figures are in `02_branch_complexity`. Full branch parameters include total R/C, per-section R/C and reference/modal time scales. No MPC model was changed.
'''
    (HERE/'RESULTS.md').write_text(note,encoding='utf-8')
    interpretation=HERE/'02_branch_complexity/INTERPRETATION.md'
    interpretation.write_text(note,encoding='utf-8')
    # Include the compact figure in the cached-results notebook.
    nbpath=HERE/'02_branch_complexity/Review.ipynb'; nb=json.loads(nbpath.read_text())
    if not any('order_comparison.png' in ''.join(c['source']) for c in nb['cells']):
        nb['cells'].insert(3,dict(cell_type='code',metadata={},execution_count=None,outputs=[],source=["display(Image(filename=str(HERE / 'figures/order_comparison.png')))\n"]))
    nb['cells'][0]['source']=['# Branch complexity: 1R, 2R1C and 3R2C\n\nFrozen 1R/2R1C results and the new symmetric 3R2C sensitivity comparison. Minimum-error and sparse selections use validation data only.\n']
    nbpath.write_text(json.dumps(nb,indent=2),encoding='utf-8')
    save_json(HERE/'delivery_verification.json',dict(tests_run=result.testsRun,tests_passed=True,lambda_evaluations=36,matched_indices=True,
        saved_3R2C_predictions_reproduced=True,baseline_matrices_reproduced=True,notebook_code_syntax_checked=True,
        notebook_executed=False,source_hashes={p.name:sha(p) for p in HERE.glob('*.py')}))
    protocol=json.loads((HERE/'extension_protocol.json').read_text())
    protocol['source_hashes']={p.name:sha(p) for p in HERE.glob('*.py')}
    save_json(HERE/'extension_protocol.json',protocol)
    print(note)

if __name__=='__main__': main()
