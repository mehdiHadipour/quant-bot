#!/usr/bin/env python3
"""Download current WEEX TradFi history and run the same leakage-safe engine.

IMPORTANT: downloaded candidates are research-only. No symbol is promoted to
live trading by this script. Approval requires the explicit policy in
scripts/promote_tradfi.py after an out-of-sample study.
"""
from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asset_universe import tradfi_candidates
from weex_data_engine import fetch_history
from ict_full_backtest import run

DATA = ROOT / "backtest_data" / "weex_tradfi"
REPORT = ROOT / "WEEX_TRADFI_BACKTEST_RESULTS.csv"


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    candidates = [x for x in tradfi_candidates() if x.get("api_verified")]
    rows = []
    for item in candidates:
        sym = item["symbol"]
        p = DATA / f"{sym}_15m.csv"
        df = fetch_history(sym, "15m", days=int(os.getenv("TRADFI_BACKTEST_DAYS", "90")))
        if df is None or len(df) < 600:
            print(f"{sym}: INSUFFICIENT_DATA ({0 if df is None else len(df)})")
            continue
        df.to_csv(p, index=False)
        df["dt"] = __import__("pandas").to_datetime(df.open_time, unit="ms", utc=True)
        trades = run(df, strict=True, vp_lookback=60, vp_bins=40, asset_class=item.get('asset_class', 'STOCK'))
        if trades.empty:
            print(f"{sym}: 0 trades")
            continue
        trades.insert(0, "symbol", sym)
        rows.append(trades)
        print(f"{sym}: {len(trades)} trades, NetR={trades.r_multiple.sum():.2f}")
    if rows:
        import pandas as pd
        out = pd.concat(rows, ignore_index=True).sort_values("entry_time")
        out.to_csv(REPORT, index=False)
        summary = out.groupby("symbol").agg(trades=("r_multiple", "size"), net_r=("r_multiple", "sum"), wins=("result", lambda x: int((x == "WIN").sum())))
        summary["win_rate"] = summary["wins"] / summary["trades"]
        summary.to_csv(ROOT / "WEEX_TRADFI_BY_SYMBOL.csv")
    else:
        REPORT.write_text("NO_APPROVABLE_TRADFI_TRADES\n", encoding="utf-8")


if __name__ == "__main__":
    main()
