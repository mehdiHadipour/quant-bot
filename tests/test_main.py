import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from main import (
    has_reached_max_concurrent_trades, prepare_analysis_frames, should_skip_cycle_early,
    _decimals_for_reference_price, format_price, build_risk_tip, recent_realized_r_multiples,
)
import pandas as pd
import config


class TestMaxConcurrentTrades(unittest.TestCase):
    def setUp(self):
        self._orig = config.MAX_CONCURRENT_TRADES

    def tearDown(self):
        config.MAX_CONCURRENT_TRADES = self._orig
        import main
        main.MAX_CONCURRENT_TRADES = self._orig

    def _set_cap(self, value):
        # main.py imports the constant by value at module load time, so
        # both config and main's local copy need updating for the test.
        config.MAX_CONCURRENT_TRADES = value
        import main
        main.MAX_CONCURRENT_TRADES = value

    def test_cap_disabled_when_zero(self):
        self._set_cap(0)
        state = {"trades": [{"status": "open"}] * 50}
        self.assertFalse(has_reached_max_concurrent_trades(state))

    def test_under_cap_allows_new_trade(self):
        self._set_cap(4)
        state = {"trades": [{"status": "open"}] * 3}
        self.assertFalse(has_reached_max_concurrent_trades(state))

    def test_at_cap_blocks_new_trade(self):
        self._set_cap(4)
        state = {"trades": [{"status": "open"}] * 4}
        self.assertTrue(has_reached_max_concurrent_trades(state))

    def test_closed_trades_dont_count_toward_cap(self):
        self._set_cap(2)
        state = {"trades": [{"status": "closed"}] * 10 + [{"status": "open"}]}
        self.assertFalse(has_reached_max_concurrent_trades(state))



class TestHeartbeatEarlyExit(unittest.TestCase):
    """v27.4 (restored — was dropped in the v27.5 package this was merged
    from). See should_skip_cycle_early() in main.py."""
    def test_first_ever_run_never_skips(self):
        self.assertFalse(should_skip_cycle_early({}))
        self.assertFalse(should_skip_cycle_early({"last_cycle_completed_at": None}))

    def test_skips_when_within_cycle_window(self):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
        self.assertTrue(should_skip_cycle_early({"last_cycle_completed_at": recent}))

    def test_does_not_skip_once_cycle_minutes_elapsed(self):
        old = (datetime.now(timezone.utc) - timedelta(minutes=config.CYCLE_MINUTES + 1)).isoformat()
        self.assertFalse(should_skip_cycle_early({"last_cycle_completed_at": old}))

    def test_malformed_timestamp_does_not_skip(self):
        self.assertFalse(should_skip_cycle_early({"last_cycle_completed_at": "not-a-date"}))


class TestAdaptivePriceFormatting(unittest.TestCase):
    """Regression tests for a real reported bug: a fixed 2-decimal
    format made entry/SL/TP/ATR/VWAP for low-price symbols (DOGE, DOT,
    etc.) all round to the same indistinguishable value."""

    def test_low_price_symbol_gets_enough_decimals(self):
        d = _decimals_for_reference_price(0.07384)
        self.assertEqual(format_price(0.07384, d), "0.07384")
        self.assertEqual(format_price(0.07251, d), "0.07251")
        self.assertEqual(format_price(0.07783, d), "0.07783")
        # ATR at a very different magnitude still uses the SAME decimals
        # as the reference price, for visual consistency within one message.
        self.assertEqual(format_price(0.00121, d), "0.00121")

    def test_high_price_symbol_keeps_two_decimals_with_grouping(self):
        d = _decimals_for_reference_price(117245.30)
        self.assertEqual(format_price(117245.30, d), "117,245.30")
        self.assertEqual(format_price(116810.20, d), "116,810.20")

    def test_zero_and_invalid_fail_safe(self):
        self.assertEqual(_decimals_for_reference_price(0), 2)
        self.assertEqual(_decimals_for_reference_price(None), 2)
        self.assertEqual(_decimals_for_reference_price("not a number"), 2)
        self.assertEqual(format_price("not a number", 2), "not a number")

    def test_decimals_increase_as_price_gets_smaller(self):
        prices_and_min_decimals = [
            (5.0, 2), (0.5, 4), (0.05, 5), (0.005, 6), (0.0005, 7),
        ]
        prev_decimals = 0
        for price, expected in prices_and_min_decimals:
            d = _decimals_for_reference_price(price)
            self.assertEqual(d, expected, f"price={price}")
            self.assertGreaterEqual(d, prev_decimals)
            prev_decimals = d


