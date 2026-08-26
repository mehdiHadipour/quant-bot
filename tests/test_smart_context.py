import os
import unittest
import pandas as pd
from smart_context import footprint_proxy, session_context, evaluate

class SmartContextTests(unittest.TestCase):
    def test_footprint_neutral_without_data(self):
        self.assertEqual(footprint_proxy(None)["bias"], "NEUTRAL")

    def test_session_is_deterministic_from_open_time(self):
        # 14:00 UTC = London/New York overlap
        df = pd.DataFrame([{"open_time": 14 * 3600 * 1000, "open":100, "high":101, "low":99, "close":100.5, "volume":1000, "taker_buy_volume":600}])
        self.assertEqual(session_context(df)["name"], "LONDON_NY_OVERLAP")

    def test_strong_opposing_flow_vetoes(self):
        df = pd.DataFrame([{"open_time": 14 * 3600 * 1000, "open":100, "high":101, "low":99.0, "close":99.2, "volume":1000, "taker_buy_volume":100}])
        ok, info = evaluate("TESTUSDT", "BUY", df)
        self.assertFalse(ok)
        self.assertIn("Footprint", info["reason"])

    def test_external_data_missing_is_neutral(self):
        for k in ("WHALE_BIAS_JSON", "WHALE_BIAS_FILE", "FUNDAMENTAL_JSON", "FUNDAMENTAL_FILE"):
            os.environ.pop(k, None)
        df = pd.DataFrame([{"open_time": 14 * 3600 * 1000, "open":100, "high":101, "low":99, "close":100.5, "volume":1000, "taker_buy_volume":550}])
        ok, info = evaluate("TESTUSDT", "BUY", df)
        self.assertTrue(ok)
        self.assertEqual(info["whale_bias"], "NEUTRAL")
        self.assertEqual(info["fundamental_score"], 0.0)

    def test_all_symbols_two_way_and_core_markets(self):
        import config
        self.assertIn("BTCUSDT", config.SYMBOLS)
        self.assertIn("ETHUSDT", config.SYMBOLS)
        self.assertFalse(config.ENABLE_DIRECTION_POLICY)
        self.assertEqual(config.BUY_ONLY_SYMBOLS, set())
        self.assertEqual(config.SELL_ONLY_SYMBOLS, set())

    def test_rollover_is_not_a_blackout(self):
        import config
        self.assertFalse(config.SESSION_VETO_ENABLED)
        self.assertEqual(config.MIN_SESSION_QUALITY, 0.0)
        self.assertGreaterEqual(config.MIN_ATR_PERCENT, 0.0)

if __name__ == "__main__":
    unittest.main()
