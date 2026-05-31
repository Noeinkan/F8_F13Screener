"""Tests for src/core/storage.py — uses a temporary SQLite file per test."""
import pytest
from datetime import datetime, timedelta
from src.core.diff import build_position_key
from src.core.storage import Storage


# ---------------------------------------------------------------------------
# Fixture: fresh in-file DB for every test
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return Storage(tmp_path / "test.db")


def _make_holding(
    issuer="Apple Inc",
    cusip="037833100",
    shares=1000,
    value=5000,
    share_class="COM",
    put_call="",
):
    return {
        "issuer_name": issuer,
        "share_class": share_class,
        "cusip": cusip,
        "figi": "",
        "value": value,
        "shares": shares,
        "sh_prn": "SH",
        "put_call": put_call,
        "investment_discretion": "SOLE",
        "other_manager": "",
        "voting_authority_sole": shares,
        "voting_authority_shared": 0,
        "voting_authority_none": 0,
    }


# ---------------------------------------------------------------------------
# seen_filings
# ---------------------------------------------------------------------------

class TestSeenFilings:

    def test_empty_initially(self, db):
        assert db.get_seen_filings() == set()

    def test_mark_and_retrieve(self, db):
        db.mark_filing_seen("entry-1", "Berkshire", "1067983", "2026-05-01", matched=False)
        seen = db.get_seen_filings()
        assert "entry-1" in seen

    def test_multiple_entries(self, db):
        for i in range(5):
            db.mark_filing_seen(f"entry-{i}", f"Fund{i}", str(i), "2026-05-01")
        assert len(db.get_seen_filings()) == 5

    def test_upsert_replaces_existing(self, db):
        db.mark_filing_seen("entry-1", "Fund", "123", "2026-05-01", matched=False)
        db.mark_filing_seen("entry-1", "Fund", "123", "2026-05-01", matched=True)
        assert len(db.get_seen_filings()) == 1  # still one row

    def test_limit_respected(self, db):
        for i in range(20):
            db.mark_filing_seen(f"entry-{i}", "F", str(i), "2026-05-01")
        assert len(db.get_seen_filings(limit=5)) == 5


# ---------------------------------------------------------------------------
# save_holdings / get_holdings_by_accession
# ---------------------------------------------------------------------------

