from pathlib import Path

import duckdb
import pytest

from src.cli.process_historical_13f import (
    build_holdings_consistency_report,
    select_filings_missing_canonical_holdings,
)
from src.core import dashboard_storage as dashboard_storage_module
from src.core.dashboard_storage import DashboardStorage, ensure_dashboard_schema


def _holding(issuer="Apple Inc", cusip="037833100", *, value=5000, shares=1000, sh_prn="SH", put_call=""):
    return {
        "issuer_name": issuer,
        "share_class": "COM",
        "cusip": cusip,
        "figi": "",
        "value_x1000": str(value),
        "value": value,
        "shares_raw": str(shares),
        "shares": shares,
        "sh_prn": sh_prn,
        "put_call": put_call,
        "investment_discretion": "SOLE",
        "other_manager": "",
        "other_managers_raw": "",
        "all_columns_raw": "",
        "voting_authority_sole": shares,
        "voting_authority_shared": 0,
        "voting_authority_none": 0,
    }


def _save(storage, holdings, accession, filing_date="2026-05-15", fund="Test Fund", **metadata):
    return storage.save_holdings(
        holdings,
        fund,
        "0000000001",
        filing_date,
        accession,
        f"https://sec.gov/{accession}",
        **metadata,
    )


def _filing_row(storage, accession):
    rows = storage.query_df("SELECT * FROM filings WHERE accession_number = ?", (accession,))
    return rows.iloc[0].to_dict()


def _effective_accessions(storage, fund="Test Fund"):
    rows = storage.query_df(
        "SELECT DISTINCT accession_number FROM holdings_effective WHERE fund_name = ? ORDER BY 1",
        (fund,),
    )
    return rows["accession_number"].tolist()


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


# ---------------------------------------------------------------------------
# filings table, value units, amendment folding, holdings_effective view
# ---------------------------------------------------------------------------


def test_save_holdings_registers_the_filing_and_view_returns_dollars(tmp_path: Path):
    storage = DashboardStorage(tmp_path / "dashboard.duckdb")
    # 2020 filing in thousands: $5k for 1,000 shares reads as $5/share only x1000.
    _save(storage, [_holding(value=5, shares=1000), _holding("NVIDIA Corp", "67066G104", value=40, shares=1000)],
          "ACC-2020", filing_date="2020-05-15")
    # 2024 filing in dollars: $50/share.
    _save(storage, [_holding(value=50_000, shares=1000)], "ACC-2024", filing_date="2024-05-15")

    old = _filing_row(storage, "ACC-2020")
    new = _filing_row(storage, "ACC-2024")
    assert (old["row_count"], old["value_multiplier"], bool(old["is_effective"])) == (2, 1000, True)
    assert (new["row_count"], new["value_multiplier"], old["anchor_accession"]) == (1, 1, "ACC-2020")

    values = storage.query_df(
        "SELECT source_accession_number, SUM(value_usd) AS total FROM holdings_effective GROUP BY 1 ORDER BY 1"
    )
    assert values["total"].tolist() == [45_000, 50_000]
    # The raw table is untouched: bookkeeping still sees what the filer wrote.
    assert storage.get_accession_row_counts(["ACC-2020"]) == {"ACC-2020": 2}


def test_bond_heavy_filing_is_not_mistaken_for_thousands(tmp_path: Path):
    """Oaktree: most rows are PRN priced near $1, the few equities trade around $15."""
    storage = DashboardStorage(tmp_path / "dashboard.duckdb")
    bonds = [
        _holding(f"Bond {index}", f"BOND{index:05d}", value=1_000_000, shares=1_000_000, sh_prn="PRN")
        for index in range(8)
    ]
    options = [_holding("Call Co", "CALL00001", value=100, shares=100_000, put_call="Call")]
    equities = [
        _holding("Equity A", "EQA000001", value=15_000_000, shares=1_000_000),
        _holding("Equity B", "EQB000001", value=18_000_000, shares=1_000_000),
    ]
    _save(storage, bonds + options + equities, "ACC-OAK", filing_date="2025-05-15")

    assert _filing_row(storage, "ACC-OAK")["value_multiplier"] == 1


