"""Tests for src/core/sec_client.py — static extraction methods and CIK matching."""
import json
from unittest.mock import MagicMock

import pytest
import requests

from src.core.sec_client import SECClient, SECFetchError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_client():
    return SECClient(user_agent="test@example.com", max_retries=1, retry_delay=0)


# ---------------------------------------------------------------------------
# extract_cik_from_link
# ---------------------------------------------------------------------------

class TestExtractCikFromLink:

    def test_data_path_pattern(self):
        url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001234567&type=13F-HR"
        assert SECClient.extract_cik_from_link(url) == "0001234567"

    def test_data_url_pattern(self):
        url = "https://www.sec.gov/Archives/edgar/data/1067983/000106798326000001/0001067983-26-000001-index.htm"
        assert SECClient.extract_cik_from_link(url) == "1067983"

    def test_cik_query_param(self):
        url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=987654&type=13F-HR"
        assert SECClient.extract_cik_from_link(url) == "987654"

    def test_invalid_url_returns_na(self):
        assert SECClient.extract_cik_from_link("https://example.com/no-cik-here") == "N/A"

    def test_empty_string_returns_na(self):
        assert SECClient.extract_cik_from_link("") == "N/A"

    def test_numeric_cik_preserved(self):
        url = "https://www.sec.gov/Archives/edgar/data/0001234567/file.xml"
        cik = SECClient.extract_cik_from_link(url)
        assert cik.isdigit()


# ---------------------------------------------------------------------------
# extract_accession_number
# ---------------------------------------------------------------------------

class TestExtractAccessionNumber:

    def test_standard_accession_pattern(self):
        url = "https://www.sec.gov/Archives/edgar/data/1067983/000106798326000001/0001067983-26-000001-index.htm"
        result = SECClient.extract_accession_number(url)
        assert result == "0001067983-26-000001"

    def test_accession_in_query_string(self):
        url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&accession=1234567890-23-999999"
        result = SECClient.extract_accession_number(url)
        assert result == "1234567890-23-999999"

    def test_missing_accession_returns_na(self):
        assert SECClient.extract_accession_number("https://example.com/nope") == "N/A"

    def test_empty_string_returns_na(self):
        assert SECClient.extract_accession_number("") == "N/A"

    def test_format_is_correct(self):
        url = "https://www.sec.gov/Archives/edgar/data/123/0001234567890-24-012345-index.htm"
        result = SECClient.extract_accession_number(url)
        # Should match \d{10}-\d{2}-\d{6}
        import re
        assert re.fullmatch(r"\d{10}-\d{2}-\d{6}", result)


# ---------------------------------------------------------------------------
# extract_filer_name_from_title
# ---------------------------------------------------------------------------

class TestExtractFilerNameFromTitle:

    def test_standard_format(self):
        title = "13F-HR - BERKSHIRE HATHAWAY INC (0001067983) (Filer)"
        result = SECClient.extract_filer_name_from_title(title)
        assert "BERKSHIRE HATHAWAY" in result
        assert "0001067983" not in result

    def test_strips_cik_suffix(self):
        title = "13F-HR - BRIDGEWATER ASSOCIATES (0001350144) (Filer)"
        result = SECClient.extract_filer_name_from_title(title)
        assert result.strip() == "BRIDGEWATER ASSOCIATES"

    def test_no_13fhr_prefix_fallback(self):
        title = "SOME FUND (0001234567) (Filer)"
        result = SECClient.extract_filer_name_from_title(title)
        assert result  # Should return something non-empty

    def test_empty_title_returns_something(self):
        result = SECClient.extract_filer_name_from_title("")
        assert isinstance(result, str)

    def test_preserves_fund_name_with_spaces(self):
        title = "13F-HR - TWO SIGMA INVESTMENTS LP (0001179392) (Filer)"
        result = SECClient.extract_filer_name_from_title(title)
        assert "TWO SIGMA" in result


# ---------------------------------------------------------------------------
# should_notify
# ---------------------------------------------------------------------------

