"""Tests for src/core/notifier.py — pure message formatting (no network)."""
import json

import pytest
from unittest.mock import patch, MagicMock
from src.core.notifier import TelegramNotifier


# ---------------------------------------------------------------------------
# _format_date (static, pure)
# ---------------------------------------------------------------------------

class TestFormatDate:

    def test_full_iso_datetime(self):
        result = TelegramNotifier._format_date("2026-05-10T21:02:34")
        assert "10" in result
        assert "mag" in result   # May in Italian
        assert "2026" in result
        assert "21:02" in result

    def test_all_months_italian(self):
        months_it = ["gen", "feb", "mar", "apr", "mag", "giu",
                     "lug", "ago", "set", "ott", "nov", "dic"]
        for i, name in enumerate(months_it, start=1):
            date_str = f"2026-{i:02d}-15T10:00:00"
            result = TelegramNotifier._format_date(date_str)
            assert name in result, f"Month {i} expected '{name}', got: {result}"

    def test_day_zero_padded(self):
        result = TelegramNotifier._format_date("2026-05-03T08:05:00")
        assert "03" in result

    def test_invalid_string_passthrough(self):
        bad = "not-a-date"
        assert TelegramNotifier._format_date(bad) == bad

    def test_none_passthrough(self):
        result = TelegramNotifier._format_date(None)
        assert result is None

    def test_date_only_no_time(self):
        result = TelegramNotifier._format_date("2026-01-15")
        assert "gen" in result
        assert "2026" in result


# ---------------------------------------------------------------------------
# send_filing_alert — message construction (mocked send_message)
# ---------------------------------------------------------------------------

class TestSendFilingAlert:

    def _make_notifier(self):
        return TelegramNotifier(
            bot_token="fake_token",
            chat_id="123456",
            max_retries=1,
            retry_delay=0,
            dashboard_base_url="http://dash.test:5173",
        )

    def test_basic_alert_contains_fund_name(self):
        notifier = self._make_notifier()
        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.send_filing_alert("Berkshire", "Berkshire Inc", "2026-05-01T00:00:00", "https://sec.gov/x")
            msg = mock_send.call_args[0][0]
            assert "Berkshire" in msg

    def test_alert_links_to_dashboard_and_edgar(self):
        notifier = self._make_notifier()
        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.send_filing_alert("Fund", "Fund Inc", "2026-05-01T00:00:00", "https://sec.gov/x")
            urls = [url for _, url in mock_send.call_args.kwargs["buttons"]]
            assert urls[0].startswith("http://dash.test:5173/fund-analysis?fund=Fund")
            assert urls[1] == "https://sec.gov/x"

    def test_alert_warns_when_holdings_missing(self):
        notifier = self._make_notifier()
        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.send_filing_alert("Fund", "Fund Inc", "2026-05-01T00:00:00", "https://sec.gov/x",
                                       holdings_saved=False)
            msg = mock_send.call_args[0][0]
            assert "holdings non ancora elaborate" in msg

    def test_alert_is_a_headline_not_a_full_diff(self):
        """The detail belongs in the dashboard; the message carries counts and one top move."""
        notifier = self._make_notifier()
        diff = {
            "new_positions": [
                {"cusip": "X", "issuer_name": "Apple", "shares": 100, "value_usd": 5000},
                {"cusip": "Y", "issuer_name": "Tiny", "shares": 10, "value_usd": 500},
            ],
            "closed_positions": [],
            "increased": [],
            "decreased": [],
        }
        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.send_filing_alert("Fund", "Fund Inc", "2026-05-01T00:00:00", "https://sec.gov/x",
                                       portfolio_diff=diff)
            msg = mock_send.call_args[0][0]
            assert "+2 nuove" in msg
            # The per-position listing stays out of Telegram entirely.
            assert "NUOVE POSIZIONI" not in msg
            assert "Apple" in msg
            assert "Tiny" not in msg

    def test_no_change_summary_when_diff_empty(self):
        notifier = self._make_notifier()
        empty = {"new_positions": [], "closed_positions": [], "increased": [], "decreased": []}
        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.send_filing_alert("Fund", "Fund Inc", "2026-05-01T00:00:00", "https://sec.gov/x",
                                       holdings_saved=True, portfolio_diff=empty)
            msg = mock_send.call_args[0][0]
            assert "nessuna variazione" in msg

    def test_fund_name_with_ampersand_is_escaped(self):
        """Telegram's HTML parser rejects a bare '&', and several funds have one."""
        notifier = self._make_notifier()
        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.send_filing_alert("Brown & Co", "Brown & Co", "2026-05-01T00:00:00", "https://sec.gov/x")
            msg = mock_send.call_args[0][0]
            assert "Brown &amp; Co" in msg

    def test_returns_send_message_result(self):
        notifier = self._make_notifier()
        with patch.object(notifier, "send_message", return_value=False):
            result = notifier.send_filing_alert("F", "F", "2026-01-01T00:00:00", "https://x.com")
            assert result is False


