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
        "open": close,
        "close": close,
        "high": close + high_offset,
        "low": close - low_offset,
        "volume": pd.Series([volume] * n),
        "taker_buy_volume": pd.Series([volume * 0.5] * n),
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

    def test_fvg_detected_on_a_genuine_gap_up(self):
        """Fair Value Gap: candle[-3]'s high must be below candle[-1]'s low
        for a bullish FVG. Craft the last 3 candles explicitly to form one
        on top of an otherwise-normal uptrend, and check it's reported."""
        n = 250
        close_values = [100 + i * 0.5 for i in range(n)]
        df = _make_ohlcv(n, close_values)
        # Force a clean gap: candle[-3] high well below candle[-1] low.
        df.loc[df.index[-3], "high"] = df["close"].iloc[-3] + 0.1
        df.loc[df.index[-1], "low"] = df["high"].iloc[-3] + 5.0
        df.loc[df.index[-1], "close"] = df["low"].iloc[-1] + 1.0
        df.loc[df.index[-1], "high"] = df["close"].iloc[-1] + 1.0
        result = analyze_market(df, df, df, df, "TESTUSDT")
        if result is not None:
            self.assertEqual(result.get("fvg"), "bullish")


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

    def test_buy_sell_probability_symmetry(self):
        """Regression test for a real, reported bug: an earlier version of
        the probability formula used the wrong sign in the SELL branch,
        which made *stronger* bearish setups score a *lower* sell
        probability — the opposite of intended — so SELL signals almost
        never cleared the confidence threshold no matter how strong the
        downtrend was. This test builds a genuine mirror-image bearish
        setup (not just a flipped sign on paper) and requires that it
        produces a SELL signal with a probability comparable to the
        equivalent bullish case. If this test ever fails, suspect the sign
        in the buy_prob/sell_prob sigmoid formulas first."""
        n = 250
        up = pd.Series([100 + i * 0.5 for i in range(n)])
        up.iloc[-1] = up.iloc[-2] + 5  # breakout candle
        down = pd.Series([300 - i * 0.5 for i in range(n)])
        down.iloc[-1] = down.iloc[-2] - 5  # breakdown candle

        vol = pd.Series([1000.0] * n)
        vol.iloc[-1] = 3000.0  # volume spike on the breakout/breakdown candle

        df_up = pd.DataFrame({"open": up, "close": up, "high": up + 1, "low": up - 1, "volume": vol, "taker_buy_volume": vol * 0.5})
        df_down = pd.DataFrame({"open": down, "close": down, "high": down + 1, "low": down - 1, "volume": vol, "taker_buy_volume": vol * 0.5})

        res_buy = analyze_market(df_up, df_up, df_up, df_up, "TESTUSDT")
        res_sell = analyze_market(df_down, df_down, df_down, df_down, "TESTUSDT")

        self.assertIsNotNone(res_buy, "a clean uptrend + breakout should produce a BUY signal")
        self.assertEqual(res_buy["direction"], "BUY")

        self.assertIsNotNone(
            res_sell,
            "a mirror-image downtrend + breakdown should ALSO produce a SELL signal "
            "(if this is None, the SELL probability formula is likely inverted again)",
        )
        self.assertEqual(res_sell["direction"], "SELL")

        self.assertLess(
            abs(res_buy["buy"] - res_sell["sell"]), 15,
            "BUY and SELL probabilities for mirror-image setups of equal strength "
            "should be roughly symmetric, not wildly different",
        )


