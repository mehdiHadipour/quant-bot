import unittest

from main import has_reached_max_concurrent_trades
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


if __name__ == "__main__":
    unittest.main()
