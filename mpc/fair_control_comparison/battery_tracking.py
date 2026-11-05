"""Measured-surplus charging beneath the unchanged supervisory dispatch LP."""
import math


def track_surplus(planned_charge, planned_discharge, pv_dc, load_ac, soc,
                  power_limit, inverter_efficiency, soc_min, soc_max):
    """Return DC requests in kW from current plant signals.

    During surplus, capture available PV within the native power/SOC limits.
    During deficit, retain the MPC discharge request and cap it to demand.
    The native NMC plant enforces its voltage and SOC-dependent limitations.
    No future measurements or grid charging enter this correction.
    """
    values=(planned_charge, planned_discharge, pv_dc, load_ac, soc,
            power_limit, inverter_efficiency, soc_min, soc_max)
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError('Non-finite battery tracking input')
    if power_limit <= 0 or not 0 < inverter_efficiency <= 1:
        raise ValueError('Invalid battery power or inverter efficiency')
    if not 0 <= soc_min < soc_max <= 1:
        raise ValueError('Invalid SOC limits')
    net_dc=max(0.,pv_dc)-max(0.,load_ac)/inverter_efficiency
    if net_dc > 0:
        charge=min(power_limit,net_dc) if soc < soc_max else 0.
        return charge,0.
    discharge=min(power_limit,max(0.,planned_discharge),-net_dc) if soc > soc_min else 0.
    return 0.,discharge


def track_export_policy(planned_discharge,planned_export_ac,pv_dc,load_ac,soc,
                        power_limit,inverter_efficiency,soc_min,soc_max):
    """Track an export target in AC kW using DC battery actuators.

    Reserve the planned exported PV before charging the measured remainder.
    Zero export target recovers measured-surplus charging. With unexpected
    surplus, store the excess above the target; with a shortfall, reduce charge.
    Battery discharge remains clipped to actual demand; no battery-to-grid sale.
    """
    if not math.isfinite(planned_export_ac) or planned_export_ac < -1e-7:
        raise ValueError('Invalid planned export')
    charge,discharge=track_surplus(0,planned_discharge,pv_dc,load_ac,soc,
                                  power_limit,inverter_efficiency,soc_min,soc_max)
    surplus=max(0,pv_dc-max(0,load_ac)/inverter_efficiency)
    charge=min(charge,max(0,surplus-max(0,planned_export_ac)/inverter_efficiency))
    return charge,discharge
