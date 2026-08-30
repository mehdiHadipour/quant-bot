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

if __name__ == "__main__":
    unittest.main()

class SessionHardGateTests(unittest.TestCase):
    def test_asia_is_enabled(self):
        df = pd.DataFrame([{"open_time": 3 * 3600 * 1000, "open":100, "high":101, "low":99, "close":100.5, "volume":1000, "taker_buy_volume":550}])
        self.assertTrue(session_context(df)["allow"])
        self.assertEqual(session_context(df)["name"], "ASIA")

    def test_asia_europe_overlap_is_enabled(self):
        # 08:30 UTC is inside London and Tokyo on dates when both local clocks align.
        df = pd.DataFrame([{"open_time": 1782894600000, "open":100, "high":101, "low":99, "close":100.5, "volume":1000, "taker_buy_volume":550}])
        ctx = session_context(df)
        self.assertTrue(ctx["allow"])
        self.assertEqual(ctx["name"], "ASIA_EUROPE_OVERLAP")


class DefensivePolicyTests(unittest.TestCase):
    def test_negative_session_is_strict(self):
        # 03:00 UTC is Asia; opposing/neutral flow must not pass the strict gate.
        df = pd.DataFrame([{"open_time": 3 * 3600 * 1000, "open":100, "high":101, "low":99, "close":100.5, "volume":1000, "taker_buy_volume":550}])
        ok, info = evaluate("TESTUSDT", "BUY", df)
        self.assertFalse(ok)
        self.assertIn("session", info["reason"].lower())

    def test_negative_symbol_requires_alignment(self):
        df = pd.DataFrame([{"open_time": 14 * 3600 * 1000, "open":100, "high":101, "low":99, "close":100.5, "volume":1000, "taker_buy_volume":550}])
        ok, info = evaluate("LINKUSDT", "BUY", df)
        self.assertFalse(ok)
        self.assertIn("Strict symbol", info["reason"])
