import unittest
import pandas as pd
import numpy as np

from indicators import detect_rsi_divergence, analyze_market, MIN_CANDLES


class TestRsiDivergence(unittest.TestCase):
    def test_bearish_divergence_detected(self):
        # Price makes a fresh (higher) high, but RSI at that point is lower
        # than it was at the prior swing high — classic bearish divergence.
        close = pd.Series(list(range(100, 124)) + [140, 130, 120, 110, 105, 100, 141])
        rsi = pd.Series([50] * 24 + [90, 85, 80, 75, 70, 65, 60])
        self.assertEqual(detect_rsi_divergence(close, rsi, lookback=30), "bearish")

    def test_bullish_divergence_detected(self):
        close = pd.Series(list(range(200, 176, -1)) + [150, 160, 170, 180, 185, 190, 149])
        rsi = pd.Series([50] * 24 + [10, 15, 20, 25, 30, 35, 40])
        self.assertEqual(detect_rsi_divergence(close, rsi, lookback=30), "bullish")

    def test_no_divergence_on_clean_trend(self):
        close = pd.Series(range(100, 131))
        rsi = pd.Series(range(30, 61))
        self.assertIsNone(detect_rsi_divergence(close, rsi, lookback=30))

    def test_insufficient_data_returns_none(self):
        close = pd.Series(range(100, 110))
        rsi = pd.Series(range(30, 40))
        self.assertIsNone(detect_rsi_divergence(close, rsi, lookback=30))

    def test_nan_in_window_returns_none_not_crash(self):
        close = pd.Series(range(100, 132))
        rsi = pd.Series([float("nan")] * 32)
        self.assertIsNone(detect_rsi_divergence(close, rsi, lookback=30))


def _make_ohlcv(n, close_values, high_offset=1.0, low_offset=1.0, volume=1000.0):
    close = pd.Series(close_values[:n], dtype=float)
    return pd.DataFrame({
        "close": close,
        "high": close + high_offset,
        "low": close - low_offset,
        "volume": pd.Series([volume] * n),
    })


class TestAnalyzeMarket(unittest.TestCase):
    """These exercise the real `ta` library (installed via requirements.txt
    in CI), so they double as a smoke test that the indicator wiring in
    indicators.py still matches the installed `ta` API after any dependency
    upgrade."""

    def test_insufficient_candles_returns_none(self):
        n = MIN_CANDLES - 5
        df = _make_ohlcv(n, [100 + i * 0.1 for i in range(n)])
        self.assertIsNone(analyze_market(df, df, df, df, "TESTUSDT"))

    def test_does_not_raise_on_a_ranging_market(self):
        # Small random noise around a flat price — a classic low-ADX,
        # "nothing to trade" market. Must not raise, and in practice
        # should not produce a signal (verified in manual QA against the
        # real `ta` package during development).
        n = 250
        rng = np.random.default_rng(42)
        close_values = list(100 + rng.normal(0, 0.05, n).cumsum() * 0 + rng.normal(0, 0.05, n))
        df = _make_ohlcv(n, [100 + v for v in close_values])
        try:
            analyze_market(df, df, df, df, "TESTUSDT")
        except Exception as e:
            self.fail(f"analyze_market raised unexpectedly on ranging data: {e}")

    def test_does_not_raise_on_a_strong_uptrend(self):
        n = 250
        close_values = [100 + i * 0.5 for i in range(n)]
        df = _make_ohlcv(n, close_values)
        try:
            # Same trending series on all four timeframes so 4H/1D/15m
            # confluence naturally agrees for this smoke test.
            result = analyze_market(df, df, df, df, "TESTUSDT")
        except Exception as e:
            self.fail(f"analyze_market raised unexpectedly on trending data: {e}")
        # If a signal is returned, its shape must be well-formed.
        if result is not None:
            self.assertIn(result["direction"], ("BUY", "SELL"))
            self.assertGreater(result["price"], 0)
            self.assertIn("adx", result)
            self.assertIn("divergence", result)

    def test_missing_15m_and_1d_data_handled_gracefully(self):
        # Simulates what main.py passes when the 15m/1D fetch failed this
        # cycle: empty frames instead of None. Must not raise, and since
        # get_timeframe_bias requires MIN_CANDLES, an empty 1D frame means
        # the confluence gate can never pass — that's expected, not a bug.
        n = 250
        df = _make_ohlcv(n, [100 + i * 0.5 for i in range(n)])
        empty = pd.DataFrame(columns=df.columns)
        try:
            result = analyze_market(empty, df, df, empty, "TESTUSDT")
        except Exception as e:
            self.fail(f"analyze_market raised on empty 15m/1D frames: {e}")
        self.assertIsNone(result)  # no 1D data => confluence gate can't pass


if __name__ == "__main__":
    unittest.main()