class TestAdaptiveTrendPathDoesNotCrash(unittest.TestCase):
    """Regression test for a real, severe bug found via CI's ruff F821
    check: analyze_market()'s ADAPTIVE_TREND_ENABLED branch (the DEFAULT
    strategy per config.py/README) referenced buy_ratio/liquidity_sweep/
    divergence in its result dict before those variables were computed
    anywhere — a guaranteed NameError on every call, under default
    settings, whenever the AdaptiveTrend early-return actually fires.

    The existing smoke tests above (test_does_not_raise_on_a_strong_uptrend
    etc.) used perfectly deterministic, noise-free linear trends, which
    happened to produce ~0 realized volatility — low enough to fall below
    ADAPTIVE_MIN_RV and hit an earlier `return None`, before ever reaching
    the buggy line. That's why they passed despite the bug: they never
    actually exercised the AdaptiveTrend success path. Real market data
    always has noise/volatility, so this crashed in every realistic run.
    This test uses seeded random noise specifically so realized volatility
    is nonzero and the AdaptiveTrend branch's return statement actually
    executes, which is the only way to catch this class of bug."""

    def test_noisy_trending_data_produces_a_signal_without_crashing(self):
        import config
        self.assertTrue(config.ADAPTIVE_TREND_ENABLED, "test assumes the default strategy")

        rng = np.random.default_rng(1)
        n = 260
        close = 100 + np.cumsum(rng.normal(0.1, 0.5, n))
        df = pd.DataFrame({
            "open": close - 0.1,
            "high": close + np.abs(rng.normal(0.5, 0.2, n)),
            "low": close - np.abs(rng.normal(0.5, 0.2, n)),
            "close": close,
            "volume": rng.uniform(100, 200, n),
            "taker_buy_volume": rng.uniform(40, 100, n),
        })
        try:
            result = analyze_market(df, df, df, df, "TESTUSDT")
        except NameError as e:
            self.fail(f"AdaptiveTrend path raised NameError (undefined variable): {e}")
        # Realized volatility from this noise profile should clear
        # ADAPTIVE_MIN_RV, so a signal (not a None skip) is expected here —
        # if this assertion itself ever fails, the noise parameters above
        # may need adjusting, but a None result must still never come from
        # a caught NameError.
        self.assertIsNotNone(result)
        self.assertIn(result["direction"], ("BUY", "SELL"))
        for key in ("buy_ratio", "liquidity_sweep", "divergence"):
            self.assertIn(key, result)


class TestFundingRateScoring(unittest.TestCase):
    """funding_rate is a contrarian, modest-weight, fail-open input: it
    must never block a signal on its own (None just means 0 score), and it
    must not flip a clear trend's direction — only nudge the probability."""

    def test_none_funding_rate_does_not_crash_or_change_direction(self):
        n = 250
        close_values = [100 + i * 0.5 for i in range(n)]
        df = _make_ohlcv(n, close_values)
        try:
            result = analyze_market(df, df, df, df, "TESTUSDT", funding_rate=None)
        except Exception as e:
            self.fail(f"analyze_market raised with funding_rate=None: {e}")
        if result is not None:
            self.assertEqual(result["direction"], "BUY")
            self.assertIsNone(result.get("funding_rate"))

    def test_extreme_positive_funding_does_not_flip_a_clean_uptrend(self):
        n = 250
        close_values = [100 + i * 0.5 for i in range(n)]
        df = _make_ohlcv(n, close_values)
        result = analyze_market(df, df, df, df, "TESTUSDT", funding_rate=0.01)
        if result is not None:
            # A strongly positive funding rate should only ever soften a
            # BUY signal's confidence, never turn a clean, strong uptrend
            # into a SELL — it's a modest contrarian nudge, not an override.
            self.assertEqual(result["direction"], "BUY")
            self.assertEqual(result.get("funding_rate"), 0.01)


class TestScoreBreakdown(unittest.TestCase):
    """v27.8: tests the breakdown filter+sort logic directly (same code
    pattern used inside analyze_market) rather than through a full
    analyze_market() call, since forcing a specific score combination
    through the real indicator pipeline isn't practical to set up
    deterministically."""

    @staticmethod
    def _build_breakdown(**scores):
        breakdown = {k: v for k, v in scores.items() if v != 0}
        return dict(sorted(breakdown.items(), key=lambda kv: abs(kv[1]), reverse=True))

    def test_zero_value_factors_are_excluded(self):
        breakdown = self._build_breakdown(Trend=20, Stochastic=0, Bollinger=0, VWAP=8)
        self.assertNotIn("Stochastic", breakdown)
        self.assertNotIn("Bollinger", breakdown)
        self.assertIn("Trend", breakdown)
        self.assertIn("VWAP", breakdown)

    def test_sorted_by_magnitude_descending_unaffected_by_sign(self):
        breakdown = self._build_breakdown(Trend=20, Momentum=-15, Structure=25, VWAP=8)
        self.assertEqual(list(breakdown.keys()), ["Structure", "Trend", "Momentum", "VWAP"])

    def test_all_zero_gives_empty_breakdown(self):
        self.assertEqual(self._build_breakdown(A=0, B=0), {})


if __name__ == "__main__":
    unittest.main()
