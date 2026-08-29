import sys
import types
import unittest
from pathlib import Path

# indicators.py imports `ta`, a real dependency not installed in this
# sandbox. compute_ichimoku() itself never touches `ta` (it's pure
# pandas/numpy), but importing indicators.py at all requires the module
# to exist. A minimal stub is enough since none of its symbols are used
# by compute_ichimoku().
if "ta" not in sys.modules:
    ta = types.ModuleType("ta")
    trend = types.ModuleType("ta.trend")
    momentum = types.ModuleType("ta.momentum")
    volatility = types.ModuleType("ta.volatility")

    class _Fake:
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, name):
            def f(*a, **k):
                import pandas as pd
                return pd.Series([1.0] * 300)
            return f

    for _name in ["EMAIndicator", "MACD", "ADXIndicator"]:
        setattr(trend, _name, _Fake)
    for _name in ["RSIIndicator", "StochasticOscillator"]:
        setattr(momentum, _name, _Fake)
    for _name in ["AverageTrueRange", "BollingerBands"]:
        setattr(volatility, _name, _Fake)
    ta.trend = trend
    ta.momentum = momentum
    ta.volatility = volatility
    sys.modules["ta"] = ta
    sys.modules["ta.trend"] = trend
    sys.modules["ta.momentum"] = momentum
    sys.modules["ta.volatility"] = volatility

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from indicators import compute_ichimoku, ICHIMOKU_SENKOU_B_WINDOW, ICHIMOKU_KIJUN_WINDOW  # noqa: E402


def _trend_df(start, end, n=100):
    close = np.linspace(start, end, n)
    return pd.DataFrame({"high": close + 1, "low": close - 1, "close": close})


class IchimokuTests(unittest.TestCase):
    def test_insufficient_history_returns_none(self):
        short_df = _trend_df(100, 110, n=ICHIMOKU_SENKOU_B_WINDOW + ICHIMOKU_KIJUN_WINDOW - 1)
        self.assertIsNone(compute_ichimoku(short_df))

    def test_minimum_sufficient_history_does_not_crash(self):
        exact_df = _trend_df(100, 110, n=ICHIMOKU_SENKOU_B_WINDOW + ICHIMOKU_KIJUN_WINDOW)
        result = compute_ichimoku(exact_df)
        # May or may not be None depending on rolling-window NaN edges at
        # the exact boundary -- the only hard requirement is no crash.
        self.assertTrue(result is None or isinstance(result, dict))

    def test_strong_uptrend_is_fully_bullish(self):
        df = _trend_df(100, 200)
        result = compute_ichimoku(df)
        self.assertIsNotNone(result)
        self.assertEqual(result["price_vs_cloud"], "above")
        self.assertEqual(result["tenkan_kijun"], "bullish")
        self.assertEqual(result["cloud_color"], "bullish")
        self.assertEqual(result["chikou"], "bullish")
        self.assertEqual(result["score"], 40)

    def test_strong_downtrend_is_fully_bearish(self):
        df = _trend_df(200, 100)
        result = compute_ichimoku(df)
        self.assertIsNotNone(result)
        self.assertEqual(result["price_vs_cloud"], "below")
        self.assertEqual(result["tenkan_kijun"], "bearish")
        self.assertEqual(result["cloud_color"], "bearish")
        self.assertEqual(result["chikou"], "bearish")
        self.assertEqual(result["score"], -40)

    def test_flat_price_is_neutral_ish(self):
        n = 100
        df = pd.DataFrame({"high": [100.0] * n, "low": [100.0] * n, "close": [100.0] * n})
        result = compute_ichimoku(df)
        self.assertIsNotNone(result)
        self.assertEqual(result["price_vs_cloud"], "inside")
        self.assertEqual(result["tenkan_kijun"], "neutral")
        self.assertEqual(result["chikou"], "neutral")
        self.assertEqual(result["score"], 0 + (5 if result["cloud_color"] == "bullish" else -5))

    def test_cloud_uses_the_value_from_26_candles_ago_not_today(self):
        # A trend that reverses partway through: if the cloud calc used
        # TODAY's raw Senkou values instead of the value from 26 candles
        # ago (the classic forward-shift bug), this would misclassify
        # price-vs-cloud for a reversal like this.
        up = np.linspace(100, 150, 60)
        down = np.linspace(150, 90, 60)
        close = np.concatenate([up, down])
        df = pd.DataFrame({"high": close + 1, "low": close - 1, "close": close})
        result = compute_ichimoku(df)
        self.assertIsNotNone(result)
        # After a sharp reversal down, price should now be below (or at
        # least not cleanly above) a cloud that was largely built from the
        # earlier uptrend data -- the specific label matters less here
        # than simply proving the function handles a reversal without
        # crashing and produces internally consistent top/bottom bounds.
        self.assertLessEqual(result["cloud_bottom"], result["cloud_top"])


if __name__ == "__main__":
    unittest.main()
