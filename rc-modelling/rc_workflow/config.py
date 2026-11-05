from dataclasses import dataclass, field, asdict
from pathlib import Path
import numpy as np

@dataclass
class Config:
    """Frozen, explicit protocol. kW, kWh/K, K and hours throughout fitting."""
    implementation: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])
    output: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1] / 'results')
    energyplus: Path = Path('C:/EnergyPlusV25-2-0/energyplus.exe')
    dt_hours: float = 1/6
    methods: tuple = ('trapezoidal', 'savgol')
    lambdas: tuple = field(default_factory=lambda: tuple([0.] + np.logspace(-6, 2, 17).tolist()))
    support_tol: float = 1e-6
    sg_window: int = 7  # 60 minutes between first and last sample at 10-min reporting
    sg_order: int = 2
    radiant_tau_hours: float = 2.
    solar_tau_hours: float = 3.
    c_bounds: tuple = (.01, 1000.)
    g_bounds: tuple = (0., 100.)
    beta_bounds: tuple = (0., 2.)
    train_months: tuple = (1, 4, 7, 10)
    train_days: tuple = (1, 14)
    validation_days: tuple = (15, 21)
    test_months: tuple = (2, 5, 8, 11)
    test_days: tuple = (15, 21)
    horizons_hours: tuple = (1, 6, 24, 72)
    selection_horizon_hours: int = 24
    selection_tolerance_C: float = .02
    # Engineering tolerance selector, not a statistical one-standard-error rule.
    def serializable(self):
        return {k: str(v) if isinstance(v, Path) else v for k,v in asdict(self).items()}

    @property
    def source_dir(self): return self.implementation / 'ep-data' / 'with-pv'

    def locate(self, suffix):
        paths=list(self.source_dir.glob('*'+suffix))
        if len(paths)!=1: raise ValueError(f'Expected one {suffix} file in {self.source_dir}; found {paths}')
        return paths[0]
