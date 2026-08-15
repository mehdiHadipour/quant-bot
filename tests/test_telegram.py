import unittest
from unittest.mock import patch, MagicMock

import config
import telegram


class TestTelegramAlert(unittest.TestCase):
    def setUp(self):
        self._orig_token = config.TELEGRAM_TOKEN
        self._orig_chat = config.TELEGRAM_CHAT
        config.TELEGRAM_TOKEN = "test-token"
        config.TELEGRAM_CHAT = "test-chat"
        telegram.TELEGRAM_TOKEN = "test-token"
        telegram.TELEGRAM_CHAT = "test-chat"

    def tearDown(self):
        config.TELEGRAM_TOKEN = self._orig_token
        config.TELEGRAM_CHAT = self._orig_chat
        telegram.TELEGRAM_TOKEN = self._orig_token
        telegram.TELEGRAM_CHAT = self._orig_chat

    @patch("telegram.requests.post")
    def test_normal_message_sent_with_html_parse_mode(self, mock_post):
        """Regression test for the v27.2 bug: intentional <b> formatting
        must actually render as bold, not literal escaped text — so
        parse_mode=HTML must be set and the message must NOT be
        html-escaped before sending."""
        mock_post.return_value = MagicMock(status_code=200)
        telegram.send_telegram_alert("<b>سیگنال جدید</b> - BTCUSDT")

        self.assertEqual(mock_post.call_count, 1)
        sent_json = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_json["parse_mode"], "HTML")
        # Must be the literal tag, not the escaped "&lt;b&gt;" entity.
        self.assertIn("<b>سیگنال جدید</b>", sent_json["text"])

    @patch("telegram.requests.post")
    def test_falls_back_to_plain_text_only_when_telegram_rejects_html_parse(self, mock_post):
        """If Telegram itself reports it couldn't parse the HTML (e.g. an
        exception message embedded a stray '<'), retry once as plain text
        so the alert still gets delivered instead of being lost."""
        html_fail = MagicMock(status_code=400, text="Bad Request: can't parse entities")
        plain_ok = MagicMock(status_code=200)
        mock_post.side_effect = [html_fail, plain_ok]

        telegram.send_telegram_alert("<b>خطا</b>: weird <exception> text")

        self.assertEqual(mock_post.call_count, 2)
        first_call_json = mock_post.call_args_list[0].kwargs["json"]
        second_call_json = mock_post.call_args_list[1].kwargs["json"]
        self.assertEqual(first_call_json["parse_mode"], "HTML")
        self.assertNotIn("parse_mode", second_call_json)

    @patch("telegram.requests.post")
    def test_non_parse_errors_do_not_trigger_plain_text_fallback(self, mock_post):
        """A non-parse-related failure (e.g. rate limiting) should just
        retry normally, not immediately fall back to plain text."""
        mock_post.return_value = MagicMock(status_code=429, text="Too Many Requests")
        telegram.send_telegram_alert("<b>test</b>")
        # 3 normal retry attempts, never a plain-text fallback call.
        self.assertEqual(mock_post.call_count, 3)
        for call in mock_post.call_args_list:
            self.assertEqual(call.kwargs["json"]["parse_mode"], "HTML")


if __name__ == "__main__":
    unittest.main()
