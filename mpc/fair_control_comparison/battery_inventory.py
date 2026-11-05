"""Inventory accounting at the transition from EnergyPlus warmup to reporting."""
def initial_inventory(rows, whole_experiment=False, warmup_disabled=False):
    first = rows.iloc[0]
    raw = float(first.start_soc)
    # At the first begin-timestep callback the output variable can still contain
    # the last warmup value. If the entire first interval has zero battery flow,
    # its end value establishes the settled inventory without omitting energy.
    zero_flow = abs(first.charge_DC_kWh) < 1e-9 and abs(first.discharge_DC_kWh) < 1e-9
    settled = whole_experiment and warmup_disabled and zero_flow
    return dict(initial_soc=float(first.end_soc) if settled else raw,
                raw_initial_soc=raw,
                initial_soc_basis='end_of_first_zero_flow_interval' if settled else 'begin_interval')
