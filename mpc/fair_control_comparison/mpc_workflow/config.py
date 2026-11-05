from dataclasses import dataclass,field,asdict
from pathlib import Path
import os

@dataclass
class Config:
    implementation: Path=field(default_factory=lambda:Path(__file__).resolve().parents[3])
    output: Path=field(default_factory=lambda:Path(__file__).resolve().parents[1]/'results')
    energyplus_root: Path=field(default_factory=lambda:Path(os.environ.get('ENERGYPLUS_ROOT','C:/EnergyPlusV25-2-0')))
    start: str='2017-08-14'
    days: int=7
    preconditioning_days: int=1
    recovery_days: int=1
    dt_hours: float=1/6
    control_hours: float=.5
    horizon_hours: float=12.
    comfort_weight: float=100.
    movement_weight: float=.25
    renewable_hvac_weight: float=.10
    observer_gain: float=.2
    disturbance_limit_kW: float=20.
    max_setpoint_change_C: float=1.
    seed: int=20261003
    scenarios: tuple=('conventional','reduced_energy','reduced_renewable','dense_renewable','reduced_renewable_no_correction')

    @property
    def rc(self):return self.output/'thermal_model'
    @property
    def source(self):return self.implementation/'ep-data'/'with-pv'
    def serializable(self):return {k:str(v) if isinstance(v,Path) else v for k,v in asdict(self).items()}
