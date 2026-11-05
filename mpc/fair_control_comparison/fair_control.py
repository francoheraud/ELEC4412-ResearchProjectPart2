"""Matched HVAC permissions, with no forecasts used by rule-based control."""
import time
import numpy as np
import pandas as pd
from advanced_control import AdvancedRun
from mpc_workflow.forecast import Forecast
from mpc_workflow.runtime import CoupledRun
from mpc_workflow.revised import scheduled_on

SAT_CHOICES = np.array([12.8, 14., 15.5, 17., 18.])


class CommonBoundsForecast(Forecast):
    """Apply a declared experimental upper bound to ALL controllers and metrics.

    The original bound is retained as a second reporting reference. No heat gain,
    weather, occupancy, hardware, or RC coefficient is changed by this class.
    """
    def at(self, t):
        info = super().at(t)
        info['original_upper'] = info['upper'].copy()
        active = (pd.Timestamp(self.config.start) <= pd.Timestamp(t) <
                  pd.Timestamp(self.config.start) + pd.Timedelta(days=self.config.days))
        offset = self.config.common_upper_offset_C if active else 0.
        info['upper'] = info['upper'] + offset * (info['occupancy'] > .01)
        return info


def reactive_sat(previous, temperatures, targets, on):
    """Thirty-minute, one-level trim/respond reset using CURRENT errors only.

    Increase SAT if the warmest zone is <= target +0.05 K; decrease if it is
    > target +0.20 K; otherwise hold. This is a documented study rule, not a
    claim of compliance with a named HVAC control standard.
    """
    if not on:
        return 12.8
    i = int(np.argmin(abs(SAT_CHOICES - previous)))
    error = float(np.max(np.asarray(temperatures) - targets))
    if error > .20:
        i = max(0, i - 1)
    elif error <= .05:
        i = min(len(SAT_CHOICES) - 1, i + 1)
    return float(SAT_CHOICES[i])


class MatchedRun(AdvancedRun):
    def __init__(self, config, controller):
        self.controller = controller
        scenario = 'coordinated_mpc' if controller == 'coordinated' else 'hvac_mpc_greedy'
        super().__init__(config, scenario, 'shared_vav_corrected')
        self.bound_rows = []

    def begin(self, state):
        if self.controller not in ('reactive', 'fixed18'):
            super().begin(state)
            return
        old_last = self.last_control_time
        name = self.scenario
        self.scenario = 'conventional'
        CoupledRun.begin(self, state)
        self.scenario = name
        self.component_energy[:] = 0.
        self.battery_integral[:] = 0.
        self.start_soc = self.ex.get_variable_value(state, self.bh['soc'])
        self.battery_active = False
        active = (pd.Timestamp(self.c.start) <= self.zone_begin_time <
                  pd.Timestamp(self.c.start) + pd.Timedelta(days=self.c.days))
        self.active = bool(active)
        if not active:
            self.sats[:] = 12.8
            self.sat = 12.8
            return
        self.last_control_time = old_last
        info = self.forecast.at(self.zone_begin_time)
        self.command = info['upper'].copy()
        if old_last is not None and (self.zone_begin_time-old_last).total_seconds() < self.c.control_hours*3600-1:
            return
        started = time.perf_counter()
        dst = float(self.ex.daylight_savings_time_indicator(state))
        on = bool(scheduled_on(self.zone_begin_time + pd.Timedelta(hours=dst)))
        sat = (18. if on else 12.8) if self.controller == 'fixed18' else reactive_sat(
            self.sat, self.current_temperature, self.command, on)
        self.sats[:] = sat
        self.sat = sat
        self.planned_cooling = np.zeros(self.model.n)
        self.last_control_time = self.zone_begin_time
        self.decisions.append(dict(time=str(self.zone_begin_time), policy=self.controller,
            **{f'supply_floor{g+1}_C': sat for g in range(3)},
            measured_worst_error_K=float(np.max(self.current_temperature-self.command)),
            solve_seconds=time.perf_counter()-started))

    def actuate(self, state):
        # Identical actuator guard for every controller, including schedule edges.
        if getattr(self, 'active', False):
            info = self.forecast.at(self.zone_begin_time)
            self.command = np.clip(self.command, info['lower']+.5, info['upper'])
        super().actuate(state)

    def end(self, state):
        super().end(state)
        info = self.forecast.at(self.zone_begin_time)
        for row, old, new in zip(self.zone_rows[-self.model.n:], info['original_upper'], info['upper']):
            row['original_upper_C'] = float(old)
            row['common_upper_C'] = float(new)