# ---------------------------------------------------------------------------
# send_message — payload (mocked HTTP)
# ---------------------------------------------------------------------------

class TestSendMessagePayload:

    def _make_notifier(self):
        return TelegramNotifier("fake", "123", max_retries=1, retry_delay=0)

    @staticmethod
    def _response(status, text=""):
        response = MagicMock()
        response.status_code = status
        response.text = text
        return response

    def test_buttons_and_silence_reach_telegram(self):
        notifier = self._make_notifier()
        with patch("src.core.notifier.requests.post", return_value=self._response(200)) as post, \
                patch("src.core.notifier.save_message_to_viewer"):
            assert notifier.send_message("hi", buttons=[("EDGAR", "https://sec.gov/x")], silent=True)

        payload = post.call_args.kwargs["data"]
        assert payload["disable_notification"] is True
        markup = json.loads(payload["reply_markup"])
        assert markup == {"inline_keyboard": [[{"text": "EDGAR", "url": "https://sec.gov/x"}]]}

    def test_a_plain_message_is_audible_and_has_no_buttons(self):
        notifier = self._make_notifier()
        with patch("src.core.notifier.requests.post", return_value=self._response(200)) as post, \
                patch("src.core.notifier.save_message_to_viewer"):
            notifier.send_message("hi")

        payload = post.call_args.kwargs["data"]
        assert "disable_notification" not in payload
        assert "reply_markup" not in payload

    def test_refused_buttons_fall_back_to_text_links(self):
        """Telegram rejects the whole message over a button URL it dislikes."""
        notifier = self._make_notifier()
        responses = [self._response(400, "Bad Request: Wrong HTTP URL"), self._response(200)]
        with patch("src.core.notifier.requests.post", side_effect=responses) as post, \
                patch("src.core.notifier.save_message_to_viewer"):
            assert notifier.send_message("hi", buttons=[("Dashboard", "http://127.0.0.1:5173/")]) is True

        retry = post.call_args_list[1].kwargs["data"]
        assert "reply_markup" not in retry
        assert "<a href='http://127.0.0.1:5173/'>Dashboard</a>" in retry["text"]


# ---------------------------------------------------------------------------
# send_daily_summary — message construction (mocked send_message)
# ---------------------------------------------------------------------------

class TestSendDailySummary:

    def _make_notifier(self):
        return TelegramNotifier("fake", "123", max_retries=1, retry_delay=0)

    def test_contains_date_and_count(self):
        notifier = self._make_notifier()
        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.send_daily_summary("2026-05-10", 42, [])
            msg = mock_send.call_args[0][0]
            assert "2026-05-10" in msg
            assert "42" in msg

    def test_top_filers_listed(self):
        notifier = self._make_notifier()
        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.send_daily_summary("2026-05-10", 10, [("Vanguard", 5), ("BlackRock", 3)])
            msg = mock_send.call_args[0][0]
            assert "Vanguard" in msg
            assert "BlackRock" in msg
