import os
import unittest
import pandas as pd
from smart_context import footprint_proxy, session_context, evaluate

class SmartContextTests(unittest.TestCase):
    # Unit tests must be deterministic and must not depend on real network
    # access or today's live news content. evaluate() calls
    # news_provider.fundamental_score() whenever no FUNDAMENTAL sidecar is
    # supplied, which -- if NEWS_ENABLED is left at its "live" default --
    # makes a real Google News RSS request. In an offline dev sandbox that
    # request simply fails and silently scores 0 (accidentally looking
    # deterministic); in real CI (with real internet) it can genuinely
    # match unrelated live articles for a made-up symbol like "TESTUSDT"
    # and return a non-zero score, making any test around it flaky. Force
    # it off for the whole test class instead of relying on that accident.
    def setUp(self):
        self._old_news_enabled = os.environ.get("NEWS_ENABLED")
        os.environ["NEWS_ENABLED"] = "0"

    def tearDown(self):
        if self._old_news_enabled is None:
            os.environ.pop("NEWS_ENABLED", None)
        else:
            os.environ["NEWS_ENABLED"] = self._old_news_enabled

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
