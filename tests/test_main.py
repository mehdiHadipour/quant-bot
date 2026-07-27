import unittest

from main import has_reached_max_concurrent_trades, prepare_analysis_frames
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


if __name__ == "__main__":
    unittest.main()
