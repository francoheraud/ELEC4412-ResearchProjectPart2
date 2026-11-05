import unittest
from types import SimpleNamespace
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from rc_workflow.config import Config
from rc_workflow.model import Layout,rollout
from rc_workflow.identification import Regression,equations
from rc_workflow.evaluation import select
from rc_workflow.prices import align_scenario

class NumericalTests(unittest.TestCase):
    def test_reciprocity_and_conservation(self):
        lay=Layout(['a','b','c'],['out'],Config());theta=np.ones(lay.p)
        theta[:3]=[2,3,4];m=lay.matrices(theta,.1)
        np.testing.assert_allclose(m['L'],m['L'].T)
        np.testing.assert_allclose(m['L'].sum(axis=1),0,atol=1e-14)
        np.testing.assert_allclose(np.diag(theta[:3])@m['A'],(np.diag(theta[:3])@m['A']).T)
        self.assertLess(m['eigenvalues'].real.max(),0)
        self.assertGreaterEqual(m['Ad'].min(),-1e-14)

    def test_exact_zoh_matches_scalar_analytic(self):
        lay=Layout(['a'],['out'],Config());theta=np.array([2.,.5,0.,0.]);m=lay.matrices(theta,1)
        # HVAC=1kW, known/radiant/solar=0, outdoors=10 C. Equilibrium is 12 C.
        pred=rollout(m['Ad'],m['Bd'],np.tile([1,0,0,0,10],(8,1)),np.array([20.]))
        np.testing.assert_allclose(pred[:,0],12+8*np.exp(-.25*np.arange(9)),atol=1e-12)

    def test_penalised_qp_matches_independent_optimizer(self):
        rng=np.random.default_rng(12);lay=Layout(['a','b','c'],['out'],Config())
        a=rng.normal(size=(200,lay.p));truth=np.ones(lay.p)*.5;y=a@truth+rng.normal(size=200)*.01;lam=.2
        reg=Regression(a,y,lay);fit,diag=reg.fit(lam)
        def fun(t):return np.mean((a@t-y)**2)+lam*t[lay.gs].sum()
        result=minimize(fun,np.ones(lay.p)*.4,bounds=list(zip(lay.lower,lay.upper)),method='L-BFGS-B',options={'ftol':1e-14,'gtol':1e-8})
        self.assertAlmostEqual(fun(fit),fun(result.x),places=8)
        # QR support reduction preserves the quadratic, including normalisation.
        ca=reg.R*reg.scale*np.sqrt(lay.p);cy=reg.target*np.sqrt(lay.p)
        reduced=Regression(ca,cy,lay,(0,));direct=Regression(a,y,lay,(0,))
        np.testing.assert_allclose(reduced.fit()[0],direct.fit()[0],atol=1e-9)

    def test_preprocessing_does_not_cross_split(self):
        rng=np.random.default_rng(6);n=80;config=Config();lay=Layout(['a','b'],['out'],config)
        d=SimpleNamespace(T=rng.normal(size=(n,2)),boundaries=rng.normal(size=(n,1)),radiant=rng.normal(size=(n,2)),solar=rng.normal(size=(n,2)),base_heat=rng.normal(size=(n,2)),dt=1/6)
        for method in config.methods:
            a,b=equations(d,[np.arange(10,40)],lay,method,config)
            original=d.T.copy();d.T[40:]+=10000
            a2,b2=equations(d,[np.arange(10,40)],lay,method,config)
            np.testing.assert_array_equal(a,a2);np.testing.assert_array_equal(b,b2);d.T=original

    def test_selector_uses_validation_margin(self):
        frame=pd.DataFrame({'lambda':[0,1,2],'edges':[10,4,0],'validation_rmse_C':[.5,.51,.6]})
        self.assertEqual(select(frame,.02)['edges'],4)

    def test_price_convention_never_silently_wraps(self):
        idx=pd.date_range('2025-01-01',periods=8760,freq='h');p=pd.DataFrame({'price':np.arange(8760)},index=idx)
        target=pd.date_range('2017-01-01',periods=52560,freq='10min')
        a=align_scenario(p,target,'label_is_start');np.testing.assert_array_equal(a[:7],[0,0,0,0,0,0,1])
        with self.assertRaises(ValueError):align_scenario(p,target,'label_is_end')
        duplicate=pd.concat([p.iloc[:3],p.iloc[2:]])
        with self.assertRaises(ValueError):align_scenario(duplicate,target,'label_is_start')

if __name__=='__main__':unittest.main()
