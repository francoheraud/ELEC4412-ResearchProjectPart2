"""Audit BES-H prices without silently choosing an ambiguous hour-ending convention."""
from datetime import datetime
import pandas as pd
import numpy as np

def load_prices(path):
    raw=pd.read_csv(path)
    expected=['Date & Hour Ending','Hourly Price ($/kWh)']
    if list(raw.columns)!=expected:raise ValueError(f'Expected price columns {expected}')
    def parse(s):
        for fmt in ('%m/%d/%Y %H:%M','%m/%d/%Y %I:%M:%S %p','%m/%d/%Y %H:%M:%S'):
            try:return datetime.strptime(str(s).strip(),fmt)
            except ValueError:pass
        raise ValueError(f'Unrecognised BES-H date: {s}')
    times=pd.DatetimeIndex([parse(s) for s in raw.iloc[:,0]])
    price=pd.to_numeric(raw.iloc[:,1],errors='raise').to_numpy(float)
    if len(times)!=8760 or not times.is_monotonic_increasing or not np.isfinite(price).all():
        raise ValueError('Prices must contain 8760 finite, nondecreasing labelled values')
    expected_hours=pd.date_range(times.min(),times.max(),freq='h')
    missing=expected_hours.difference(times)
    frame=pd.DataFrame({'price_USD_per_kWh':price},index=times);frame.index.name='source_label_time'
    audit=dict(rows=len(frame),first_label=str(times[0]),last_label=str(times[-1]),minimum=float(price.min()),maximum=float(price.max()),
               negative_price_hours=int((price<0).sum()),units='USD/kWh as supplied; no currency or unit conversion',
               duplicate_labels=times[times.duplicated(keep=False)].astype(str).tolist(),
               missing_clock_hours=missing.astype(str).tolist(),
               ready_for_mpc=not times.has_duplicates and len(missing)==0,
               status='RC identification does not use prices; MPC alignment requires an explicit time convention and resolution of duplicate/missing clock labels.',
               caveats=['Column says hour ending but labels span 00:00-23:00; verify whether labels denote interval starts or ends.',
                        '2025 prices and typical-year weather are a scenario, not a matched historical year.',
                        'Historical realised prices are not future forecasts. Full look-ahead is perfect foresight.',
                        'Export compensation and other tariff charges are not provided.'])
    return frame,audit

def align_scenario(prices,simulation_interval_starts,convention):
    """Explicit month/day/clock-time scenario mapping, not chronological year matching.

    convention='label_is_start' or 'label_is_end'. End-labelled data must include
    the following Jan 1 midnight if a complete target year is required. No wrap,
    interpolation, DST repair, or endpoint fabrication is performed.
    """
    if convention not in ('label_is_start','label_is_end'):raise ValueError('Choose price-label convention explicitly')
    if prices.index.has_duplicates or not np.all(np.diff(prices.index.asi8)==3600e9):
        raise ValueError('Resolve duplicate/missing clock labels and timezone conventions explicitly before MPC alignment')
    idx=prices.index-(pd.Timedelta(hours=1) if convention=='label_is_end' else pd.Timedelta(0))
    # Preserve year-boundary coverage before mapping to a typical-year clock.
    dominant_year=pd.Series(prices.index.year).mode().iloc[0]
    keep=idx.year==dominant_year
    keys=idx[keep].strftime('%m-%d %H');lookup=dict(zip(keys,prices.iloc[keep,0]))
    target=pd.DatetimeIndex(simulation_interval_starts).strftime('%m-%d %H')
    missing=sorted(set(target)-set(lookup))
    if missing:raise ValueError(f'Missing price intervals after convention mapping: {missing[:8]}')
    return np.array([lookup[k] for k in target])
