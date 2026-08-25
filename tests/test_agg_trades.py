import unittest
from unittest.mock import patch, Mock
from data_engine import fetch_recent_agg_trades


class TestFetchRecentAggTrades(unittest.TestCase):
    def _mock_response(self, status_code=200, payload=None):
        resp = Mock()
        resp.status_code = status_code
        resp.json.return_value = payload if payload is not None else []
        return resp

    def test_successful_fetch_returns_dataframe_with_expected_columns(self):
        payload = [
            {"p": "100.5", "q": "1.2", "m": False},
            {"p": "100.6", "q": "0.8", "m": True},
        ]
        with patch("data_engine.requests.get", return_value=self._mock_response(payload=payload)):
            df = fetch_recent_agg_trades("BTCUSDT")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 2)
        self.assertListEqual(list(df.columns), ["price", "qty", "is_buyer_maker"])
        self.assertAlmostEqual(df["price"].iloc[0], 100.5)
        self.assertEqual(df["is_buyer_maker"].iloc[1], True)

    def test_empty_response_returns_none(self):
        with patch("data_engine.requests.get", return_value=self._mock_response(payload=[])):
            self.assertIsNone(fetch_recent_agg_trades("BTCUSDT"))

    def test_http_error_falls_through_all_mirrors_then_returns_none(self):
        with patch("data_engine.requests.get", return_value=self._mock_response(status_code=451)) as mock_get:
            result = fetch_recent_agg_trades("BTCUSDT")
        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 3)  # tries all 3 mirrors

    def test_network_exception_does_not_raise(self):
        import requests
        with patch("data_engine.requests.get", side_effect=requests.RequestException("boom")):
            result = fetch_recent_agg_trades("BTCUSDT")
        self.assertIsNone(result)

    def test_minutes_capped_at_55_for_binance_1_hour_window_limit(self):
        payload = [{"p": "1", "q": "1", "m": False}]
        with patch("data_engine.requests.get", return_value=self._mock_response(payload=payload)) as mock_get:
            fetch_recent_agg_trades("BTCUSDT", minutes=120)
        _, kwargs = mock_get.call_args
        span_ms = kwargs["params"]["endTime"] - kwargs["params"]["startTime"]
        self.assertLessEqual(span_ms, 55 * 60 * 1000)


if __name__ == "__main__":
    unittest.main()