class TestHoldings:

    def test_save_and_retrieve_by_accession(self, db):
        holdings = [_make_holding("Apple Inc", "037833100", 1000, 5000)]
        db.save_holdings(holdings, "Berkshire", "1067983", "2026-05-01", "ACC-001", "https://sec.gov/x")
        result = db.get_holdings_by_accession("ACC-001")
        position_key = build_position_key("037833100", "Apple Inc", "COM", "")
        assert position_key in result
        assert result[position_key]["issuer_name"] == "Apple Inc"
        assert result[position_key]["shares"] == 1000

    def test_multiple_holdings_saved(self, db):
        holdings = [
            _make_holding("Apple Inc",  "037833100", 1000, 5000),
            _make_holding("Tesla Inc",  "88160R101",  500, 2000),
            _make_holding("Nvidia Corp","67066G104",  200, 8000),
        ]
        count = db.save_holdings(holdings, "Berkshire", "1067983", "2026-05-01", "ACC-001", "https://sec.gov/x")
        assert count == 3
        result = db.get_holdings_by_accession("ACC-001")
        assert len(result) == 3

    def test_empty_holdings_returns_zero(self, db):
        count = db.save_holdings([], "Fund", "123", "2026-05-01", "ACC-000", "https://sec.gov/x")
        assert count == 0

    def test_unknown_accession_returns_empty(self, db):
        result = db.get_holdings_by_accession("DOES-NOT-EXIST")
        assert result == {}

    def test_holdings_with_none_cusip_excluded(self, db):
        h = _make_holding("No CUSIP Fund", None, 100, 1000)
        db.save_holdings([h], "Fund", "123", "2026-05-01", "ACC-002", "https://sec.gov/x")
        result = db.get_holdings_by_accession("ACC-002")
        fallback_key = build_position_key("", "No CUSIP Fund", "COM", "")
        assert fallback_key in result
        assert result[fallback_key]["shares"] == 100

    def test_filing_date_with_timestamp_cleaned(self, db):
        holdings = [_make_holding()]
        db.save_holdings(holdings, "Fund", "123", "2026-05-01T12:00:00", "ACC-003", "https://sec.gov/x")
        result = db.get_holdings_by_accession("ACC-003")
        assert len(result) == 1  # should not crash or skip

    def test_same_cusip_equity_and_call_are_separate_positions(self, db):
        holdings = [
            _make_holding("Apple Inc", "037833100", 1000, 5000, share_class="COM", put_call=""),
            _make_holding("Apple Inc", "037833100", 200, 800, share_class="COM", put_call="CALL"),
        ]

        db.save_holdings(holdings, "Fund", "123", "2026-05-01", "ACC-OPT", "https://sec.gov/x")
        result = db.get_holdings_by_accession("ACC-OPT")

        equity_key = build_position_key("037833100", "Apple Inc", "COM", "")
        call_key = build_position_key("037833100", "Apple Inc", "COM", "CALL")

        assert len(result) == 2
        assert result[equity_key]["shares"] == 1000
        assert result[call_key]["shares"] == 200
        assert result[call_key]["put_call"] == "CALL"

    def test_duplicate_lines_same_normalized_position_are_aggregated(self, db):
        holdings = [
            _make_holding("Apple Inc", "037833100", 1000, 5000),
            _make_holding("Apple Inc", "037833100", 500, 2500),
        ]

        db.save_holdings(holdings, "Fund", "123", "2026-05-01", "ACC-AGG", "https://sec.gov/x")
        result = db.get_holdings_by_accession("ACC-AGG")

        equity_key = build_position_key("037833100", "Apple Inc", "COM", "")
        assert len(result) == 1
        assert result[equity_key]["shares"] == 1500
        assert result[equity_key]["value_usd"] == 7500

    def test_save_holdings_replaces_existing_accession(self, db):
        first = [_make_holding("Apple Inc", "037833100", 1000, 5000)]
        second = [_make_holding("Microsoft Corp", "594918104", 400, 2500)]

        db.save_holdings(first, "Fund", "123", "2026-05-01", "ACC-004", "https://sec.gov/x")
        db.save_holdings(second, "Fund", "123", "2026-05-01", "ACC-004", "https://sec.gov/x")

        result = db.get_holdings_by_accession("ACC-004")
        apple_key = build_position_key("037833100", "Apple Inc", "COM", "")
        microsoft_key = build_position_key("594918104", "Microsoft Corp", "COM", "")
        assert apple_key not in result
        assert microsoft_key in result
        assert len(result) == 1

    def test_export_csv_includes_raw_parser_fields(self, db, tmp_path):
        holding = _make_holding()
        holding["value_x1000"] = "5000"
        holding["shares_raw"] = "1000"
        holding["other_managers_raw"] = "MGR-1"
        holding["all_columns_raw"] = "Apple Inc | COM | 037833100"

        db.save_holdings([holding], "Fund", "123", "2026-05-01", "ACC-005", "https://sec.gov/x")

        output_path = tmp_path / "holdings.csv"
        db.export_holdings_to_csv(output_path)

        csv_text = output_path.read_text(encoding="utf-8")
        assert "Value Raw ($000s)" in csv_text
        assert "Shares/Principal Amount Raw" in csv_text
        assert "Other Managers (raw)" in csv_text
        assert "All Columns (raw)" in csv_text

    def test_export_latest_snapshot_uses_newest_filing_per_fund(self, db, tmp_path):
        older = _make_holding("Apple Inc", "037833100", 1000, 5000)
        newer = _make_holding("Microsoft Corp", "594918104", 400, 2500)

        db.save_holdings([older], "Fund A", "123", "2026-02-14", "ACC-OLD", "https://sec.gov/old")
        db.save_holdings([newer], "Fund A", "123", "2026-05-15", "ACC-NEW", "https://sec.gov/new")
        db.save_holdings([_make_holding("NVIDIA Corp", "67066G104", 200, 8000)], "Fund B", "456", "2026-03-31", "ACC-B", "https://sec.gov/b")

        output_path = tmp_path / "latest_snapshot.csv"
        row_count = db.export_latest_snapshot_to_csv(output_path)

        csv_text = output_path.read_text(encoding="utf-8")
        assert row_count == 2
        assert "ACC-NEW" in csv_text
        assert "ACC-OLD" not in csv_text
        assert "ACC-B" in csv_text


