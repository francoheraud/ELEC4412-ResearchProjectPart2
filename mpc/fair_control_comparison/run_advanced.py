import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
from pathlib import Path
import argparse,json,re,shutil,hashlib
from types import SimpleNamespace
from run import setup,report,ROOT,DEFAULT
from advanced_control import AdvancedRun
from mpc_workflow.runtime import idf_objects

def split_schedule(text):
    clean=re.sub(r'!.*',lambda m:' '*len(m.group()),text)
    spans=[(m,[v.strip() for v in m.group()[:-1].split(',')]) for m in re.finditer(r'[^;]+;',clean)]
    schedule=next(o for m,o in spans if o[0].lower()=='schedule:compact' and o[1]=='Seasonal-Reset-Supply-Air-Temp-Sch')
    replacements=[]
    for m,o in spans:
        if o[0].lower()=='setpointmanager:scheduled' and o[1] in [f'VAV_{i} SAT setpoint' for i in range(1,4)]:
            new=o.copy();new[3]=f'Thesis SAT Floor {o[1][4]}'
            start=m.start()+len(m.group())-len(m.group().lstrip());replacements.append((start,m.end(),',\n  '.join(new)+';'))
    assert len(replacements)==3
    for a,b,s in sorted(replacements,reverse=True):text=text[:a]+s+text[b:]
    for g in range(3):
        new=schedule.copy();new[1]=f'Thesis SAT Floor {g+1}';text+='\n'+',\n  '.join(new)+';\n'
    original=idf_objects(clean);actual=idf_objects(text)
    # Three references changed plus three exact clones; all other objects retained.
    assert len(actual)==len(original)+3
    changed=[(a,b) for a,b in zip(original,actual) if a!=b]
    assert len(changed)==3 and all(a[:3]==b[:3] and a[4:]==b[4:] for a,b in changed)
    return text

def main():
    p=argparse.ArgumentParser();p.add_argument('--variant',choices=['shared_original','shared_adaptive','independent_adaptive','independent_vav','independent_vav_corrected'],required=True);p.add_argument('--all',action='store_true');p.add_argument('--margin',type=float,default=None);p.add_argument('--label');p.add_argument('--settings',type=Path);a=p.parse_args()
    settings=json.loads((a.settings or ROOT/'settings_soft_comfort.json').read_text());settings['schedule_clock_correction']=True
    if a.margin is not None:settings['comfort_margin']=a.margin
    label=a.label or a.variant;settingsfile=ROOT/f'recipe_{label}.json';settingsfile.write_text(json.dumps(settings,indent=2))
    c=setup(SimpleNamespace(implementation=str(DEFAULT),plant_folder=None,label=label,case='all',days=7,recovery_days=1,start='2017-08-21',settings=settingsfile,coverage=80,battery='NMC',capacity_multiplier=2))
    idf=c.output/'inputs/model.idf';idf.write_text(split_schedule(idf.read_text()))
    proto=json.loads((c.output/'protocol.json').read_text());proto.update(control_extension=a.variant,scope='Exploratory matched-week control development. Sequential RC SAT candidate plus original policies, full horizon LP scoring; not globally optimal. Separate schedules retain original values and equipment. Humidity monitored, not constrained.',comfort_margin_C=settings['comfort_margin'],simulation_input_sha256=hashlib.sha256(idf.read_bytes()).hexdigest())
    if a.variant.startswith('independent_vav'):
        shutil.copy2(ROOT/'vav_minimum_flow.json',c.output/'vav_minimum_flow.json')
        proto['minimum_flow_predictor']=json.loads((ROOT/'vav_minimum_flow.json').read_text())
    if a.variant=='independent_vav_corrected':proto['export_feedback_correction']='Reserve planned intentional export after excluding spill forced solely by the charge-power limit.'
    (c.output/'protocol.json').write_text(json.dumps(proto,indent=2))
    for case in ['conventional','hvac_mpc_greedy','coordinated_mpc'] if a.all else ['coordinated_mpc']:
        AdvancedRun(c,case,a.variant).run()
    report(c)
if __name__=='__main__':main()
