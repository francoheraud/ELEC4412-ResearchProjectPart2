import os
os.environ['OPENBLAS_NUM_THREADS']='1'
import unittest
import numpy as np
from bess_mpc import BESSConfig,dispatch
from battery_tracking import track_export_policy

class ExportTests(unittest.TestCase):
    def config(self,**kw):
        return BESSConfig(**(dict(control_hours=1,capacity_kWh=100,power_kW=50,soc_min=.24,soc_max=.92,
             eta_charge=1,eta_discharge=1,inverter_efficiency=1,grid_import_weight=0,
             price_weight=1,price_reference_USD_per_kWh=1,battery_throughput_weight=0)|kw))
    def test_export_or_store_opportunity_cost(self):
        c=self.config();a=dispatch(np.array([0.,10.]),np.array([10.,0.]),np.array([3.,2.]),.24,c)
        self.assertAlmostEqual(a['charge'][0],0);self.assertAlmostEqual(a['export'][0],10)
        self.assertAlmostEqual(a['objective'],-10)
        b=dispatch(np.array([0.,10.]),np.array([10.,0.]),np.array([1.,2.]),.24,c)
        self.assertAlmostEqual(b['charge'][0],10);self.assertAlmostEqual(b['discharge'][1],10)
        c.export_price_factor=0
        z=dispatch(np.array([0.,10.]),np.array([10.,0.]),np.array([3.,2.]),.24,c)
        self.assertAlmostEqual(z['charge'][0],10)
    def test_objective_and_electrical_balance(self):
        c=self.config(inverter_efficiency=.96,eta_charge=.9,eta_discharge=.9,
                      grid_import_weight=10,price_reference_USD_per_kWh=.05,battery_throughput_weight=.01)
        load=np.array([5,30,50,0.]);pv=np.array([30,0,10,100.]);price=np.array([-.01,.1,.03,.06])
        a=dispatch(load,pv,price,.5,c)
        expected=10*a['grid'].sum()+np.dot(price,a['grid']-a['export'])/.05+.01*(a['charge']+a['discharge']).sum()
        self.assertAlmostEqual(a['objective'],expected)
        np.testing.assert_allclose(a['grid']-a['export'],load-pv+.96*(a['charge']-a['discharge']),atol=1e-8)
        np.testing.assert_allclose(np.diff(np.r_[50,a['energy']]),.9*a['charge']-a['discharge']/.9,atol=1e-8)
        self.assertFalse(np.any((a['charge']>1e-8)&(a['discharge']>1e-8)))
    def test_tracking_obeys_export_choice_and_limits(self):
        # PV 30 DC, load 9.6 AC -> 20 DC surplus. Reserve 9.6 AC for export.
        self.assertEqual(track_export_policy(0,9.6,30,9.6,.5,50,.96,.24,.92),(10,0))
        self.assertEqual(track_export_policy(0,19.2,30,9.6,.5,50,.96,.24,.92),(0,0))
        self.assertEqual(track_export_policy(0,0,30,9.6,.5,50,.96,.24,.92),(20,0))
        self.assertEqual(track_export_policy(50,0,0,9.6,.5,50,.96,.24,.92),(0,10))
        self.assertEqual(track_export_policy(50,0,0,9.6,.24,50,.96,.24,.92),(0,0))

if __name__=='__main__':unittest.main()
