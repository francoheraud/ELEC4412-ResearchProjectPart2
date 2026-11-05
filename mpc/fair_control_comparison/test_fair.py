import unittest
from types import SimpleNamespace
import numpy as np
import pandas as pd
from fair_control import CommonBoundsForecast, reactive_sat, SAT_CHOICES
from hvac_policies import policy_candidates

class FairTests(unittest.TestCase):
    def test_reactive_current_error_and_limits(self):
        self.assertEqual(reactive_sat(15.5,np.array([24.3,24.]),np.array([24.,24.]),True),14.)
        self.assertEqual(reactive_sat(15.5,np.array([24.,23.]),np.array([24.,24.]),True),17.)
        self.assertEqual(reactive_sat(15.5,np.array([24.1]),np.array([24.]),True),15.5)
        self.assertEqual(reactive_sat(18.,np.array([22.]),np.array([24.]),True),18.)
        self.assertEqual(reactive_sat(12.8,np.array([30.]),np.array([24.]),True),12.8)
        self.assertEqual(reactive_sat(18.,np.array([30.]),np.array([24.]),False),12.8)

    def test_common_bounds_preserve_input_and_recovery(self):
        f=CommonBoundsForecast.__new__(CommonBoundsForecast)
        f.config=SimpleNamespace(start='2017-08-21',days=7,common_upper_offset_C=3.)
        f.data=dict(setpoints=np.array([[[21.,24.],[15.6,26.7]]]),occupancy=np.array([[1.,0.]]),pv_kW=np.array([0.]),non_hvac_kW=np.array([1.]))
        f.index=lambda t:0
        inside=f.at(pd.Timestamp('2017-08-21'))
        np.testing.assert_equal(inside['upper'],[27.,26.7])
        np.testing.assert_equal(inside['original_upper'],[24.,26.7])
        np.testing.assert_equal(f.data['setpoints'][0,:,1],[24.,26.7])
        np.testing.assert_equal(f.at(pd.Timestamp('2017-08-28'))['upper'],[24.,26.7])

    def test_all_predictive_commands_inside_common_bounds(self):
        f=dict(upper=np.array([[27.,29.7],[26.7,26.7]]),lower=np.ones((2,2))*21,
            occupied=np.array([[True,True],[False,False]]),on=np.ones(2),pv=np.array([10.,0.]),base=np.ones(2))
        c=SimpleNamespace(policy_family='flexible',preoccupancy_hours=2,control_hours=.5,comfort_margin=0.,
            precooling_offsets_C=[.5,1.,1.5],anticipatory_policies=False,occupied_relaxation_C=0.,allow_dynamic_sat=False)
        for _,_,sp,_ in policy_candidates(f,np.ones(2),np.zeros((2,2)),{},c):
            self.assertTrue(np.all(sp<=f['upper']))
            self.assertTrue(np.all(sp>=f['lower']+.5))

if __name__=='__main__':unittest.main()