def test_new_holdings_amendment_is_read_with_its_original(tmp_path: Path):
    storage = DashboardStorage(tmp_path / "dashboard.duckdb")
    _save(storage, [_holding(), _holding("NVIDIA Corp", "67066G104")], "ACC-O",
          form_type="13F-HR", period_of_report="2026-03-31")
    _save(storage, [_holding("Microsoft Corp", "594918104")], "ACC-NH", filing_date="2026-05-20",
          form_type="13F-HR/A", period_of_report="2026-03-31", amendment_type="NEW HOLDINGS")

    rows = storage.query_df(
        "SELECT accession_number, filing_date, source_accession_number FROM holdings_effective ORDER BY issuer_name"
    )
    assert set(rows["accession_number"]) == {"ACC-O"}
    assert set(rows["filing_date"]) == {"2026-05-15"}
    assert sorted(rows["source_accession_number"]) == ["ACC-NH", "ACC-O", "ACC-O"]


def test_metadata_backfill_turns_a_refiling_into_a_restatement(tmp_path: Path):
    storage = DashboardStorage(tmp_path / "dashboard.duckdb")
    _save(storage, [_holding(), _holding("NVIDIA Corp", "67066G104")], "ACC-O")
    _save(storage, [_holding("Microsoft Corp", "594918104")], "ACC-R", filing_date="2026-06-01")
    assert _effective_accessions(storage) == ["ACC-O", "ACC-R"]

    updated = storage.upsert_filing_metadata_many([
        {"accession_number": "ACC-O", "form_type": "13F-HR", "period_of_report": "2026-03-31"},
        {"accession_number": "ACC-R", "form_type": "13F-HR/A", "period_of_report": "2026-03-31",
         "amendment_type": "RESTATEMENT", "table_entry_total": 1},
        {"accession_number": "ACC-UNKNOWN", "form_type": "13F-HR"},
        {"accession_number": "ACC-O"},
    ])

    assert updated == 2
    assert _effective_accessions(storage) == ["ACC-R"]
    assert not bool(_filing_row(storage, "ACC-O")["is_effective"])

    # None never overwrites what is already known.
    storage.upsert_filing_metadata_many([{"accession_number": "ACC-R", "amendment_type": None, "table_value_total": 7}])
    row = _filing_row(storage, "ACC-R")
    assert (row["amendment_type"], row["table_value_total"]) == ("RESTATEMENT", 7)

    # Re-ingesting through a caller that does not pass metadata keeps it too.
    _save(storage, [_holding("Microsoft Corp", "594918104")], "ACC-R", filing_date="2026-06-01")
    assert _filing_row(storage, "ACC-R")["period_of_report"] == "2026-03-31"
    assert _effective_accessions(storage) == ["ACC-R"]


def test_missing_metadata_and_entry_count_mismatch_reports(tmp_path: Path):
    storage = DashboardStorage(tmp_path / "dashboard.duckdb")
    _save(storage, [_holding()], "ACC-NO-META")
    _save(storage, [_holding()], "ACC-AMEND", filing_date="2026-05-20",
          form_type="13F-HR/A", period_of_report="2026-03-31")
    _save(storage, [_holding(), _holding("NVIDIA Corp", "67066G104")], "ACC-COMPLETE", filing_date="2026-05-14",
          form_type="13F-HR", period_of_report="2026-03-31", table_entry_total=3)

    missing = storage.get_filings_missing_metadata()
    assert [row["accession_number"] for row in missing] == ["ACC-AMEND", "ACC-NO-META"]
    assert set(missing[0]) == {
        "accession_number", "fund_name", "fund_cik", "filing_date", "filing_url",
        "form_type", "period_of_report", "amendment_type",
    }
    assert missing[1]["filing_url"] == "https://sec.gov/ACC-NO-META"
    assert len(storage.get_filings_missing_metadata(limit=1)) == 1

    mismatches = storage.get_entry_count_mismatches()
    assert [(row["accession_number"], row["row_count"], row["table_entry_total"]) for row in mismatches] == [
        ("ACC-COMPLETE", 2, 3)
    ]


