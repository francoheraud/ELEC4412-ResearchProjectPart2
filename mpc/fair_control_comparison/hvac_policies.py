"""Finite thermostat and calibrated, time-varying SAT policy candidates."""
import numpy as np
from mpc_workflow.revised import SAT_LEVELS

def policy_candidates(f, baseline_power, baseline_cooling, profiles, c):
    upper,lower=f['upper'],f['lower'];h=len(upper)
    occupied=f['occupied'];on=f['on']>0
    # Legacy behavior is retained explicitly for controlled comparisons.
    if c.policy_family=='legacy':
        policies=[('scheduled',upper.copy()),
            ('comfort_margin',np.maximum(lower+.5,upper-c.comfort_margin*occupied)),
            ('solar_precool',np.maximum(lower+.5,upper-c.max_precooling*(f['pv']>f['base']+5)[:,None]))]
    else:
        # True predicted surplus includes baseline HVAC, not just non-HVAC load.
        surplus=f['pv']>f['base']+baseline_power+5
        pre=np.zeros_like(occupied,dtype=bool)
        look=round(c.preoccupancy_hours/c.control_hours)
        for k in range(h):
            if look:pre[k]=(~occupied[k])&np.any(occupied[k+1:min(h,k+look+1)],axis=0)
        near_occupancy=occupied|pre
        policies=[('scheduled',upper.copy()),('comfort_margin',upper-c.comfort_margin*occupied)]
        # Unoccupied precooling aims at the next occupied upper bound, rather
        # than lowering a loose night setback by an ineffectual small offset.
        next_upper=upper.copy()
        for k in range(h-1,-1,-1):
            if k+1<h:next_upper[k]=np.where(occupied[k],upper[k],next_upper[k+1])
        for amount in c.precooling_offsets_C:
            solar_mask=surplus[:,None]&near_occupancy&on[:,None]
            solar_target=np.where(occupied,upper,next_upper)-amount
            policies.append((f'solar_precool_{amount:g}',np.where(solar_mask,np.minimum(upper,solar_target),upper)))
            pre_target=np.minimum(upper,next_upper-amount)
            policies.append((f'preoccupancy_{amount:g}',np.where(pre&on[:,None],pre_target,upper)))
        policies=[(name,np.clip(sp,lower+.5,upper)) for name,sp in policies]
    if c.anticipatory_policies:
        # Separate exploratory candidates. Low marginal grid/cost periods are
        # followed by forecast occupied demand. Every plan is scored with the RC.
        net=f['base']+baseline_power-f['pv']
        marginal=c.grid_import_weight*(net>0)+c.price_weight*f['prices']/c.price_reference_USD_per_kWh
        look=max(1,round(6/c.control_hours))
        opportunity=np.zeros(h,dtype=bool)
        for k in range(h-1):
            end=min(h,k+look+1)
            opportunity[k]=on[k] and np.any(occupied[k:end]) and np.max(marginal[k+1:end])>marginal[k]+.5
        for amount in (.25,.5,1.):
            target=upper-amount
            for group in (-1,0,1,2):
                members=np.ones(upper.shape[1],dtype=bool) if group<0 else profiles['groups']==group
                mask=opportunity[:,None]&members[None,:]
                sp=np.clip(np.where(mask,target,upper),lower+.5,upper)
                policies.append((f'anticipatory_{amount:g}_group{group}',sp))
    relaxation=float(getattr(c,'occupied_relaxation_C',0.))
    if relaxation>0:
        for amount in [.5,1.,2.,3.]:
            if amount<=relaxation:
                policies.append((f'occupied_relax_{amount:g}',upper+amount*occupied))
    sats=[(f'fixed_{level:g}',np.where(on,level,12.8)) for level in SAT_LEVELS]
    if c.policy_family=='flexible' and c.allow_dynamic_sat:
        groups=profiles['groups'];capacity=profiles['group_capacity']
        utilisation=np.max(np.column_stack([baseline_cooling[:,groups==g].sum(axis=1)/max(capacity[g],1e-9) for g in range(3)]),axis=1)
        demand=np.where(utilisation<.4,15.5,np.where(utilisation<.7,14.,12.8))
        sats.append(('demand_reset',np.where(on,demand,12.8)))
        surplus=f['pv']>f['base']+baseline_power+5
        sats.append(('solar_reset',np.where(on,np.where(surplus,12.8,15.5),12.8)))
    # Identical trajectories need only be simulated once (common at night).
    result=[];seen=set()
    for name,sp in policies:
        for sat_name,schedule in sats:
            key=(sp.tobytes(),schedule.tobytes())
            if key in seen:continue
            seen.add(key);result.append((name,sat_name,sp,schedule))
    return result
