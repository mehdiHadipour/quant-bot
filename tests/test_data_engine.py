import unittest
from unittest.mock import patch, Mock

from data_engine import _to_okx_symbol, fetch_okx_klines, fetch_klines


class TestOkxSymbolMapping(unittest.TestCase):
    def test_usdt_pair_maps_to_dash_form(self):
        self.assertEqual(_to_okx_symbol("BTCUSDT"), "BTC-USDT")
        self.assertEqual(_to_okx_symbol("ETHUSDT"), "ETH-USDT")

    def test_non_usdt_pair_returns_none(self):
        self.assertIsNone(_to_okx_symbol("BTCUSD"))
        self.assertIsNone(_to_okx_symbol("USDT"))


class TestFetchOkxKlines(unittest.TestCase):
    def _mock_response(self, status_code=200, payload=None):
        resp = Mock()
        resp.status_code = status_code
        resp.json.return_value = payload or {}
        return resp

    def test_unsupported_interval_returns_none_without_network_call(self):
        with patch("data_engine.requests.get") as mock_get:
            result = fetch_okx_klines("BTCUSDT", interval="3m")
            self.assertIsNone(result)
            mock_get.assert_not_called()

    def test_successful_fetch_returns_oldest_first_dataframe(self):
        # OKX returns candles newest-first: [ts, o, h, l, c, vol, ...]
        payload = {"data": [
            ["3000", "103", "104", "102", "103.5", "10"],  # newest
            ["2000", "102", "103", "101", "102.5", "9"],
            ["1000", "100", "101", "99", "100.5", "8"],    # oldest
        ]}
        with patch("data_engine.requests.get", return_value=self._mock_response(payload=payload)) as mock_get:
            df = fetch_okx_klines("BTCUSDT", interval="1h", limit=300)
            self.assertIsNotNone(df)
            self.assertEqual(len(df), 3)
            # Reversed to oldest-first: first row's open should be 100.
            self.assertAlmostEqual(df["open"].iloc[0], 100.0)
            self.assertAlmostEqual(df["open"].iloc[-1], 103.0)
            self.assertTrue((df["taker_buy_volume"] == 0.0).all())
            # limit capped to OKX's 100-per-request max.
            _, kwargs = mock_get.call_args
            self.assertEqual(kwargs["params"]["limit"], 100)

    def test_http_error_returns_none(self):
        with patch("data_engine.requests.get", return_value=self._mock_response(status_code=500)):
            self.assertIsNone(fetch_okx_klines("BTCUSDT"))

    def test_empty_data_returns_none(self):
        with patch("data_engine.requests.get", return_value=self._mock_response(payload={"data": []})):
            self.assertIsNone(fetch_okx_klines("BTCUSDT"))


class TestFetchKlinesFallsBackToOkx(unittest.TestCase):
    def test_okx_used_only_after_every_binance_mirror_fails(self):
        binance_fail = Mock(status_code=500)
        with patch("data_engine.requests.get", return_value=binance_fail), \
             patch("data_engine.fetch_okx_klines") as mock_okx, \
             patch("data_engine.time.sleep"):  # skip real backoff delays in the test
            mock_okx.return_value = "OKX_FRAME"
            result = fetch_klines("BTCUSDT", interval="1h")
            self.assertEqual(result, "OKX_FRAME")
            mock_okx.assert_called_once_with("BTCUSDT", "1h", 300)

    def test_okx_not_called_when_a_binance_mirror_succeeds(self):
        ok_resp = Mock(status_code=200)
        ok_resp.json.return_value = [
            [0, "100", "101", "99", "100.5", "10", 0, 0, 0, "5", 0, 0],
        ]
        with patch("data_engine.requests.get", return_value=ok_resp), \
             patch("data_engine.fetch_okx_klines") as mock_okx:
            result = fetch_klines("BTCUSDT", interval="1h")
            self.assertIsNotNone(result)
            mock_okx.assert_not_called()


if __name__ == "__main__":
    unittest.main()