class TestClosedCandleSignalIsolation(unittest.TestCase):
    def test_analysis_excludes_live_final_candle_but_monitoring_keeps_it(self):
        base = pd.DataFrame({
            "open": [100, 101, 102],
            "high": [101, 102, 103],
            "low": [99, 100, 101],
            "close": [100.5, 101.5, 102.5],
            "volume": [10, 11, 12],
            "taker_buy_volume": [5, 6, 7],
        })
        frames = {k: base.copy() for k in ("15m", "1h", "4h", "1d")}
        live, closed = prepare_analysis_frames(frames)
        self.assertEqual(len(live["1h"]), 3)
        self.assertEqual(len(closed["1h"]), 2)
        self.assertEqual(closed["1h"]["close"].iloc[-1], 101.5)
        self.assertEqual(live["1h"]["close"].iloc[-1], 102.5)

    def test_single_candle_produces_no_completed_signal_candle(self):
        base = pd.DataFrame({
            "open": [100], "high": [101], "low": [99], "close": [100.5],
            "volume": [10], "taker_buy_volume": [5],
        })
        frames = {k: base.copy() for k in ("15m", "1h", "4h", "1d")}
        _, closed = prepare_analysis_frames(frames)
        self.assertTrue(closed["1h"].empty)
        self.assertTrue(closed["4h"].empty)


class TestRecentRealizedRMultiples(unittest.TestCase):
    def test_no_history_returns_empty_list(self):
        with patch("main._read_history_csv", return_value=None):
            self.assertEqual(recent_realized_r_multiples(), [])

    def test_reads_and_orders_by_exit_time(self):
        df = pd.DataFrame([
            {"exit_time": "2026-01-02T00:00:00+00:00", "r_multiple": 1.0},
            {"exit_time": "2026-01-01T00:00:00+00:00", "r_multiple": -1.0},
        ])
        with patch("main._read_history_csv", return_value=df):
            values = recent_realized_r_multiples()
        self.assertEqual(values, [-1.0, 1.0])

    def test_respects_lookback(self):
        df = pd.DataFrame([{"exit_time": f"2026-01-{i:02d}T00:00:00+00:00", "r_multiple": float(i)} for i in range(1, 31)])
        with patch("main._read_history_csv", return_value=df):
            values = recent_realized_r_multiples(lookback=5)
        self.assertEqual(len(values), 5)
        self.assertEqual(values, [26.0, 27.0, 28.0, 29.0, 30.0])


class TestBuildRiskTipThrottleNote(unittest.TestCase):
    def test_no_throttle_note_when_history_is_healthy(self):
        with patch("main.recent_realized_r_multiples", return_value=[]):
            msg = build_risk_tip("BUY", 100, 90, 130)
        self.assertNotIn("عملکرد واقعی معاملات اخیر ضعیف‌تر", msg)

    def test_throttle_note_appears_when_recent_performance_is_severely_weak(self):
        weak = [-0.5, 0.2, -0.3, 0.1, -0.4] * 3  # 15 trades, avg <= 0
        with patch("main.recent_realized_r_multiples", return_value=weak):
            msg = build_risk_tip("BUY", 100, 90, 130)
        self.assertIn("عملکرد واقعی معاملات اخیر ضعیف‌تر", msg)
        self.assertIn("25%", msg)


if __name__ == "__main__":
    unittest.main()
