from pathlib import Path
import json, math
import pandas as pd
from adaptive_strategy import signal_and_weight

def load(path):
    d=pd.read_csv(path); d.index=pd.to_datetime(d.close_time,unit='ms',utc=True); return d

def run(data_dir='backtest_data', fee=0.0008):
    files=sorted(Path(data_dir).glob('*_15m.csv'))
    if len(files)<2: raise ValueError('Need at least 2 *_15m.csv files')
    frames={p.stem.rsplit('_',1)[0]:load(p) for p in files}
    idx=None
    for d in frames.values(): idx=d.index if idx is None else idx.intersection(d.index)
    weights={}; returns={}
    for s,d in frames.items():
        d=d.loc[idx].copy(); _,w=signal_and_weight(d); weights[s]=w; returns[s]=d.close.pct_change().fillna(0)
    W=pd.concat(weights,axis=1).fillna(0); W=W.div(W.abs().sum(axis=1).clip(lower=1),axis=0)
    R=pd.concat(returns,axis=1).fillna(0); turnover=W.diff().abs().sum(axis=1)
    pnl=(W.shift(1)*R).sum(axis=1)-turnover*fee; eq=(1+pnl).cumprod(); dd=(eq/eq.cummax()-1).min()
    sh=math.sqrt(96*365)*pnl.mean()/pnl.std() if pnl.std()>0 else 0
    return {'symbols':list(frames),'return_pct':float((eq.iloc[-1]-1)*100),'max_drawdown_pct':float(dd*100),'sharpe_annualized':float(sh),'observations':len(eq),'cost_round_trip':fee*2}
if __name__=='__main__':
    r=run(); print(json.dumps(r,indent=2))
