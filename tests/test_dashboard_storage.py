from pathlib import Path

import duckdb
import pytest

from src.cli.process_historical_13f import (
    build_holdings_consistency_report,
    select_filings_missing_canonical_holdings,
)
from src.core import dashboard_storage as dashboard_storage_module
from src.core.dashboard_storage import DashboardStorage


def _holding(issuer="Apple Inc", cusip="037833100"):
    return {
        "issuer_name": issuer,
        "share_class": "COM",
        "cusip": cusip,
        "figi": "",
        "value_x1000": "5000",
        "value": 5000,
        "shares_raw": "1000",
        "shares": 1000,
        "sh_prn": "SH",
        "put_call": "",
        "investment_discretion": "SOLE",
        "other_manager": "",
        "other_managers_raw": "",
        "all_columns_raw": "",
        "voting_authority_sole": 1000,
        "voting_authority_shared": 0,
        "voting_authority_none": 0,
    }


def test_save_holdings_replaces_existing_accession_atomically(tmp_path: Path):
    storage = DashboardStorage(tmp_path / "dashboard.duckdb")

    storage.save_holdings(
        [_holding("Apple Inc", "037833100"), _holding("NVIDIA Corp", "67066G104")],
        "Test Fund",
        "0000000001",
        "2026-05-15",
        "ACC-001",
        "https://sec.gov/acc-001",
    )
    storage.save_holdings(
        [_holding("Microsoft Corp", "594918104")],
        "Test Fund",
        "0000000001",
        "2026-05-15",
        "ACC-001",
        "https://sec.gov/acc-001",
    )

    counts = storage.get_accession_row_counts(["ACC-001", "MISSING"])
    rows = storage.query_df(
        "SELECT issuer_name FROM holdings WHERE accession_number = ?",
        ("ACC-001",),
    )

    assert counts == {"ACC-001": 1}
    assert rows["issuer_name"].tolist() == ["Microsoft Corp"]


def test_connect_retries_while_another_process_holds_the_lock(tmp_path, monkeypatch):
    """The poller and the refresh pipeline both write this DB; a lost race must not abort."""
    real_connect = duckdb.connect
    calls = {"n": 0}

    def flaky_connect(path, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise duckdb.IOException(
                f'IO Error: Could not set lock on file "{path}": '
                "Conflicting lock is held in /usr/bin/python3.12 (PID 1234)."
            )
        return real_connect(path, **kwargs)

    monkeypatch.setattr(duckdb, "connect", flaky_connect)
    monkeypatch.setattr(dashboard_storage_module.time, "sleep", lambda _: None)

    storage = DashboardStorage(tmp_path / "dashboard.duckdb")

    assert calls["n"] == 3
    assert storage.get_accession_row_counts(["MISSING"]) == {}


def test_connect_does_not_retry_on_non_lock_io_errors(tmp_path, monkeypatch):
    def broken_connect(path, **kwargs):
        raise duckdb.IOException("IO Error: database file is corrupted")

    monkeypatch.setattr(duckdb, "connect", broken_connect)
    monkeypatch.setattr(dashboard_storage_module.time, "sleep", lambda _: None)

    with pytest.raises(duckdb.IOException, match="corrupted"):
        DashboardStorage(tmp_path / "dashboard.duckdb")


def test_save_holdings_normalizes_fund_cik_to_ten_digits(tmp_path: Path):
    storage = DashboardStorage(tmp_path / "dashboard.duckdb")

    storage.save_holdings(
        [_holding()],
        "Test Fund",
        "2045724",
        "2026-05-15",
        "ACC-CIK",
        "https://sec.gov/acc-cik",
    )

    rows = storage.query_df(
        "SELECT fund_cik FROM holdings WHERE accession_number = ?",
        ("ACC-CIK",),
    )

    assert rows["fund_cik"].tolist() == ["0002045724"]


def test_select_filings_uses_duckdb_as_canonical_when_available(tmp_path: Path):
    storage = DashboardStorage(tmp_path / "dashboard.duckdb")
    storage.save_holdings(
        [_holding()],
        "Test Fund",
        "0000000001",
        "2026-05-15",
        "ACC-CANONICAL",
        "https://sec.gov/canonical",
    )
    filings = [
        {"accession_number": "ACC-CANONICAL"},
        {"accession_number": "ACC-TRACKED-MISSING"},
        {"accession_number": "ACC-NEW"},
    ]
    processed = {"ACC-CANONICAL", "ACC-TRACKED-MISSING"}

    selected, tracked_but_missing = select_filings_missing_canonical_holdings(
        filings,
        processed,
        storage,
    )

    assert [filing["accession_number"] for filing in selected] == [
        "ACC-TRACKED-MISSING",
        "ACC-NEW",
    ]
    assert tracked_but_missing == ["ACC-TRACKED-MISSING"]


def test_select_filings_falls_back_to_tracking_without_canonical_storage():
    filings = [
        {"accession_number": "ACC-TRACKED"},
        {"accession_number": "ACC-NEW"},
    ]

    selected, tracked_but_missing = select_filings_missing_canonical_holdings(
        filings,
        {"ACC-TRACKED"},
        None,
    )

    assert [filing["accession_number"] for filing in selected] == ["ACC-NEW"]
    assert tracked_but_missing == []


def test_build_holdings_consistency_report_flags_missing_canonical_accessions():
    catalog_filings = [
        {"cik": "2045724", "fund_name": "Test Fund", "accession_number": "ACC-CANONICAL"},
        {"cik": "2045724", "fund_name": "Test Fund", "accession_number": "ACC-CATALOG-MISSING"},
        {"cik": "0000000002", "fund_name": "Other Fund", "accession_number": "ACC-OTHER-FUND"},
    ]
    cache_filings = [
        {"cik": "0002045724", "fund_name": "Test Fund", "accession_number": "ACC-CACHE-MISSING"},
    ]
    processed = {"ACC-CANONICAL", "ACC-CATALOG-MISSING", "ACC-OTHER-FUND"}
    canonical_counts = {
        "ACC-CANONICAL": 2,
        "ACC-CATALOG-MISSING": 0,
        "ACC-CACHE-MISSING": 0,
        "ACC-OTHER-FUND": 4,
    }

    report = build_holdings_consistency_report(
        catalog_filings,
        processed,
        canonical_counts,
        cache_filings=cache_filings,
        fund_cik="2045724",
    )

    assert report["fund_cik"] == "0002045724"
    assert report["canonical_accessions"] == ["ACC-CANONICAL"]
    assert report["catalog_but_missing_canonical"] == ["ACC-CATALOG-MISSING"]
    assert report["cache_but_missing_canonical"] == ["ACC-CACHE-MISSING"]
    assert report["tracked_but_missing_canonical"] == ["ACC-CATALOG-MISSING"]
    assert report["missing_canonical_by_fund"] == [{
        "cik": "0002045724",
        "fund_name": "Test Fund",
        "missing_count": 2,
    }]