import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import unittest,json
import numpy as np
from pathlib import Path
from advanced_control import simulate,adaptive_schedule,step_candidates
from bess_mpc import BESSConfig
from mpc_workflow.thermal import ThermalModel
from mpc_workflow.forecast import Forecast
from mpc_workflow.revised import rollout
from run_advanced import split_schedule

ROOT=Path(__file__).resolve().parent
class TestAdvanced(unittest.TestCase):
    def test_export_tracker_distinguishes_power_limited_spill(self):
        from test_battery_feedback import intentional_export
        # 100 kW AC surplus and 50 kW DC charging create 52 kW unavoidable spill.
        self.assertEqual(intentional_export(52,100,50,.96),0)
        self.assertEqual(intentional_export(62,100,50,.96),10)
        # An economic export choice below the power limit must remain intact.
        self.assertEqual(intentional_export(20,30,50,.96),20)
        self.assertEqual(intentional_export(0,0,50,.96),0)
    def test_common_sat_matches_original_dynamics(self):
        c=BESSConfig(**json.loads((ROOT/'settings_soft_comfort.json').read_text()))
        c.horizon_hours=4
        model=ThermalModel(ROOT/'model/thermal_model.npz');model.state=np.full(model.nx,24.)
        forecast=Forecast(ROOT/'test_fixtures/forecast_profiles.npz',c)
        f=forecast.horizon('2017-08-21 12:00',np.full(model.n,24),np.full(3,26))
        f.update(on=np.ones(8),outdoor=np.full(8,30),prices=np.full(8,.05))
        coeff=np.array(json.loads((ROOT/'test_fixtures/electrical_model.json').read_text())['coefficients'])
        for s in [12.8,14,15.5]:
            args=(model,f,np.full(model.n,24),np.full(model.n,.1),forecast.data,f['upper'])
            old=rollout(*args,np.full(8,s),coeff,c)
            new=simulate(*args,np.full((8,3),s),coeff,c)
            for a,b in zip(old,new):np.testing.assert_allclose(a,b,atol=1e-10)
        schedule=adaptive_schedule(model,f,np.full(model.n,24),np.zeros(model.n),forecast.data,f['upper'],coeff,c,np.full(3,12.8))
        self.assertEqual(schedule.shape,(8,3));self.assertTrue(np.isin(schedule,[12.8,14,15.5]).all())
    def test_schedule_only_change(self):
        text=(ROOT/'test_fixtures/model.idf').read_text()
        result=split_schedule(text)
        self.assertIn('Thesis SAT Floor 3',result)
    def test_minimum_flow_is_passive_and_only_when_on(self):
        # Three uncoupled zones/floors: no demand at a 27 C cooling target,
        # but an operating 15.5 C air system still delivers minimum-flow cooling.
        class M:
            n=3
            def discretize(self,dt):return np.eye(3),np.eye(3)*.1,np.zeros((3,1))
        from types import SimpleNamespace
        c=SimpleNamespace(control_hours=.5,vav_minimum_flow=True)
        profiles=dict(groups=np.arange(3),capacity=np.full(3,100.),group_capacity=np.full(3,100.),minimum_airflow_m3_s=np.full(3,.3))
        args=(M(),np.full(3,24.),np.zeros(1),np.zeros(3),np.full(3,20.),np.full(3,27.),30.)
        xx,p,q=step_candidates(*args,1.,np.full((1,3),15.5),profiles,np.ones((3,3,3)),c)
        expected=1.2*1.006*.3*(xx[:,:3]-15.5)
        np.testing.assert_allclose(q,expected,atol=1e-10);self.assertTrue((q>0).all())
        xx,p,q=step_candidates(*args,0.,np.full((1,3),15.5),profiles,np.ones((3,3,3)),c)
        np.testing.assert_allclose(q,0)
if __name__=='__main__':unittest.main()
