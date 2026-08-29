"""Regression test for main.process_symbol().

This exists specifically because a variable-ordering bug (result/msg used
before they were assigned, deep inside process_symbol's ~250-line body)
went undetected by every other check in this project -- py_compile,
import-time checks, validate_project.py, system_audit.py, and every unit
test all passed while the live bot would have crashed with an
UnboundLocalError on literally the first symbol that reached that code
path in production. None of those checks actually *execute*
process_symbol() with realistic inputs; this test does.
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

# main.py imports `ta`, a real dependency not installed in this sandbox.
# A minimal stub is enough here: this test is about process_symbol()'s own
# control flow (does it run at all, does a signal correctly open a trade),
# not about validating real indicator math -- that's indicators.py's own
# concern, covered by test_smart_context.py's checks and by actually
# running the bot against real market data.
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
import main  # noqa: E402


def _make_df(n=50):
    close = np.linspace(100, 110, n)
    return pd.DataFrame({
        "open_time": np.arange(n) * 3600000,
        "open": close, "high": close + 0.5, "low": close - 0.5, "close": close,
        "volume": [1000.0] * n, "taker_buy_volume": [600.0] * n,
    })


class ProcessSymbolRegressionTests(unittest.TestCase):
    def setUp(self):
        self.klines = {
            "15m": _make_df(), "1h": _make_df(), "4h": _make_df(), "1d": _make_df(),
        }
        self.state = {"trades": [], "stats": {"wins": 0, "losses": 0, "streak": 0}, "symbol_cooldowns": {}}
        self.counters = {"fetched_ok": 0, "closed": 0, "signals": 0}

    def test_no_signal_path_does_not_crash(self):
        # analyze_market's real gates (ADX etc.) will almost certainly
        # reject this flat synthetic data -- that's fine, this test only
        # cares that reaching this far in process_symbol never raises.
        with patch.object(main, "fetch_funding_rate", return_value=(None, None, "test")):
            try:
                main.process_symbol(self.state, "BTCUSDT", self.klines, self.counters)
            except Exception as e:  # pragma: no cover - failure path
                self.fail(f"process_symbol raised unexpectedly on the no-signal path: {e!r}")

    def test_signal_path_opens_a_trade_without_crashing(self):
        fake_signal = {
            "direction": "BUY", "buy": 80.0, "sell": 20.0, "neutral": 0.0,
            "atr": 2.0, "price": 110.0, "symbol": "BTCUSDT", "adx": 30.0,
            "divergence": None, "buy_ratio": 0.6, "fvg": None, "vwap": 109.0,
            "funding_rate": None, "liquidity_sweep": None,
            "smart_context": {
                "footprint": {"bias": "BUY", "delta": 0.3},
                "session": {"name": "LONDON_NY_OVERLAP"},
                "whale_bias": "BUY", "fundamental_score": 1.0,
            },
        }
        with patch.object(main, "analyze_market", return_value=fake_signal), \
             patch.object(main, "fetch_funding_rate", return_value=(None, None, "test")), \
             patch.object(main, "send_telegram_alert", return_value=None), \
             patch.object(main, "save_state", return_value=None):
            main.process_symbol(self.state, "BTCUSDT", self.klines, self.counters)

        self.assertEqual(self.counters["signals"], 1)
        self.assertEqual(len(self.state["trades"]), 1)
        trade = self.state["trades"][0]
        self.assertEqual(trade["direction"], "BUY")
        self.assertEqual(trade["status"], "open")
        self.assertAlmostEqual(trade["entry"], 110.0)
        self.assertAlmostEqual(trade["sl"], 106.4)
        self.assertAlmostEqual(trade["tp"], 116.0)


if __name__ == "__main__":
    unittest.main()