class TestShouldNotify:

    CIK_FILTER = {
        "0001067983": "Berkshire Hathaway (Buffett)",
        "0001350144": "Bridgewater Associates (Dalio)",
    }

    def test_matching_cik_with_leading_zeros(self):
        client = make_client()
        url = "https://www.sec.gov/Archives/edgar/data/1067983/file.htm"
        match, name = client.should_notify("Berkshire", url, self.CIK_FILTER)
        assert match is True
        assert "Berkshire" in name

    def test_no_match_returns_false(self):
        client = make_client()
        url = "https://www.sec.gov/Archives/edgar/data/9999999/file.htm"
        match, name = client.should_notify("Unknown Fund", url, self.CIK_FILTER)
        assert match is False
        assert name == ""

    def test_leading_zeros_normalized(self):
        client = make_client()
        # Filter has '0001350144', URL has '1350144' (no leading zeros)
        url = "https://www.sec.gov/Archives/edgar/data/1350144/file.htm"
        match, name = client.should_notify("Bridgewater", url, self.CIK_FILTER)
        assert match is True

    def test_empty_filter_notifies_all(self):
        client = make_client()
        url = "https://www.sec.gov/Archives/edgar/data/9999999/file.htm"
        match, name = client.should_notify("Any Fund", url, {})
        assert match is True
        assert name == "ALL"

    def test_bad_url_returns_false(self):
        client = make_client()
        match, name = client.should_notify("Unknown", "https://example.com/no-cik", self.CIK_FILTER)
        assert match is False

    def test_both_cik_formats_in_filter_match(self):
        client = make_client()
        # Filter without leading zeros
        cik_filter = {"1067983": "Berkshire Hathaway"}
        url = "https://www.sec.gov/Archives/edgar/data/1067983/file.htm"
        match, name = client.should_notify("Berkshire", url, cik_filter)
        assert match is True


# ---------------------------------------------------------------------------
# Retry policy - no real network: the session is a mock, sleep is recorded
# ---------------------------------------------------------------------------

SUBMISSIONS = {
    "name": "BERKSHIRE HATHAWAY INC",
    "filings": {"recent": {
        "form": ["13F-HR", "10-K"],
        "accessionNumber": ["0000950123-26-000001", "0000950123-26-000002"],
        "filingDate": ["2026-08-14", "2026-02-01"],
        "acceptanceDateTime": ["2026-08-14T16:01:00.000Z", ""],
        "primaryDocument": ["xslForm13F_X02/primary_doc.xml", "10k.htm"],
        "reportDate": ["2026-06-30", "2025-12-31"],
    }},
}

ATOM = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>13F-HR - X</title></entry></feed>'


def _response(status=200, body=b"", content_type="application/json", headers=None):
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.content = body
    response.headers = {"Content-Type": content_type, **(headers or {})}

    def _json():
        return json.loads(body.decode("utf-8"))

    response.json.side_effect = _json
    return response


def _json_response(payload=SUBMISSIONS, status=200):
    return _response(status, json.dumps(payload).encode("utf-8"))


def _client(*outcomes, max_retries=3):
    """A client whose session returns (or raises) ``outcomes`` in order."""
    sleeps = []
    client = SECClient(
        "test test@example.com",
        max_retries=max_retries,
        sleep=sleeps.append,
        jitter=lambda low, high: high,  # deterministic: always the top of the range
    )
    client._session = MagicMock()
    client._session.get.side_effect = list(outcomes)
    return client, sleeps


