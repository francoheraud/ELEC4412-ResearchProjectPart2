import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import json,argparse
from pathlib import Path
from types import SimpleNamespace
from run import setup,report,ROOT,DEFAULT
from bess_mpc import BESSRun

def intentional_export(planned_export_ac,surplus_ac,power_dc,eta):
    """Do not preserve forecast spill imposed solely by the charge-power cap."""
    unavoidable=max(0.,surplus_ac-eta*power_dc)
    return max(0.,planned_export_ac-unavoidable)

class FeedbackRun(BESSRun):
    def begin(self,state):
        before=len(self.horizon_records);super().begin(state)
        if len(self.horizon_records)>before:
            h=self.horizon_records[-1]
            surplus=max(0.,h['pv'][0]-h['base'][0]-h['hvac_kW'][0])
            original=self.planned_export_ac
            self.planned_export_ac=intentional_export(original,surplus,self.c.power_kW,self.c.inverter_efficiency)
            self.decisions[-1]['original_export_target_AC_kW']=original
            self.decisions[-1]['intentional_export_target_AC_kW']=self.planned_export_ac

if __name__=='__main__':
    assert intentional_export(52,100,50,.96)==0
    assert intentional_export(20,30,50,.96)==20
    parser=argparse.ArgumentParser();parser.add_argument('--label',default='battery_feedback');parser.add_argument('--settings',type=Path);parser.add_argument('--all',action='store_true');args=parser.parse_args()
    c=setup(SimpleNamespace(implementation=str(DEFAULT),plant_folder=None,label=args.label,case='all',days=7,recovery_days=1,start='2017-08-21',settings=args.settings or ROOT/'settings_soft_comfort.json',coverage=80,battery='NMC',capacity_multiplier=2))
    p=c.output/'protocol.json';j=json.loads(p.read_text());j['change']='Charging feedback reserves only planned export not forced by the 50 kW charge-power limit. Predicted unavoidable spill is not a fixed export target under changing actual PV.';p.write_text(json.dumps(j,indent=2))
    for case in ['conventional','hvac_mpc_greedy','coordinated_mpc'] if args.all else ['coordinated_mpc']:FeedbackRun(c,case).run()
    report(c)
