#!/usr/bin/env python3
"""Reproducible AdaptiveTrend portfolio backtest for the supplied 15m dataset."""
import argparse, json, math, os, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from adaptive_strategy import signal_and_weight

def load(path):
    d=pd.read_csv(path)
    req={"close_time","open","high","low","close","volume"}
    miss=req-set(d.columns)
    if miss: raise ValueError(f"{path}: missing {sorted(miss)}")
    return d

def run(data_dir, symbols, fee):
    frames={s:load(os.path.join(data_dir,f"{s}_15m.csv")) for s in symbols}
    idx=None
    for d in frames.values():
        x=pd.Index(d.close_time)
        idx=x if idx is None else idx.intersection(x)
    idx=pd.Index(sorted(idx))
    weights={}; returns={}
    for s,d in frames.items():
        d=d[d.close_time.isin(idx)].copy()
        _sig, w = signal_and_weight(d, target_vol=.20, max_asset_weight=1.0)  # signal unused; weight (w) drives this portfolio-level P&L
        d.index=pd.to_datetime(d.close_time,unit="ms",utc=True)
        weights[s]=w.reindex(d.index).fillna(0)
        returns[s]=d.close.pct_change().fillna(0)
    W=pd.concat(weights,axis=1).fillna(0)
    W=W.div(W.abs().sum(axis=1).clip(lower=1),axis=0)
    R=pd.concat(returns,axis=1).fillna(0)
    turnover=W.diff().abs().sum(axis=1)
    pnl=(W.shift(1)*R).sum(axis=1)-turnover*fee
    pnl=pnl.fillna(0)
    equity=(1+pnl).cumprod()
    dd=equity/equity.cummax()-1
    n=len(equity); cut=int(n*.70)
    oos=(1+pnl.iloc[cut:]).cumprod()
    dt=pd.to_datetime(frames[symbols[0]].close_time,unit="ms",utc=True)
    years=(dt.iloc[-1]-dt.iloc[0]).total_seconds()/(365.25*86400)
    oos_years=(dt.iloc[-1]-dt.iloc[int(len(dt)*.70)]).total_seconds()/(365.25*86400)
    sharpe=(pnl.mean()/pnl.std()*math.sqrt(96*365)) if pnl.std()>0 else None
    return {
      "cost_round_trip":fee,
      "full_return_pct":float((equity.iloc[-1]-1)*100),
      "full_cagr_pct":float((equity.iloc[-1]**(1/years)-1)*100),
      "max_drawdown_pct":float(dd.min()*100),
      "sharpe_annualized":float(sharpe) if sharpe is not None else None,
      "oos_30pct_return_pct":float((oos.iloc[-1]-1)*100),
      "oos_30pct_cagr_pct":float((oos.iloc[-1]**(1/oos_years)-1)*100),
      "bars":int(n)
    }

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--data-dir",default="backtest_data")
    ap.add_argument("--symbols",default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--fee",type=float,default=.0016)
    ap.add_argument("--output",default="backtest_data/adaptive_backtest_report.json")
    a=ap.parse_args()
    result=run(a.data_dir,[x.strip().upper() for x in a.symbols.split(",") if x.strip()],a.fee)
    os.makedirs(os.path.dirname(a.output) or ".",exist_ok=True)
    with open(a.output,"w") as f: json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
