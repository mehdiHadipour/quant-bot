
"""Minimal event-safe portfolio backtest engine for V31."""
import pandas as pd
from adaptive_strategy import signal_and_weight

def load_csv(path):
    d=pd.read_csv(path)
    required={"close_time","open","high","low","close","volume"}
    missing=required-set(d.columns)
    if missing: raise ValueError(f"missing columns: {sorted(missing)}")
    return d

def run(files, fee=0.0008, target_vol=0.20, max_gross=1.0):
    frames={s:load_csv(p) for s,p in files.items()}
    idx=None; weights={}; returns={}
    for s,d in frames.items():
        d=d.copy()
        d.index=pd.to_datetime(d.close_time,unit="ms",utc=True)
        if idx is None: idx=d.index
        else: idx=idx.intersection(d.index)
    for s,d in frames.items():
        d=d.loc[idx]
        _sig, w = signal_and_weight(d, target_vol, max_gross)  # signal itself unused; weight (w) drives this portfolio-level P&L
        weights[s]=w
        returns[s]=d.close.pct_change().fillna(0)
    W=pd.concat(weights,axis=1).fillna(0)
    W=W.div(W.abs().sum(axis=1).clip(lower=1),axis=0)
    R=pd.concat(returns,axis=1).fillna(0)
    turnover=W.diff().abs().sum(axis=1)
    pnl=(W.shift(1)*R).sum(axis=1)-turnover*fee
    equity=(1+pnl).cumprod()
    return pnl,equity,W
