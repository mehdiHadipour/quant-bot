import unittest
import pandas as pd
from footprint import compute_footprint_metrics, describe_footprint


def _trades(rows):
    """rows: list of (price, qty, is_buyer_maker)."""
    return pd.DataFrame(rows, columns=["price", "qty", "is_buyer_maker"])


class TestComputeFootprintMetrics(unittest.TestCase):
    def test_none_when_trades_empty(self):
        self.assertIsNone(compute_footprint_metrics(_trades([]), 100, 110))

    def test_none_when_trades_is_none(self):
        self.assertIsNone(compute_footprint_metrics(None, 100, 110))

    def test_none_when_candle_has_no_range(self):
        df = _trades([(100, 1.0, False)])
        self.assertIsNone(compute_footprint_metrics(df, 100, 100))

    def test_buy_ratio_all_aggressive_buys(self):
        # is_buyer_maker=False means the buyer crossed the spread (aggressive buy).
        df = _trades([(101, 1.0, False), (102, 2.0, False)])
        result = compute_footprint_metrics(df, 100, 110)
        self.assertAlmostEqual(result["buy_ratio"], 1.0)

    def test_buy_ratio_all_aggressive_sells(self):
        df = _trades([(101, 1.0, True), (102, 2.0, True)])
        result = compute_footprint_metrics(df, 100, 110)
        self.assertAlmostEqual(result["buy_ratio"], 0.0)

    def test_buy_ratio_mixed(self):
        df = _trades([(101, 3.0, False), (102, 1.0, True)])  # 3 buy, 1 sell -> 75%
        result = compute_footprint_metrics(df, 100, 110)
        self.assertAlmostEqual(result["buy_ratio"], 0.75)

    def test_poc_identifies_highest_volume_price_bucket(self):
        # Heavy volume concentrated near the low of the range.
        df = _trades([
            (100.5, 100.0, False),  # huge volume near the low
            (109.5, 1.0, False),    # tiny volume near the high
        ])
        result = compute_footprint_metrics(df, 100, 110, n_bins=10)
        self.assertLess(result["poc_position"], 0.2)  # POC near the low end

    def test_poc_position_is_high_when_volume_concentrated_at_top(self):
        df = _trades([
            (109.5, 100.0, False),
            (100.5, 1.0, False),
        ])
        result = compute_footprint_metrics(df, 100, 110, n_bins=10)
        self.assertGreater(result["poc_position"], 0.8)

    def test_imbalance_near_high_and_low_computed_separately(self):
        df = _trades([
            (109, 5.0, False),   # near high: all aggressive buy
            (109, 5.0, False),
            (101, 5.0, True),    # near low: all aggressive sell
            (101, 5.0, True),
        ])
        result = compute_footprint_metrics(df, 100, 110)
        self.assertAlmostEqual(result["imbalance_near_high"], 1.0)
        self.assertAlmostEqual(result["imbalance_near_low"], 0.0)

    def test_zero_total_volume_returns_none(self):
        df = _trades([(101, 0.0, False)])
        self.assertIsNone(compute_footprint_metrics(df, 100, 110))

    def test_trade_count_reported(self):
        df = _trades([(101, 1.0, False), (102, 1.0, True), (103, 1.0, False)])
        result = compute_footprint_metrics(df, 100, 110)
        self.assertEqual(result["trade_count"], 3)


class TestDescribeFootprint(unittest.TestCase):
    def test_none_metrics_produces_graceful_message(self):
        msg = describe_footprint(None, "BUY")
        self.assertIn("در دسترس نبود", msg)

    def test_valid_metrics_includes_percentages(self):
        metrics = {"buy_ratio": 0.65, "poc_position": 0.3, "trade_count": 42}
        msg = describe_footprint(metrics, "BUY")
        self.assertIn("65", msg)
        self.assertIn("30", msg)
        self.assertIn("42", msg)

    def test_never_claims_to_be_a_validated_filter(self):
        """Regression guard: this must always read as informational, per
        footprint.py's module docstring — never phrase it as
        pass/fail/agree/disagree with the signal's direction."""
        metrics = {"buy_ratio": 0.2, "poc_position": 0.9, "trade_count": 10}
        msg = describe_footprint(metrics, "BUY")
        for forbidden in ("تأیید شد", "رد شد", "مخالف جهت"):
            self.assertNotIn(forbidden, msg)


if __name__ == "__main__":
    unittest.main()
