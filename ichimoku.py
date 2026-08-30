"""Leakage-safe Ichimoku Kinko Hyo calculations for 24/7 markets."""
from __future__ import annotations
import pandas as pd


def ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52, displacement: int = 26) -> pd.DataFrame:
    h, l, c = df.high, df.low, df.close
    tenkan_sen = (h.rolling(tenkan, min_periods=tenkan).max() + l.rolling(tenkan, min_periods=tenkan).min()) / 2.0
    kijun_sen = (h.rolling(kijun, min_periods=kijun).max() + l.rolling(kijun, min_periods=kijun).min()) / 2.0
    span_a_raw = (tenkan_sen + kijun_sen) / 2.0
    span_b_raw = (h.rolling(senkou_b, min_periods=senkou_b).max() + l.rolling(senkou_b, min_periods=senkou_b).min()) / 2.0
    # Cloud visible at the current bar was calculated displacement bars earlier.
    cloud_a = span_a_raw.shift(displacement)
    cloud_b = span_b_raw.shift(displacement)
    cloud_top = pd.concat([cloud_a, cloud_b], axis=1).max(axis=1).where(cloud_a.notna() & cloud_b.notna())
    cloud_bottom = pd.concat([cloud_a, cloud_b], axis=1).min(axis=1).where(cloud_a.notna() & cloud_b.notna())
    # Forward cloud is calculated from information known at the current close.
    future_bull = span_a_raw > span_b_raw
    future_bear = span_a_raw < span_b_raw
    chikou_bull = c > c.shift(displacement)
    chikou_bear = c < c.shift(displacement)
    return pd.DataFrame({
        'tenkan': tenkan_sen, 'kijun': kijun_sen,
        'span_a_raw': span_a_raw, 'span_b_raw': span_b_raw,
        'cloud_a': cloud_a, 'cloud_b': cloud_b,
        'cloud_top': cloud_top, 'cloud_bottom': cloud_bottom,
        'future_bull': future_bull, 'future_bear': future_bear,
        'chikou_bull': chikou_bull, 'chikou_bear': chikou_bear,
        'bull': (c > cloud_top) & (tenkan_sen > kijun_sen) & chikou_bull & future_bull,
        'bear': (c < cloud_bottom) & (tenkan_sen < kijun_sen) & chikou_bear & future_bear,
        'cloud_thickness_atr': (cloud_top-cloud_bottom),
    }, index=df.index)
