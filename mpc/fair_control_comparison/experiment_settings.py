"""Validated notebook/CLI settings and physical NMC bank resizing."""
from dataclasses import fields
import json, math, re
from pathlib import Path

ALLOWED = {
    'export_price_factor','baseline_comfort_guard','anticipatory_policies','schedule_clock_correction',
    'price_weight','grid_import_weight','renewable_hvac_weight','hvac_only_energy_weight',
    'comfort_weight','battery_throughput_weight','setpoint_movement_weight','sat_movement_weight',
    'price_reference_USD_per_kWh','policy_family','precooling_offsets_C','preoccupancy_hours',
    'allow_dynamic_sat','max_hvac_energy_increase_fraction','comfort_margin',
    'horizon_hours','control_hours','eta_charge','eta_discharge','soc_min','soc_max',
}

def load_settings(path):
    obj = {} if path is None else json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(obj,dict): raise ValueError('Settings must be a JSON object')
    extra = set(obj)-ALLOWED
    if extra: raise ValueError('Unknown settings: '+', '.join(sorted(extra)))
    return obj

def validate(c):
    for key in ALLOWED:
        value = getattr(c,key)
        if key in ('policy_family','precooling_offsets_C','allow_dynamic_sat','baseline_comfort_guard','anticipatory_policies','schedule_clock_correction'): continue
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError(f'{key} must be finite numeric')
        if value < 0: raise ValueError(f'{key} must be nonnegative')
    if c.export_price_factor not in (0,1): raise ValueError('Use zero export credit or the same BES-H price')
    for key in ('baseline_comfort_guard','anticipatory_policies','schedule_clock_correction'):
        if not isinstance(getattr(c,key),bool):raise ValueError(key+' must be boolean')
    if c.policy_family not in ('legacy','flexible'): raise ValueError('policy_family must be legacy or flexible')
    if not isinstance(c.allow_dynamic_sat,bool): raise ValueError('allow_dynamic_sat must be boolean')
    if not 0 < c.eta_charge <= 1 or not 0 < c.eta_discharge <= 1: raise ValueError('Efficiencies must be in (0,1]')
    if not 0<=c.soc_min<c.soc_max<=.94: raise ValueError('Use 0 <= soc_min < soc_max <= native plant maximum 0.94')
    if c.soc_min<.24: raise ValueError('Planning reserve cannot be below the native plant lower limit 0.24')
    if c.price_reference_USD_per_kWh<=0: raise ValueError('Price reference must be positive')
    if c.horizon_hours<=0 or c.horizon_hours>72 or c.control_hours<=0: raise ValueError('Horizon must be in (0,72] hours')
    if abs(c.control_hours/c.dt_hours-round(c.control_hours/c.dt_hours))>1e-8: raise ValueError('Control interval must be a multiple of the measurement interval')
    if abs(c.horizon_hours/c.control_hours-round(c.horizon_hours/c.control_hours))>1e-8: raise ValueError('Horizon must contain whole control intervals')
    if c.max_hvac_energy_increase_fraction>1: raise ValueError('HVAC energy allowance must be between 0 and 1')
    offsets=c.precooling_offsets_C
    if not isinstance(offsets,(tuple,list)) or not offsets or len(offsets)>6: raise ValueError('Supply 1-6 precooling offsets')
    if any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) or not 0<x<=3 for x in offsets):
        raise ValueError('Precooling offsets must be in (0,3] C')
    if c.preoccupancy_hours>6: raise ValueError('Preoccupancy window cannot exceed 6 hours')

def objects(text):
    return [[v.strip() for v in obj.split(',')] for obj in re.sub(r'!.*','',text).split(';') if obj.strip()]

def set_common_soc_limits(text,soc_min,soc_max):
    """Set the native distribution limits to the MPC limits for every controller.

    EnergyPlus 25.2 IDD: distribution field N2=max SOC, N3=min SOC;
    their indices in the comma-split object including its type are 14 and 15.
    Preserve every other object and value, including the NMC cell parameters.
    """
    if not 0 <= soc_min < soc_max <= .94:
        raise ValueError('Invalid common SOC range')
    rows=objects(text)
    targets=[o for o in rows if o[0].lower()=='electricloadcenter:distribution'
             and len(o)>15 and o[9].strip()]
    if len(targets)!=1: raise ValueError('Expected exactly one distribution with storage')
    old=targets[0];new=old.copy();new[14]=str(soc_max);new[15]=str(soc_min)
    clean=re.sub(r'!.*',lambda m:' '*len(m.group()),text)
    matches=[m for m in re.finditer(r'[^;]+;',clean)
             if [v.strip() for v in m.group()[:-1].split(',')]==old]
    if len(matches)!=1: raise ValueError('Could not identify storage distribution')
    m=matches[0];start=m.start()+len(m.group())-len(m.group().lstrip())
    result=text[:start]+',\n    '.join(new)+';'+text[m.end():]
    if objects(result)!=[new if o==old else o for o in rows]:
        raise AssertionError('Unexpected plant edit outside native SOC limits')
    return result

def resize_nmc(text,multiplier):
    if isinstance(multiplier,bool) or not isinstance(multiplier,int) or not 1<=multiplier<=10:
        raise ValueError('Capacity multiplier must be an integer from 1 to 10')
    rows=objects(text);b=[o for o in rows if o[0].lower()=='electricloadcenter:storage:liionnmcbattery']
    if len(b)!=1: raise ValueError('Resizing requires exactly one NMC battery')
    old=b[0];new=old.copy()
    for idx in [7,10,11]: new[idx]=str(float(old[idx])*multiplier)
    new[7]=str(int(old[7])*multiplier)
    clean=re.sub(r'!.*',lambda m:' '*len(m.group()),text)
    matches=[m for m in re.finditer(r'[^;]+;',clean) if m.group().strip().split(',')[0].lower()==old[0].lower()]
    m=matches[0];start=m.start()+len(m.group())-len(m.group().lstrip())
    result=text if multiplier==1 else text[:start]+',\n    '.join(new)+';'+text[m.end():]
    # Only parallel count, mass and surface area may differ; all controls share it.
    changed=objects(result)
    expected=[new if o==old else o for o in rows] if multiplier!=1 else rows
    assert changed==expected
    dist=next(o for o in rows if o[0].lower()=='electricloadcenter:distribution')
    data=dict(battery_name=old[1],battery_type='NMC',capacity_multiplier=multiplier,
        series_cells=int(new[6]),parallel_strings=int(new[7]),
        capacity_kWh=float(new[6])*float(new[7])*float(new[17])*float(new[18])/1000,
        battery_mass_kg=float(new[10]),battery_surface_area_m2=float(new[11]),
        charge_design_kW=float(dist[16])/1000,discharge_design_kW=float(dist[18])/1000)
    if data['charge_design_kW']!=data['discharge_design_kW']: raise ValueError('Current controller requires equal charge/discharge design power')
    return result,data
