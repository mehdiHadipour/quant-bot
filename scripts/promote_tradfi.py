#!/usr/bin/env python3
"""Promote only statistically acceptable TradFi symbols/directions.

Policy: >=30 trades per symbol for overall approval, PF>=1.25, NetR>0,
MaxDD<=8R, WinRate>=45%. Directional policy requires >=8 trades; negative
expectancy becomes STRICT and materially negative PF becomes BLOCK.
"""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INFILE = ROOT / "WEEX_TRADFI_BACKTEST_RESULTS.csv"
OUT = ROOT / "state" / "tradfi_approval.json"


def pf(s):
    pos = s[s > 0].sum(); neg = -s[s < 0].sum()
    return float(pos / neg) if neg else (99.0 if pos else 0.0)


def main():
    if not INFILE.exists():
        raise SystemExit("No WEEX_TRADFI_BACKTEST_RESULTS.csv; run scripts/weex_tradfi_backtest.py first.")
    df = pd.read_csv(INFILE)
    approved=[]; policies={}
    # Defensive guard: if the backtest produced zero rows (or, from an
    # older run, still has the legacy non-CSV placeholder), there's no
    # "symbol" column to group by. That's a normal "nothing to approve
    # this run" outcome, not an error — write an empty approval file
    # instead of letting df.groupby("symbol") raise KeyError: 'symbol'.
    if df.empty or "symbol" not in df.columns:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"approved_symbols": [], "policies": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"approved_symbols": [], "count": 0}, ensure_ascii=False))
        return
    for sym,g in df.groupby("symbol"):
        r=pd.to_numeric(g.r_multiple, errors="coerce").dropna()
        eq=r.cumsum(); dd=float((eq.cummax()-eq).max()) if len(r) else 0.0
        overall=pf(r); wr=float((r>0).mean()) if len(r) else 0.0
        if len(r)>=30 and overall>=1.25 and r.sum()>0 and dd<=8 and wr>=0.45:
            approved.append(sym)
        policies[sym]={"trades":int(len(r)),"net_r":float(r.sum()),"pf":overall,"win_rate":wr,"max_dd_r":dd}
        for direction in ("BUY","SELL"):
            d=g[g.direction.eq(direction)]; rr=pd.to_numeric(d.r_multiple, errors="coerce").dropna()
            if len(rr)>=8:
                dpf=pf(rr); dnet=float(rr.sum()); level="BLOCK" if dpf<0.90 and dnet<0 else "STRICT" if dpf<1.05 or dnet<0 else "NORMAL"
            else:
                level="UNPROVEN"
                dpf=None; dnet=float(rr.sum()) if len(rr) else 0.0
            policies[sym][direction]={"trades":int(len(rr)),"net_r":dnet,"pf":dpf,"level":level}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"approved_symbols":approved,"policies":policies},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"approved_symbols":approved,"count":len(approved)},ensure_ascii=False))

if __name__ == "__main__": main()
