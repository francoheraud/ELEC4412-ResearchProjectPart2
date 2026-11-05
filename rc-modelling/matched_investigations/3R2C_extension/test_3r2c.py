"""Checks specific to the two-storage-state branch extension."""
import test_engine
from rc_engine import *
import unittest

class ThreeRTests(unittest.TestCase):
    def data(self): return test_engine.EngineTests().data()

    def test_balance_and_passivity_for_both_differentiation_methods(self):
        d=self.data(); bs=branches(d['zones'],'local','3R2C',.5)
        x=np.r_[np.full(len(bs),.1),[.8,.7]]; block=np.arange(1000)
        lo,hi,m=bounds(d,bs,True,False); verify_model(d,bs,x,True,lo,hi)
        A,B,Ad,Bd,C,kept=state_matrices(d,bs,x,True)
        self.assertEqual(len(C),15+2*(30+15+10))
        self.assertEqual(complexity(d,bs,x,True)['states'],len(C))
        wall=storage_traces(d,block,bs); columns=state_trace_columns(bs,kept)
        for method in METHODS:
            X,y,ids=training_arrays(d,block,bs,method,True)
            if method=='savgol':
                state=np.column_stack([d['T'][ids],wall[ids][:,columns]])
                bd=d['boundaries'][ids]
                deriv=savgol_filter(d['T'],7,2,deriv=1,delta=1/6,axis=0)[ids]
            else:
                state=np.column_stack([(d['T'][ids]+d['T'][ids+1])/2,(wall[ids][:,columns]+wall[ids+1][:,columns])/2])
                bd=(d['boundaries'][ids]+d['boundaries'][ids+1])/2
                deriv=(d['T'][ids+1]-d['T'][ids])/(1/6)
            u=np.column_stack([np.zeros((len(ids),60)),bd])
            rhs=state@A.T+u@B.T
            np.testing.assert_allclose((X@x-y).reshape(-1,15),d['C_air']*(deriv-rhs[:,:15]),atol=1e-10)

    def test_foh_reconstruction_against_independent_matrix_exponential(self):
        d=self.data(); tau=.5; dt=1/6
        bs=[Branch(0,1,'interzone',tau,2),Branch(2,0,'outdoor_storage',12.,2)]
        block=np.arange(100)
        traces=storage_traces(d,block,bs)
        for e,b in enumerate(bs):
            a=3/(2*b.tau); A=a*np.array([[-2.,1.],[1.,-2.]])
            # Augmented states [wall(2), endpoint(2), endpoint slope(2)].
            M=np.zeros((6,6)); M[:2,:2]=A; M[:2,2:4]=a*np.eye(2); M[2:4,4:]=np.eye(2)
            F=expm(dt*M)
            u=np.column_stack([d['T'][block,b.i],d['T'][block,b.j] if b.interzone else d['boundaries'][block,b.j]])
            w=np.linalg.solve(-A,a*u[0]); reference=[w]
            for k in range(len(block)-1):
                w=(F@np.r_[w,u[k],(u[k+1]-u[k])/dt])[:2]; reference.append(w)
            np.testing.assert_allclose(traces[:,[e,len(bs)+e]],reference,atol=1e-11)
        changed=storage_traces(d,block[:60],bs)
        np.testing.assert_allclose(changed,traces[:60],atol=0)

    def test_total_RC_and_steady_conductance_preserved(self):
        d=self.data(); g=.2; tau=.5; expected=[]
        for nodes in [1,2]:
            bs=[Branch(0,1,'interzone',tau,nodes)]
            x=np.array([g,0.,0.]); A,B,_,_,C,kept=state_matrices(d,bs,x,True)
            K=-C[:,None]*A
            self.assertAlmostEqual(C[15:].sum(),4*g*tau)
            Kzz=K[:15,:15]; Kzw=K[:15,15:]; Kww=K[15:,15:]
            effective=Kzz-Kzw@np.linalg.solve(Kww,Kzw.T)
            self.assertAlmostEqual(effective[0,1],-g)
            expected.append(effective)
            if nodes==2:
                np.testing.assert_allclose(np.sort(-1/np.linalg.eigvals(A[15:,15:])),[2*tau/9,2*tau/3])
        np.testing.assert_allclose(*expected,atol=1e-12)

    def test_frozen_baseline_matrices_reproduced(self):
        here=Path(__file__).resolve().parent
        d=load_inputs(DEFAULT_IMPLEMENTATION,here)
        for name in ['local_1R_wall','local_2R1C_wall']:
            cfg=case_definitions(d)[name]
            selections=json.loads((here/'cases'/name/'selection.json').read_text())
            for rule,row in selections.items():
                saved=np.load(here/'cases'/name/f'{rule}.npz')
                bs=branches(d['zones'],cfg['mask'],cfg['order'],row['tau_interzone_hours'])
                A,B,Ad,Bd,C,kept=state_matrices(d,bs,saved['theta'],True)
                for key,value in [('A',A),('B',B),('Ad',Ad),('Bd',Bd),('C',C)]:
                    np.testing.assert_allclose(value,saved[key],atol=1e-12,rtol=1e-12)

if __name__=='__main__': unittest.main()
