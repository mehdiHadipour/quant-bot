"""Small research metrics used by the backtest/reporting layer."""
from __future__ import annotations

def expectancy(r_values):
    vals=[float(x) for x in r_values]
    return sum(vals)/len(vals) if vals else 0.0

def profit_factor(r_values):
    vals=[float(x) for x in r_values]
    gains=sum(x for x in vals if x>0); losses=sum(-x for x in vals if x<0)
    return gains/losses if losses else (float('inf') if gains else 0.0)

def max_drawdown(r_values):
    equity=peak=0.0; dd=0.0
    for x in r_values:
        equity += float(x); peak=max(peak,equity); dd=max(dd,peak-equity)
    return dd

def net_r_after_costs(r_values, fee_r=0.0, slippage_r=0.0):
    vals=[float(x) for x in r_values]
    return sum(vals)-len(vals)*(float(fee_r)+float(slippage_r))

def walk_forward_splits(n, train_size, test_size, step=None):
    step=step or test_size; out=[]; start=0
    while start+train_size+test_size<=n:
        out.append((range(start,start+train_size),range(start+train_size,start+train_size+test_size)))
        start += step
    return out
