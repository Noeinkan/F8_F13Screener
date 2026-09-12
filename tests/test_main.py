import logging
from unittest.mock import MagicMock

import feedparser
import pytest

from src.cli.main import FilingProcessor
from src.core.sec_client import SECFetchError


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


# ---------------------------------------------------------------------------
# SEC failures must not look like a quiet, healthy cycle
# ---------------------------------------------------------------------------

def _funds(n):
    return {f"{i:010d}": f"Fund {i}" for i in range(1, n + 1)}


def _cycle_processor(funds, monkeypatch, bootstrapped=True):
    processor, storage, dashboard_storage = _make_processor()
    processor.config = MagicMock(
        hedge_funds_cik=funds,
        submissions_recent_limit=10,
        submissions_request_delay_seconds=0,
        enable_atom_fallback=False,
    )
    processor.runtime_state = {"submissions_bootstrapped": bootstrapped}
    processor._save_runtime_state = MagicMock()
    storage.any_filing_seen.return_value = False
    dashboard_storage.has_holdings_for_accession.return_value = True

    recorded = {}
    monkeypatch.setattr("src.cli.main.notification_state.record_cycle",
                        lambda totals: recorded.update(healthy=totals))
    monkeypatch.setattr("src.cli.main.notification_state.record_cycle_degraded",
                        lambda totals, reason: recorded.update(degraded=totals, reason=reason))
    monkeypatch.setattr("src.cli.main.notification_state.record_cycle_error",
                        lambda message: recorded.update(error=message))
    return processor, storage, recorded


def _forbidden():
    return SECFetchError("HTTP 403", "https://data.sec.gov/x", status_code=403)


def test_empty_answers_from_sec_are_a_healthy_quiet_cycle(monkeypatch):
    processor, _, recorded = _cycle_processor(_funds(4), monkeypatch)
    processor.sec_client.fetch_recent_13f_for_cik.return_value = []

    processor.process_filings_cycle()

    assert "healthy" in recorded and "degraded" not in recorded


def test_sec_blocking_the_server_is_recorded_as_degraded_with_the_reason(monkeypatch):
    processor, _, recorded = _cycle_processor(_funds(4), monkeypatch)
    processor.sec_client.fetch_recent_13f_for_cik.side_effect = _forbidden()

    processor.process_filings_cycle()

    assert "healthy" not in recorded
    assert recorded["reason"] == "SEC non raggiungibile: 4/4 fondi falliti, ultimo errore HTTP 403"
    assert recorded["degraded"]["fetch_failed"] == 4


def test_a_few_failing_funds_do_not_mark_the_cycle_unhealthy(monkeypatch):
    processor, _, recorded = _cycle_processor(_funds(4), monkeypatch)
    processor.sec_client.fetch_recent_13f_for_cik.side_effect = [_forbidden(), [], [], []]

    processor.process_filings_cycle()

    assert "healthy" in recorded
    assert recorded["healthy"]["fetch_failed"] == 1


def test_half_the_funds_failing_is_degraded(monkeypatch):
    processor, _, recorded = _cycle_processor(_funds(4), monkeypatch)
    processor.sec_client.fetch_recent_13f_for_cik.side_effect = [_forbidden(), [], _forbidden(), []]

    processor.process_filings_cycle()

    assert "degraded" in recorded


def test_circuit_breaker_stops_the_cycle_after_consecutive_failures(monkeypatch):
    processor, _, recorded = _cycle_processor(_funds(58), monkeypatch)
    processor.sec_client.fetch_recent_13f_for_cik.side_effect = _forbidden()

    stats = processor.process_submissions()

    threshold = FilingProcessor.SEC_CIRCUIT_BREAKER_THRESHOLD
    assert processor.sec_client.fetch_recent_13f_for_cik.call_count == threshold
    assert stats["fetch_failed"] == threshold
    assert stats["funds_skipped"] == 58 - threshold
    reason = FilingProcessor._sec_outage_reason(stats)
    assert "58/58 fondi non controllati" in reason
    assert "HTTP 403" in reason


def test_a_success_resets_the_consecutive_failure_count(monkeypatch):
    processor, _, _ = _cycle_processor(_funds(10), monkeypatch)
    threshold = FilingProcessor.SEC_CIRCUIT_BREAKER_THRESHOLD
    pattern = ([_forbidden()] * (threshold - 1) + [[]]) * 2
    processor.sec_client.fetch_recent_13f_for_cik.side_effect = pattern

    stats = processor.process_submissions()

    assert processor.sec_client.fetch_recent_13f_for_cik.call_count == 10
    assert stats["funds_skipped"] == 0


def test_one_failing_filing_does_not_abort_the_other_funds(monkeypatch, caplog):
    processor, storage, recorded = _cycle_processor(_funds(3), monkeypatch)
    processor.sec_client.fetch_recent_13f_for_cik.side_effect = lambda cik, max_entries: [
        {"accession_number": f"ACC-{cik}", "filing_date": "2026-09-11", "filing_url": "u"}
    ]
    calls = []

    def _seen(candidates):
        calls.append(candidates)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        return True

    storage.any_filing_seen.side_effect = _seen

    with caplog.at_level(logging.ERROR):
        processor.process_filings_cycle()

    assert len(calls) == 3, "the remaining funds must still be checked"
    assert recorded["healthy"]["errors"] == 1
    assert "ACC-0000000001" in caplog.text and "Fund 1" in caplog.text


def test_bootstrap_is_not_completed_when_sec_did_not_answer(monkeypatch):
    processor, _, _ = _cycle_processor(_funds(4), monkeypatch, bootstrapped=False)
    processor.sec_client.fetch_recent_13f_for_cik.side_effect = _forbidden()

    processor.process_submissions()

    assert processor.runtime_state.get("submissions_bootstrapped") is False
    processor._save_runtime_state.assert_not_called()


def test_bootstrap_completes_on_a_healthy_cycle(monkeypatch):
    processor, _, _ = _cycle_processor(_funds(2), monkeypatch, bootstrapped=False)
    processor.sec_client.fetch_recent_13f_for_cik.return_value = []

    processor.process_submissions()

    assert processor.runtime_state["submissions_bootstrapped"] is True


def test_feed_outage_is_logged_not_raised():
    processor, storage, _ = _make_processor()
    processor.config = MagicMock(rss_url="https://sec.gov/rss")
    processor.sec_client.fetch_13f_feed.side_effect = SECFetchError("HTTP 503")

    assert processor.process_feed_fallback() is None
    storage.any_filing_seen.assert_not_called()


@pytest.mark.parametrize("stats", [None, {}, {"funds_total": 0, "fetch_failed": 0}])
def test_outage_reason_is_none_without_failures(stats):
    assert FilingProcessor._sec_outage_reason(stats) is None
