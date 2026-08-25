
"""V31 AdaptiveTrend strategy.
Uses only information available before each 15m return:
- 4h EMA(6/18) directional trend
- 30-day realized-volatility targeting
- gross exposure normalization <= 1.0x
"""
from __future__ import annotations
import pandas as pd
import numpy as np

def signal_and_weight(df: pd.DataFrame, target_vol=0.20, max_asset_weight=1.0):
    d=df.copy()
    d.index=pd.to_datetime(d["close_time"],unit="ms",utc=True)
    h=d[["close"]].resample("4h").last()
    fast=h["close"].ewm(span=6,adjust=False).mean()
    slow=h["close"].ewm(span=18,adjust=False).mean()
    signal=np.sign(fast-slow).reindex(d.index,method="ffill").fillna(0.0)
    rv=d["close"].pct_change().rolling(96*30).std()*np.sqrt(96*365)
    weight=(target_vol/rv).clip(upper=max_asset_weight).fillna(0.0)*signal
    return signal, weight