class TestRetryPolicy:

    def test_success_needs_one_request_and_no_sleep(self):
        client, sleeps = _client(_json_response())

        filings = client.fetch_recent_13f_for_cik("0001067983")

        assert [f["accession_number"] for f in filings] == ["0000950123-26-000001"]
        assert filings[0]["report_date"] == "2026-06-30"
        assert sleeps == []

    def test_a_fund_with_no_13f_is_an_empty_list_not_an_error(self):
        payload = {"name": "X", "filings": {"recent": {"form": ["10-K"]}}}
        client, _ = _client(_json_response(payload))

        assert client.fetch_recent_13f_for_cik("1") == []

    @pytest.mark.parametrize("status", [403, 404, 400])
    def test_client_errors_are_not_retried(self, status):
        client, sleeps = _client(_response(status, b"denied", "text/html"))

        with pytest.raises(SECFetchError) as err:
            client.fetch_recent_13f_for_cik("0001067983")

        assert err.value.status_code == status
        assert err.value.reason == f"HTTP {status}"
        assert client._session.get.call_count == 1
        assert sleeps == []

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_throttle_and_server_errors_are_retried_then_raise(self, status):
        client, sleeps = _client(*[_response(status, b"")] * 3)

        with pytest.raises(SECFetchError) as err:
            client.fetch_recent_13f_for_cik("0001067983")

        assert client._session.get.call_count == 3
        assert err.value.reason == f"HTTP {status}"
        assert len(sleeps) == 2, "no sleep after the last attempt"

    def test_backoff_is_exponential_and_capped(self):
        client, sleeps = _client(*[_response(503)] * 6, max_retries=6)

        with pytest.raises(SECFetchError):
            client.fetch_recent_13f_for_cik("1")

        # base 2 s doubling, jitter pinned to the top of the range, cap 30 s.
        assert sleeps == [2.0, 4.0, 8.0, 16.0, 30.0]

    def test_jitter_never_goes_below_half_the_backoff(self):
        client, sleeps = _client(_response(503), _json_response())
        client._jitter = lambda low, high: low

        client.fetch_recent_13f_for_cik("1")

        assert sleeps == [1.0]

    def test_retry_after_seconds_is_honoured(self):
        client, sleeps = _client(_response(429, headers={"Retry-After": "7"}), _json_response())

        assert client.fetch_recent_13f_for_cik("1")
        assert sleeps == [7.0]

    def test_retry_after_is_capped(self):
        client, sleeps = _client(_response(503, headers={"Retry-After": "3600"}), _json_response())

        client.fetch_recent_13f_for_cik("1")

        assert sleeps == [30.0]

    def test_retry_after_http_date_falls_back_to_backoff(self):
        client, sleeps = _client(
            _response(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            _json_response(),
        )

        client.fetch_recent_13f_for_cik("1")

        assert sleeps == [2.0]

    @pytest.mark.parametrize("exc, reason", [
        (requests.exceptions.ConnectTimeout("slow"), "timeout"),
        (requests.exceptions.ReadTimeout("slow"), "timeout"),
        (requests.exceptions.ConnectionError("refused"), "connessione fallita"),
    ])
    def test_transport_errors_are_retried(self, exc, reason):
        client, sleeps = _client(exc, exc, exc)

        with pytest.raises(SECFetchError) as err:
            client.fetch_recent_13f_for_cik("1")

        assert err.value.reason == reason
        assert client._session.get.call_count == 3

    def test_transient_failure_then_success_returns_the_filings(self):
        client, sleeps = _client(requests.exceptions.ConnectionError("blip"), _json_response())

        assert len(client.fetch_recent_13f_for_cik("1")) == 1
        assert len(sleeps) == 1

    def test_html_error_page_with_200_is_a_failure_not_an_empty_answer(self):
        page = b"<!DOCTYPE html><html><body>Service Unavailable</body></html>"
        client, _ = _client(*[_response(200, page, "text/html; charset=utf-8")] * 3)

        with pytest.raises(SECFetchError) as err:
            client.fetch_recent_13f_for_cik("1")

        assert "HTML" in err.value.reason
        assert client._session.get.call_count == 3

    def test_html_body_is_detected_even_with_a_json_content_type(self):
        page = b"  <html><body>Request Rate Threshold Exceeded</body></html>"
        client, _ = _client(_response(200, page), _json_response())

        assert len(client.fetch_recent_13f_for_cik("1")) == 1
        assert client._session.get.call_count == 2

    def test_truncated_json_is_retried(self):
        client, sleeps = _client(_response(200, b'{"name": "X", "fil'), _json_response())

        assert len(client.fetch_recent_13f_for_cik("1")) == 1
        assert len(sleeps) == 1

    def test_json_that_is_not_an_object_is_a_failure(self):
        client, _ = _client(*[_response(200, b"[]")] * 3)

        with pytest.raises(SECFetchError, match="JSON non valido"):
            client.fetch_recent_13f_for_cik("1")

    def test_legacy_retry_delay_zero_means_no_waiting(self):
        """``SECClient(ua, max_retries, retry_delay)`` still works positionally."""
        sleeps = []
        client = SECClient("ua", 2, 0, sleep=sleeps.append)
        client._session = MagicMock()
        client._session.get.side_effect = [_response(503), _json_response()]

        client.fetch_recent_13f_for_cik("1")

        assert sleeps == [0.0]


class TestFeedFetch:

    def test_feed_is_parsed(self):
        client, _ = _client(_response(200, ATOM, "application/atom+xml"))

        feed = client.fetch_13f_feed("https://www.sec.gov/rss")

        assert len(feed.entries) == 1

    def test_feed_outage_raises_instead_of_returning_an_empty_feed(self):
        client, _ = _client(*[_response(503)] * 3)

        with pytest.raises(SECFetchError):
            client.fetch_13f_feed("https://www.sec.gov/rss")

    def test_feed_html_page_is_a_failure(self):
        page = b"<html><body>maintenance</body></html>"
        client, _ = _client(*[_response(200, page, "text/html")] * 3)

        with pytest.raises(SECFetchError, match="HTML"):
            client.fetch_13f_feed("https://www.sec.gov/rss")
