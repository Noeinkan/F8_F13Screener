import logging
from unittest.mock import MagicMock

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