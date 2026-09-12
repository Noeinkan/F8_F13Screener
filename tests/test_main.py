import logging
from unittest.mock import MagicMock

import feedparser

from src.cli.main import FilingProcessor


def _make_processor():
    processor = FilingProcessor.__new__(FilingProcessor)
    processor.logger = logging.getLogger("test_filing_processor")
    processor.sec_client = MagicMock()
    processor.parser = MagicMock()
    storage = MagicMock()
    dashboard_storage = MagicMock()
    processor.storage = storage
    processor.dashboard_storage = dashboard_storage
    return processor, storage, dashboard_storage


def _configure_successful_parse(processor, storage, dashboard_storage):
    holdings = [{
        "issuer_name": "Apple Inc",
        "share_class": "COM",
        "cusip": "037833100",
        "value": 5000,
        "shares": 1000,
    }]
    processor.sec_client.extract_accession_number.return_value = "ACC-001"
    processor.parser.get_information_table_url.return_value = "https://sec.gov/info.xml"
    processor.parser.parse_information_table.return_value = holdings
    storage.get_latest_accessions_for_fund.return_value = []
    storage.save_holdings.return_value = len(holdings)
    dashboard_storage.save_holdings.return_value = len(holdings)
    return holdings


def test_process_holdings_returns_true_when_sqlite_and_duckdb_save():
    processor, storage, dashboard_storage = _make_processor()
    _configure_successful_parse(processor, storage, dashboard_storage)

    holdings_saved, portfolio_diff = processor._process_holdings(
        "https://sec.gov/filing",
        "Filer LLC",
        "Fund LP",
        "0001234567",
        "2026-05-15",
    )

    assert holdings_saved is True
    assert portfolio_diff is None
    storage.save_holdings.assert_called_once()
    dashboard_storage.save_holdings.assert_called_once()


def test_process_holdings_diff_names_the_two_filings_it_compared():
    """The alert deep-links to exactly this comparison in the dashboard."""
    processor, storage, dashboard_storage = _make_processor()
    _configure_successful_parse(processor, storage, dashboard_storage)
    storage.get_latest_accessions_for_fund.return_value = [{"accession_number": "ACC-000"}]
    storage.get_holdings_by_accession.side_effect = lambda acc: {
        "037833100": {"cusip": "037833100", "issuer_name": "Apple Inc", "shares": 500 if acc == "ACC-000" else 1000,
                      "value_usd": 5000},
    }

    _, portfolio_diff = processor._process_holdings(
        "https://sec.gov/filing", "Filer LLC", "Fund LP", "0001234567", "2026-05-15",
    )

    assert portfolio_diff["from_accession_number"] == "ACC-000"
    assert portfolio_diff["to_accession_number"] == "ACC-001"


def test_dispatch_queues_form_and_report_date_during_a_wave(monkeypatch):
    processor, _, _ = _make_processor()
    processor.config = MagicMock(enable_digest=True, digest_days_before=2, digest_days_after=7)
    queued = {}
    monkeypatch.setattr("src.cli.main.filing_calendar.active_window", lambda *a, **k: object())
    monkeypatch.setattr("src.cli.main.notification_state.queue_alert", lambda key, payload: queued.update(payload))

    processor._dispatch_alert("Fund", "Filer", "2026-08-14", "https://sec.gov/x", True, None, "entry",
                              form="13F-HR/A", report_date="2026-06-30")

    assert queued["form"] == "13F-HR/A"
    assert queued["report_date"] == "2026-06-30"


def test_process_holdings_fails_when_duckdb_save_raises(caplog):
    processor, storage, dashboard_storage = _make_processor()
    _configure_successful_parse(processor, storage, dashboard_storage)
    dashboard_storage.save_holdings.side_effect = RuntimeError("locked")

    with caplog.at_level(logging.ERROR):
        holdings_saved, portfolio_diff = processor._process_holdings(
            "https://sec.gov/filing",
            "Filer LLC",
            "Fund LP",
            "0001234567",
            "2026-05-15",
        )

    assert holdings_saved is False
    assert portfolio_diff is None
    assert "Salvataggio DuckDB dashboard fallito" in caplog.text
    storage.save_holdings.assert_called_once()
    dashboard_storage.save_holdings.assert_called_once()


def test_process_holdings_fails_when_duckdb_save_returns_zero(caplog):
    processor, storage, dashboard_storage = _make_processor()
    _configure_successful_parse(processor, storage, dashboard_storage)
    dashboard_storage.save_holdings.return_value = 0

    with caplog.at_level(logging.ERROR):
        holdings_saved, portfolio_diff = processor._process_holdings(
            "https://sec.gov/filing",
            "Filer LLC",
            "Fund LP",
            "0001234567",
            "2026-05-15",
        )

    assert holdings_saved is False
    assert portfolio_diff is None
    assert "Salvataggio DuckDB dashboard vuoto" in caplog.text


