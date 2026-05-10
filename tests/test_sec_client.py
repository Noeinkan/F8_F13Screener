"""Tests for src/core/sec_client.py — static extraction methods and CIK matching."""
import pytest
from src.core.sec_client import SECClient


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
