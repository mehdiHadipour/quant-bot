import os
import unittest
from pathlib import Path

class FibonacciGateTests(unittest.TestCase):
    def test_requirement_default_is_enabled(self):
        self.assertEqual(os.getenv("REQUIRE_FIB_OTE", "1"), "1")

    def test_indicators_expose_fibonacci_requirement(self):
        import indicators
        self.assertIn("REQUIRE_FIB_OTE", Path("config.py").read_text(encoding="utf-8"))
        self.assertTrue(hasattr(indicators, "analyze_market"))
        self.assertAlmostEqual(indicators.FIB_OTE_LOW, 0.618)
        self.assertAlmostEqual(indicators.FIB_OTE_HIGH, 0.786)
        self.assertEqual(indicators.FIB_LOOKBACK, 72)

if __name__ == "__main__":
    unittest.main()
