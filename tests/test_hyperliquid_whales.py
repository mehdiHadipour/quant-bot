import unittest
from hyperliquid_whales import aggregate_positions


class HyperliquidWhalesTests(unittest.TestCase):
    def test_majority_long_notional_gives_buy_bias(self):
        positions = {
            "0xA": [{"coin": "BTC", "szi": 2.0, "notional": 100_000.0}],
            "0xB": [{"coin": "BTC", "szi": 1.0, "notional": 50_000.0}],
            "0xC": [{"coin": "BTC", "szi": -1.0, "notional": 20_000.0}],
        }
        result = aggregate_positions(positions)
        self.assertEqual(result["BTC"]["bias"], "BUY")
        self.assertEqual(result["BTC"]["n_long"], 2)
        self.assertEqual(result["BTC"]["n_short"], 1)

    def test_majority_short_notional_gives_sell_bias(self):
        positions = {
            "0xA": [{"coin": "ETH", "szi": -3.0, "notional": 90_000.0}],
            "0xB": [{"coin": "ETH", "szi": 1.0, "notional": 10_000.0}],
        }
        result = aggregate_positions(positions)
        self.assertEqual(result["ETH"]["bias"], "SELL")

    def test_close_split_is_neutral(self):
        positions = {
            "0xA": [{"coin": "SOL", "szi": 1.0, "notional": 51_000.0}],
            "0xB": [{"coin": "SOL", "szi": -1.0, "notional": 49_000.0}],
        }
        result = aggregate_positions(positions)
        self.assertEqual(result["SOL"]["bias"], "NEUTRAL")

    def test_no_positions_gives_empty_result(self):
        self.assertEqual(aggregate_positions({}), {})

    def test_coins_are_independent(self):
        positions = {
            "0xA": [
                {"coin": "BTC", "szi": 1.0, "notional": 100_000.0},
                {"coin": "ETH", "szi": -1.0, "notional": 100_000.0},
            ],
        }
        result = aggregate_positions(positions)
        self.assertEqual(result["BTC"]["bias"], "BUY")
        self.assertEqual(result["ETH"]["bias"], "SELL")


if __name__ == "__main__":
    unittest.main()