def test_process_holdings_succeeds_when_sqlite_save_raises(caplog):
    processor, storage, dashboard_storage = _make_processor()
    _configure_successful_parse(processor, storage, dashboard_storage)
    storage.save_holdings.side_effect = RuntimeError("sqlite locked")

    with caplog.at_level(logging.WARNING):
        holdings_saved, portfolio_diff = processor._process_holdings(
            "https://sec.gov/filing",
            "Filer LLC",
            "Fund LP",
            "0001234567",
            "2026-05-15",
        )

    assert holdings_saved is True
    assert portfolio_diff is None
    assert "Salvataggio SQLite holdings non riuscito" in caplog.text
    dashboard_storage.save_holdings.assert_called_once()


def test_process_feed_fallback_survives_empty_feed():
    """A SEC outage returns an empty FeedParserDict; `.entries` would raise."""
    processor, storage, _ = _make_processor()
    processor.config = MagicMock()
    processor.config.rss_url = "https://sec.gov/rss"
    # This is exactly what fetch_13f_feed() returns after exhausting retries.
    processor.sec_client.fetch_13f_feed.return_value = feedparser.FeedParserDict()

    # Must return without raising and without trying to read seen filings.
    processor.process_feed_fallback()

    storage.get_seen_filings.assert_not_called()
    storage.any_filing_seen.assert_not_called()


def test_needs_holdings_backfill_when_sqlite_has_accession_but_duckdb_does_not():
    processor, storage, dashboard_storage = _make_processor()
    storage.has_holdings_for_accession.return_value = True
    dashboard_storage.has_holdings_for_accession.return_value = False

    assert processor._needs_holdings_backfill("ACC-001") is True


def test_needs_holdings_backfill_when_duckdb_has_accession_even_if_sqlite_missing():
    processor, storage, dashboard_storage = _make_processor()
    storage.has_holdings_for_accession.return_value = False
    dashboard_storage.has_holdings_for_accession.return_value = True

    assert processor._needs_holdings_backfill("ACC-001") is False


def test_needs_holdings_backfill_ignores_duckdb_errors_for_retry_later(caplog):
    processor, storage, dashboard_storage = _make_processor()
    storage.has_holdings_for_accession.return_value = True
    dashboard_storage.has_holdings_for_accession.side_effect = RuntimeError("locked")

    with caplog.at_level(logging.WARNING):
        needs_backfill = processor._needs_holdings_backfill("ACC-001")

    assert needs_backfill is False
    assert "DuckDB dashboard temporaneamente non accessibile" in caplog.text

# ---------------------------------------------------------------------------
# Cross-path dedup: the two discovery routes must recognise each other's rows
# ---------------------------------------------------------------------------

ACC = "0000908834-26-000432"


def test_seen_candidates_cover_padded_and_unpadded_cik():
    """The feed reads '909661' from the URL, submissions uses '0000909661'.

    Unless both spellings are probed the two paths never see each other's rows
    and every tracked filing is alerted twice - which is exactly what happened
    on 14 August 2026 (88 messages for 42 funds).
    """
    candidates = FilingProcessor._build_seen_candidates("feed", "909661", ACC, "fallback")

    assert f"filing:909661:{ACC}" in candidates
    assert f"filing:0000909661:{ACC}" in candidates
    assert f"submissions:0000909661:{ACC}" in candidates
    assert f"feed:909661:{ACC}" in candidates


def test_seen_candidates_match_across_the_two_paths():
    from_feed = FilingProcessor._build_seen_candidates("feed", "909661", ACC, "a")
    from_submissions = FilingProcessor._build_seen_candidates("submissions", "0000909661", ACC, "b")

    assert from_feed & from_submissions, "the two discovery paths must share a candidate"


def test_entry_id_is_written_in_one_canonical_spelling():
    from_feed = FilingProcessor._build_entry_id("feed", "909661", ACC, "a")
    from_submissions = FilingProcessor._build_entry_id("submissions", "0000909661", ACC, "b")

    assert from_feed == from_submissions == f"filing:0000909661:{ACC}"


def test_entry_id_falls_back_when_accession_unknown():
    assert FilingProcessor._build_entry_id("feed", "909661", "N/A", "the-fallback") == "the-fallback"
    assert FilingProcessor._build_entry_id("feed", "909661", "", "the-fallback") == "the-fallback"


def test_cik_variants_leaves_non_numeric_alone():
    assert FilingProcessor._cik_variants("N/A") == {"N/A"}
    assert FilingProcessor._cik_variants("") == {""}


def test_seen_candidates_without_accession_use_the_fallback():
    candidates = FilingProcessor._build_seen_candidates("feed", "909661", "N/A", "raw-entry-id")
    assert candidates == {"raw-entry-id", "feed:raw-entry-id"}
