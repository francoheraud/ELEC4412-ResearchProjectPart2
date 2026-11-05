"""Physical invariants, optimizer objective, and sample alignment checks."""
import unittest
from rc_engine import *

class EngineTests(unittest.TestCase):
    def data(self):
        n=15; count=1000; t=np.arange(count)/6
        zones=np.array(['CORE_BOTTOM','CORE_MID','CORE_TOP']+[f'PERIMETER_{f}_ZN_{k}' for f in ['BOT','MID','TOP'] for k in range(1,5)])
        data=dict(zones=zones,dt_hours=np.array(1/6),C_air=np.linspace(.1,.8,n),
                  T=20+np.sin(t[:,None]/7+np.arange(n)[None,:]/3),boundaries=np.full((count,5),15.),
                  wall_prior={'reference_G_kW_K':.15},boundary_names=np.array(['OUTDOOR','P1','P2','P3','GROUND']))
        for key in ['hvac_kW','known_gain_kW','radiant_filtered_kW','solar_filtered_kW']:
            data[key]=np.zeros((count,n))
        return data

    def test_masks_and_nonduplicated_1r_outdoor(self):
        d=self.data(); local=branches(d['zones'],'local','2R1C',.5); full=branches(d['zones'],'unrestricted','2R1C',.5)
        self.assertEqual(sum(b.interzone for b in local),30); self.assertEqual(sum(b.interzone for b in full),105)
        self.assertEqual(sum(b.kind.startswith('plenum') for b in local),25)
        self.assertEqual(sum(b.kind=='plenum_lower' for b in local),10)
        simple=branches(d['zones'],'local','1R')
        self.assertEqual(sum(b.kind.startswith('outdoor') for b in simple),15)
        self.assertTrue(all(b.tau==0 for b in simple))

    def test_passivity_reciprocity_equilibrium_and_storage_count(self):
        d=self.data(); bs=branches(d['zones'],'local','2R1C',.5)
        x=np.r_[np.full(len(bs),.1),[.8,.7]]; lo,hi,m=bounds(d,bs,True,False)
        v=verify_model(d,bs,x,True,lo,hi); self.assertLess(v['max_real_eigenvalue'],0)
        A,B,Ad,Bd,C,kept=state_matrices(d,bs,x,True)
        self.assertEqual(len(C),15+30+15+10)
        np.testing.assert_allclose(C[15:],[4*x[e]*bs[e].tau for e in kept])

    def test_fitting_equations_match_network_balance(self):
        d=self.data(); bs=branches(d['zones'],'local','2R1C',.5); nb=len(bs)
        x=np.r_[np.full(nb,.1),[.8,.7]]; block=np.arange(1000)
        X,y,ids=training_arrays(d,block,bs,'savgol',True)
        A,B,_,_,C,kept=state_matrices(d,bs,x,True)
        wall=storage_traces(d,block,bs)
        derivative=savgol_filter(d['T'],7,2,deriv=1,delta=1/6,axis=0)[ids]
        state=np.column_stack([d['T'][ids],wall[ids][:,kept]])
        u=np.column_stack([np.zeros((len(ids),60)),d['boundaries'][ids]])
        rhs=state@A.T+u@B.T
        np.testing.assert_allclose((X@x-y).reshape(-1,15),d['C_air']*(derivative-rhs[:,:15]),atol=1e-10)

    def test_methods_have_identical_indices_and_free_air_equivalence(self):
        d=self.data(); bs=branches(d['zones'],'local','2R1C',.5); block=np.arange(1000)
        X,y,ids=training_arrays(d,block,bs,'savgol',True)
        Xf,yf,idsf=training_arrays(d,block,bs,'savgol',False)
        _,_,idst=training_arrays(d,block,bs,'trapezoidal',True)
        np.testing.assert_array_equal(ids,idst); np.testing.assert_array_equal(ids,idsf)
        x=np.r_[np.full(len(bs),.1),[.8,.7]]
        np.testing.assert_allclose(X@x-y,Xf@np.r_[x,d['C_air']]-yf,atol=1e-12)

    def test_sparse_objective_against_enumerated_supports(self):
        R=np.eye(4); y=np.array([.05,1.2,.4,.8]); scale=np.ones(4)
        stats=dict(R=R,y=y,scale=scale,constant=0.)
        lo=np.array([.5,.5,0.,0.]); hi=np.full(4,2.); m=2; lam=.2
        candidates=[]
        for support in [[],[0],[1],[0,1]]:
            x,_=fit_refit(stats,lo,hi,m,support,lam)
            candidates.append(np.sum((R@x-y)**2)+lam*x[:m].sum())
        x,obj,_,ok=fit_conditional(stats,lo,hi,m,lam,np.zeros(4))
        self.assertTrue(ok); self.assertAlmostEqual(obj,min(candidates),places=10)
        self.assertEqual(x[0],0.); self.assertGreaterEqual(x[1],.5)

    def test_qr_preserves_full_residual_objective(self):
        d=self.data(); bs=branches(d['zones'],'local','1R'); block=np.arange(1000)
        stats=regression(d,[block],bs,'savgol',False)
        X,y,_=training_arrays(d,block,bs,'savgol',False)
        x=np.r_[np.full(len(bs),.1),[.8,.7],d['C_air']]
        compressed=np.sum((stats['R']@(x*stats['scale'])-stats['y'])**2)+stats['constant']
        self.assertAlmostEqual(compressed,np.mean((X@x-y)**2),places=10)

    def test_storage_initialisation_is_causal(self):
        d=self.data(); bs=branches(d['zones'],'local','2R1C',.5); block=np.arange(1000)
        original=storage_traces(d,block,bs)
        d['T'][601:]+=100.
        mutated=storage_traces(d,block,bs)
        np.testing.assert_array_equal(original[:601],mutated[:601])

if __name__=='__main__': unittest.main()
