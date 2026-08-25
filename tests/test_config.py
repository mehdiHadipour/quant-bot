import unittest
import config


class TestDirectionAllowed(unittest.TestCase):
    """Tests for the per-symbol direction policy (V27.22), based on the
    user's own real (demo-account) trade results — a SELL-only symbol
    should never let a BUY signal through, but must never block SELL."""

    def test_sell_only_symbol_blocks_buy(self):
        self.assertFalse(config.direction_allowed("BNBUSDT", "BUY"))

    def test_sell_only_symbol_allows_sell(self):
        self.assertTrue(config.direction_allowed("BNBUSDT", "SELL"))

    def test_buy_only_symbol_allows_only_buy(self):
        self.assertTrue(config.direction_allowed("DOGEUSDT", "BUY"))
        self.assertFalse(config.direction_allowed("DOGEUSDT", "SELL"))

    def test_symbol_not_in_symbols_at_all_defaults_unrestricted(self):
        """A symbol absent from both SYMBOLS and SELL_ONLY_SYMBOLS (e.g.
        one that's been fully removed) is unrestricted by this function
        specifically — it simply never gets analyzed in the first place
        since it's not iterated over, so this function never sees it
        live; this just documents that direction_allowed itself doesn't
        error or misbehave on an unknown symbol."""
        self.assertTrue(config.direction_allowed("BTCUSDT", "BUY"))

    def test_default_sell_only_set_matches_the_requested_policy(self):
        expected = {"BNBUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "ZECUSDT"}
        self.assertEqual(config.SELL_ONLY_SYMBOLS, expected)

    def test_fully_removed_symbols_are_not_in_default_symbols(self):
        removed = {"BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SUIUSDT", "TONUSDT"}
        self.assertTrue(removed.isdisjoint(set(config.SYMBOLS)))

    def test_directional_symbols_are_in_symbols(self):
        for sym in ("DOGEUSDT", "DOTUSDT", "ZECUSDT"):
            self.assertIn(sym, config.SYMBOLS)
        self.assertEqual(config.BUY_ONLY_SYMBOLS, {"DOGEUSDT", "DOTUSDT"})
        self.assertIn("ZECUSDT", config.SELL_ONLY_SYMBOLS)


if __name__ == "__main__":
    unittest.main()

