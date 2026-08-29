"""Regression test for run_backtest.py's bounded-lookback-window fix.

Two bugs were found together while diagnosing a real 41+ minute backtest
run that got killed by the job timeout:

1. run_backtest.py fed analyze_market() the ENTIRE growing history at
   every tick (df.iloc[:idx+1], with idx climbing into the thousands),
   so every indicator was recomputed over an ever-larger series each
   time -- O(N^2) total work for a single symbol's walk.

2. Bounding that slice to a fixed trailing window (matching what the
   live bot ever actually sees) fixed the performance problem, but the
   resulting slice's row labels were no longer 0-based/contiguous-from-
   start once the window started sliding past the beginning of the
   series -- which broke detect_rsi_divergence's .loc-based lookups
   with a KeyError the instant the walk went past LOOKBACK_CANDLES rows.

This test builds more than LOOKBACK_CANDLES rows of history specifically
so the lookback window slides at least once, and confirms the walk
completes without crashing.
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

if "ta" not in sys.modules:
    ta = types.ModuleType("ta")
    trend = types.ModuleType("ta.trend")
    momentum = types.ModuleType("ta.momentum")
    volatility = types.ModuleType("ta.volatility")

    class _FakeSeriesIndicator:
        def __init__(self, series=None, close=None, window=14, **k):
            self._series = series if series is not None else close

        def ema_indicator(self):
            return self._series.rolling(3, min_periods=1).mean()

        def rsi(self):
            import numpy.random as npr
            return pd.Series(npr.default_rng(1).uniform(40, 60, len(self._series)), index=self._series.index)

        def bollinger_pband(self):
            import numpy.random as npr
            return pd.Series(npr.default_rng(2).uniform(0, 1, len(self._series)), index=self._series.index)

    class _FakeMACD:
        def __init__(self, close=None, series=None, **k):
            self._series = close if close is not None else series

        def macd(self):
            import numpy.random as npr
            return pd.Series(npr.default_rng(3).uniform(-1, 1, len(self._series)), index=self._series.index)

        def macd_signal(self):
            import numpy.random as npr
            return pd.Series(npr.default_rng(4).uniform(-1, 1, len(self._series)), index=self._series.index)

    class _FakeHLC:
        def __init__(self, high=None, low=None, close=None, **k):
            self._close = close

        def adx(self):
            import numpy.random as npr
            return pd.Series(npr.default_rng(5).uniform(15, 35, len(self._close)), index=self._close.index)

        def average_true_range(self):
            import numpy.random as npr
            return pd.Series(np.abs(npr.default_rng(6).normal(1.0, 0.2, len(self._close))), index=self._close.index)

        def stoch(self):
            import numpy.random as npr
            return pd.Series(npr.default_rng(7).uniform(20, 80, len(self._close)), index=self._close.index)

        def stoch_signal(self):
            import numpy.random as npr
            return pd.Series(npr.default_rng(8).uniform(20, 80, len(self._close)), index=self._close.index)

    trend.EMAIndicator = _FakeSeriesIndicator
    trend.MACD = _FakeMACD
    trend.ADXIndicator = _FakeHLC
    momentum.RSIIndicator = _FakeSeriesIndicator
    momentum.StochasticOscillator = _FakeHLC
    volatility.AverageTrueRange = _FakeHLC
    volatility.BollingerBands = _FakeSeriesIndicator
    ta.trend = trend
    ta.momentum = momentum
    ta.volatility = volatility
    sys.modules["ta"] = ta
    sys.modules["ta.trend"] = trend
    sys.modules["ta.momentum"] = momentum
    sys.modules["ta.volatility"] = volatility

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.run_backtest as rb  # noqa: E402


def _make_df(n, step_ms):
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + np.abs(rng.normal(0.2, 0.1, n))
    low = close - np.abs(rng.normal(0.2, 0.1, n))
    vol = np.abs(rng.normal(1000, 100, n))
    taker = vol * rng.uniform(0.3, 0.7, n)
    return pd.DataFrame({
        "open_time": np.arange(n) * step_ms,
        "open": close, "high": high, "low": low, "close": close,
        "volume": vol, "taker_buy_volume": taker,
    })


class BoundedWindowRegressionTests(unittest.TestCase):
    def test_walk_past_lookback_window_does_not_crash(self):
        # More than LOOKBACK_CANDLES (300) 1H rows so the window slides
        # past the start of the series at least once during the walk.
        n_1h = rb.LOOKBACK_CANDLES + 100
        data = {
            "1h": _make_df(n_1h, 3600000),
            "4h": _make_df(n_1h, 4 * 3600000),
            "1d": _make_df(n_1h, 24 * 3600000),
            "15m": _make_df(n_1h * 4, 15 * 60000),
        }
        with patch.object(rb, "load_symbol_data", return_value=data):
            try:
                closed, still_open = rb.run_backtest(["TESTUSDT"], "/unused")
            except Exception as e:  # pragma: no cover - failure path
                self.fail(f"run_backtest crashed once the lookback window slid: {e!r}")
        self.assertIsInstance(closed, list)
        self.assertIsInstance(still_open, list)


if __name__ == "__main__":
    unittest.main()
