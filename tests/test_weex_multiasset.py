import json
import os
import tempfile
import unittest
from pathlib import Path

from asset_universe import classify_symbol
from performance_monitor import diagnose


class TestWEEXMultiAsset(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(classify_symbol("XAUTUSDT"), "METAL")
        self.assertEqual(classify_symbol("CLUSDT"), "ENERGY")
        self.assertEqual(classify_symbol("SPYXUSDT"), "ETF")
        self.assertEqual(classify_symbol("GER40USDT"), "INDEX")
        self.assertEqual(classify_symbol("AAPLXUSDT"), "STOCK")

    def test_negative_direction_alert(self):
        rows = [{"symbol":"TESTUSDT","direction":"BUY","session":"NEW_YORK","r_multiple":-1.0} for _ in range(8)]
        rows += [{"symbol":"TESTUSDT","direction":"SELL","session":"NEW_YORK","r_multiple":1.0} for _ in range(8)]
        d = diagnose(rows)
        buy = [x for x in d["alerts"] if x.get("direction") == "BUY"]
        self.assertTrue(buy)
        self.assertEqual(d["direction_policies"]["TESTUSDT"]["BUY"]["level"], "BLOCK")


if __name__ == "__main__":
    unittest.main()
