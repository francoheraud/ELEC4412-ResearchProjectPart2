"""Full-state RC propagation and causal hidden-temperature reconstruction.

Zone temperatures are measured outputs; branch temperatures remain states.
Units: hours, kW, kWh/K. No RC parameters are updated online.
"""
import json
from pathlib import Path
import numpy as np
from scipy.linalg import expm


class ThermalModel:
    def __init__(self, path):
        path = Path(path)
        with np.load(path, allow_pickle=False) as data:
            self.A = data['A'].copy()
            self.B = data['B'].copy()
            self.C = data['C'].copy()
            self.zones = data['zones'].tolist()
            self.theta = data['theta'].copy()
            self.storage_ids = data['storage_branch_indices'].copy()
            self.boundary_names = data['boundary_names'].tolist()
        self.n = len(self.zones)
        self.nx = len(self.A)
        self.Bq = self.B[:, :self.n]
        self.Bd = self.B[:, self.n:]
        self.output_matrix = np.eye(self.nx)[:self.n]
        self.branches = json.loads((path.parent/'best_accuracy_branches.json').read_text())
        self.storage = [self.branches[int(k)] for k in self.storage_ids]
        self.tau = np.array([b['tau'] for b in self.storage])
        self.state = None
        self.cache = {}
        self.initialisation = None
        self.history = None
        if (path.parent/'past_measurements.npz').exists():
            with np.load(path.parent/'past_measurements.npz', allow_pickle=False) as h:
                self.history = {k:h[k].copy() for k in h.files}
        assert self.A.shape == (self.nx, self.nx)
        assert self.B.shape == (self.nx, 4*self.n+5)
        assert self.nx == self.n+len(self.storage)
        assert np.all(self.C > 0) and np.all(self.tau > 0)

    def discretize(self, dt):
        if dt not in self.cache:
            nx, nu = self.B.shape
            aug = np.zeros((nx+nu, nx+nu))
            aug[:nx, :nx] = self.A
            aug[:nx, nx:] = self.B
            e = expm(aug*dt)
            self.cache[dt] = (e[:nx, :nx], e[:nx, nx:nx+self.n], e[:nx, nx+self.n:])
        return self.cache[dt]

    def midpoints(self, temperatures, boundaries):
        return np.array([(temperatures[b['i']] +
            (temperatures[b['j']] if b['kind']=='interzone' else boundaries[b['j']]))/2
            for b in self.storage])

    def filter_storage(self, stored, mid_start, mid_end, dt):
        # Exact dz/dt=(midpoint(t)-z)/tau solution for linear measured endpoints.
        decay = np.exp(-dt/self.tau)
        end_weight = 1-(1-decay)*self.tau/dt
        start_weight = 1-decay-end_weight
        return decay*stored + start_weight*mid_start + end_weight*mid_end

    def observe_begin(self, time, temperatures, boundaries):
        if self.state is None:
            mids = self.midpoints(temperatures, boundaries)
            stored = mids.copy()
            used = 0
            last = None
            if self.history is not None:
                h = self.history
                indices = np.flatnonzero(h['time'].astype('datetime64[ns]') < np.datetime64(time))
                if len(indices):
                    previous_mid = self.midpoints(h['T'][indices[0]], h['boundaries'][indices[0]])
                    stored = previous_mid.copy()
                    last = h['time'][indices[0]]
                    for idx in indices[1:]:
                        current_mid = self.midpoints(h['T'][idx], h['boundaries'][idx])
                        elapsed = float((np.datetime64(h['time'][idx])-np.datetime64(last))/np.timedelta64(1,'h'))
                        stored = self.filter_storage(stored, previous_mid, current_mid, elapsed)
                        previous_mid = current_mid
                        last = h['time'][idx]
                    elapsed = float((np.datetime64(time)-np.datetime64(last))/np.timedelta64(1,'h'))
                    stored = self.filter_storage(stored, previous_mid, mids, elapsed)
                    used = len(indices)
            self.state = np.r_[temperatures, stored]
            self.initialisation = dict(time=str(time), past_samples=used,
                last_past_measurement=None if last is None else str(last),
                method='Causal endpoint filtering; live conditioning follows; no future measurements')
        else:
            self.state[:self.n] = temperatures

    def observe_end(self, start_temperatures, end_temperatures, start_boundaries, end_boundaries, dt):
        stored = self.filter_storage(self.state[self.n:],
            self.midpoints(start_temperatures,start_boundaries),
            self.midpoints(end_temperatures,end_boundaries),dt)
        self.state = np.r_[end_temperatures,stored]
        if not np.isfinite(self.state).all():
            raise RuntimeError('Nonfinite thermal state estimate')


class DisturbanceObserver:
    """Original bounded filtered heat bias, projected onto measured zone outputs."""
    def __init__(self, n, gain=.2, limit=20.):
        self.d = np.zeros(n)
        self.gain = gain
        self.limit = limit

    def update(self, previous, current, actual_heat, forecast_inputs, matrices):
        A, Bq, Bd = matrices
        predicted_state = A@previous + Bq@(actual_heat+self.d) + Bd@forecast_inputs
        predicted = predicted_state[:len(current)]
        innovation = current-predicted
        increment = np.linalg.lstsq(Bq[:len(current)], innovation, rcond=1e-10)[0]
        self.d = np.clip(self.d+self.gain*increment, -self.limit, self.limit)
        return predicted, innovation