# ---------------------------------------------------------------------------
# get_latest_accessions_for_fund
# ---------------------------------------------------------------------------

class TestLatestAccessions:

    def _save(self, db, cik, acc, date):
        db.save_holdings(
            [_make_holding()],
            "Test Fund", cik, date, acc, "https://sec.gov/x"
        )

    def test_returns_newest_first(self, db):
        self._save(db, "111", "ACC-Q1", "2025-02-14")
        self._save(db, "111", "ACC-Q2", "2025-05-15")
        self._save(db, "111", "ACC-Q3", "2025-08-14")
        result = db.get_latest_accessions_for_fund("111", limit=3)
        dates = [r["filing_date"] for r in result]
        assert dates == sorted(dates, reverse=True)

    def test_limit_respected(self, db):
        for i in range(5):
            self._save(db, "222", f"ACC-{i}", f"2025-{i+1:02d}-15")
        result = db.get_latest_accessions_for_fund("222", limit=2)
        assert len(result) == 2

    def test_unknown_cik_returns_empty(self, db):
        assert db.get_latest_accessions_for_fund("9999999") == []

    def test_different_funds_isolated(self, db):
        self._save(db, "AAA", "ACC-A", "2026-02-14")
        self._save(db, "BBB", "ACC-B", "2026-02-14")
        result_a = db.get_latest_accessions_for_fund("AAA")
        assert all(r["accession_number"] == "ACC-A" for r in result_a)


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------

class TestStatistics:

    def test_initial_statistics_zero(self, db):
        stats = db.get_statistics()
        assert stats["total_checked"] == 0
        assert stats["matched"] == 0
        assert stats["filtered"] == 0

    def test_update_increments(self, db):
        db.update_statistics(total_checked=10, matched=2, filtered=8)
        stats = db.get_statistics()
        assert stats["total_checked"] == 10
        assert stats["matched"] == 2
        assert stats["filtered"] == 8

    def test_multiple_updates_accumulate(self, db):
        db.update_statistics(total_checked=5, matched=1, filtered=4)
        db.update_statistics(total_checked=5, matched=1, filtered=4)
        stats = db.get_statistics()
        assert stats["total_checked"] == 10
        assert stats["matched"] == 2


# ---------------------------------------------------------------------------
# cleanup_old_filings
# ---------------------------------------------------------------------------

class TestCleanup:

    def test_old_records_deleted(self, db):
        # Insert a very old entry by manipulating processed_at manually
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        old_ts = (datetime.now() - timedelta(days=100)).isoformat()
        conn.execute(
            "INSERT INTO seen_filings (entry_id, filer_name, cik, filing_date, matched, processed_at) "
            "VALUES ('old-entry', 'OldFund', '999', '2025-01-01', 0, ?)",
            (old_ts,)
        )
        conn.commit()
        conn.close()

        db.cleanup_old_filings(days=90)
        assert "old-entry" not in db.get_seen_filings()

    def test_recent_records_kept(self, db):
        db.mark_filing_seen("new-entry", "NewFund", "888", "2026-05-01")
        db.cleanup_old_filings(days=90)
        assert "new-entry" in db.get_seen_filings()

    def test_clear_holdings_removes_all_rows(self, db):
        db.save_holdings([_make_holding()], "Fund", "123", "2026-05-01", "ACC-100", "https://sec.gov/x")
        deleted = db.clear_holdings()
        assert deleted == 1
        assert db.get_holdings_by_accession("ACC-100") == {}