def test_old_database_is_migrated_on_open(tmp_path: Path):
    db_path = tmp_path / "old.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute(dashboard_storage_module.HOLDINGS_TABLE_DDL)
    conn.execute(
        """
        INSERT INTO holdings (filing_date, fund_name, fund_cik, accession_number, cusip, value_usd, shares, sh_prn)
        VALUES
            ('2021-05-15', 'Old Fund', '0000000009', 'ACC-OLD', '037833100', 10, 1000, 'SH'),
            ('2024-05-15', 'Old Fund', '0000000009', 'ACC-NEW', '037833100', 20000, 1000, 'SH')
        """
    )
    conn.close()

    assert ensure_dashboard_schema(db_path) is True
    assert ensure_dashboard_schema(db_path) is True  # idempotent

    storage = DashboardStorage(db_path, read_only=True)
    filings = storage.query_df("SELECT accession_number, value_multiplier, is_effective FROM filings ORDER BY 1")
    assert filings["accession_number"].tolist() == ["ACC-NEW", "ACC-OLD"]
    assert filings["value_multiplier"].tolist() == [1, 1000]
    totals = storage.query_df("SELECT SUM(value_usd) AS total FROM holdings_effective")
    assert totals["total"].iloc[0] == 30_000


def test_writer_running_older_code_cannot_hide_rows(tmp_path: Path):
    """Holdings added without a filings row are registered the next time the file is opened."""
    db_path = tmp_path / "dashboard.duckdb"
    DashboardStorage(db_path)
    conn = duckdb.connect(str(db_path))
    conn.execute(
        "INSERT INTO holdings (filing_date, fund_name, accession_number, value_usd, shares, sh_prn) "
        "VALUES ('2025-02-14', 'Fund', 'ACC-LEGACY', 1000, 10, 'SH')"
    )
    conn.close()

    storage = DashboardStorage(db_path)
    assert _effective_accessions(storage, "Fund") == ["ACC-LEGACY"]


def test_ensure_dashboard_schema_skips_missing_file_and_lock_conflicts(tmp_path, monkeypatch, caplog):
    assert ensure_dashboard_schema(tmp_path / "missing.duckdb") is False

    db_path = tmp_path / "dashboard.duckdb"
    DashboardStorage(db_path)

    def locked_connect(path, **kwargs):
        raise duckdb.IOException(
            f'IO Error: Could not set lock on file "{path}": Conflicting lock is held in python (PID 1).'
        )

    monkeypatch.setattr(duckdb, "connect", locked_connect)
    with caplog.at_level("WARNING"):
        assert ensure_dashboard_schema(db_path) is False
    assert "locked" in caplog.text


def test_clear_holdings_keeps_only_filings_with_metadata(tmp_path: Path):
    storage = DashboardStorage(tmp_path / "dashboard.duckdb")
    _save(storage, [_holding()], "ACC-PLAIN")
    _save(storage, [_holding()], "ACC-META", filing_date="2026-05-16", form_type="13F-HR", period_of_report="2026-03-31")

    storage.clear_holdings()

    filings = storage.query_df("SELECT accession_number, row_count, is_effective FROM filings")
    assert filings["accession_number"].tolist() == ["ACC-META"]
    assert (int(filings["row_count"].iloc[0]), bool(filings["is_effective"].iloc[0])) == (0, False)
    assert storage.query_df("SELECT COUNT(*) AS n FROM holdings_effective")["n"].iloc[0] == 0

    _save(storage, [_holding()], "ACC-META", filing_date="2026-05-16")
    assert _filing_row(storage, "ACC-META")["period_of_report"] == "2026-03-31"
    assert _effective_accessions(storage) == ["ACC-META"]


def test_replace_holdings_from_dataframe_keeps_filings_consistent(tmp_path: Path):
    storage = DashboardStorage(tmp_path / "dashboard.duckdb")
    _save(storage, [_holding()], "ACC-GONE")
    source = storage.query_df("SELECT * FROM holdings")
    source["accession_number"] = "ACC-NEW"

    inserted = storage.replace_holdings_from_dataframe(source)

    assert inserted == 1
    assert storage.query_df("SELECT accession_number FROM filings")["accession_number"].tolist() == ["ACC-NEW"]
    assert _effective_accessions(storage) == ["ACC-NEW"]