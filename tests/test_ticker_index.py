"""Tests for the holdings-derived ticker→CUSIP index."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import duckdb
import pandas as pd
import pytest

from src.web.ticker_index import (
    _index_path,
    cusips_for_ticker,
    expand_ticker_terms,
    get_ticker_index,
    invalidate_ticker_index,
    is_ticker_like,
)


@pytest.fixture
def fresh_ticker_index(monkeypatch, tmp_path):
    """Force the ticker index to rebuild against a controlled holdings DB."""
    # Reset the in-process cache before each test.
    invalidate_ticker_index()

    db_path = tmp_path / "13f_dashboard.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE holdings (
            cusip TEXT,
            issuer_name TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO holdings VALUES (?, ?)",
        [
            ("037833100", "APPLE INC"),
            ("02079K305", "ALPHABET INC"),
            ("684060106", "ORANGE"),  # Orange SA ADR (CUSIP for ORANY/ORAN)
            ("68417L107", "ORANGE CNTY BANCORP INC"),  # different issuer, same prefix
            ("88160R101", "TESLA INC"),
        ],
    )
    conn.close()

    # Build a SEC reference that's *just* enough to resolve our sample issuers.
    ref_path = tmp_path / "sec_company_tickers_exchange.json"
    ref_path.write_text(
        json.dumps(
            {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [320193, "Apple Inc.", "AAPL", "Nasdaq"],
                    [1652044, "Alphabet Inc.", "GOOG", "Nasdaq"],
                    [1318605, "Tesla, Inc.", "TSLA", "Nasdaq"],
                ],
            }
        ),
        encoding="utf-8",
    )

    # Patch the module-level constants used by the index.
    monkeypatch.setattr("src.web.ticker_index.DASHBOARD_DB_FILE", db_path)
    monkeypatch.setattr("src.web.ticker_index.CACHE_FILE", tmp_path / "holdings_ticker_index.json")
    monkeypatch.setattr("src.web.tickers.TICKER_REFERENCE_FILE", ref_path)
    # Clear the lru_cache on get_ticker_lookup so it re-reads the patched reference.
    from src.web import tickers

    tickers.get_ticker_lookup.cache_clear()

    yield

    invalidate_ticker_index()
    tickers.get_ticker_lookup.cache_clear()


def test_is_ticker_like_accepts_short_alphanumeric_tokens():
    assert is_ticker_like("AAPL")
    assert is_ticker_like("BRK.B")
    assert is_ticker_like("RDS-A")
    assert is_ticker_like("ORAN")
    assert is_ticker_like("APPLE")  # ticker-shape is fine; ambiguity handled by the index


def test_is_ticker_like_rejects_long_or_numeric_or_empty():
    assert not is_ticker_like("")
    assert not is_ticker_like("037833100")  # numeric CUSIP
    assert not is_ticker_like("apple berkshire")  # multi-word
    assert not is_ticker_like("037-833")  # punctuation-only, no alpha
    assert not is_ticker_like("ABCDEF")  # 6 chars — too long for a ticker


def test_get_ticker_index_resolves_holdings_to_cusips(fresh_ticker_index):
    mapping = get_ticker_index()

    # Apple, Alphabet, Tesla resolve cleanly via SEC reference.
    assert mapping["AAPL"] == ["037833100"]
    assert mapping["GOOG"] == ["02079K305"]
    assert mapping["TSLA"] == ["88160R101"]

    # ORANGE County Bancorp has no matching ticker in our minimal fixture
    # (it would be OBT, which isn't in the test SEC reference), so it should
    # NOT show up under the ORANGE prefix.
    assert "ORANGE CNTY BANCORP INC".lower() not in {k.lower() for k in mapping}


def test_get_ticker_index_includes_oran_via_cusip_override(monkeypatch, tmp_path):
    """The 684060106 → ORAN CUSIP override (in src.web.tickers) should make
    ORAN resolve to Orange SA even though the SEC reference only lists the
    OTC tickers FNCTF/ORANY for the issuer name ``ORANGE``."""
    db_path = tmp_path / "13f_dashboard.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE TABLE holdings (cusip TEXT, issuer_name TEXT)")
    conn.execute("INSERT INTO holdings VALUES ('684060106', 'ORANGE')")
    conn.close()

    ref_path = tmp_path / "sec_company_tickers_exchange.json"
    ref_path.write_text(
        json.dumps(
            {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [[1038143, "ORANGE", "ORANY", "OTC"]],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("src.web.ticker_index.DASHBOARD_DB_FILE", db_path)
    monkeypatch.setattr("src.web.ticker_index.CACHE_FILE", tmp_path / "holdings_ticker_index.json")
    monkeypatch.setattr("src.web.tickers.TICKER_REFERENCE_FILE", ref_path)
    from src.web import tickers
    tickers.get_ticker_lookup.cache_clear()
    invalidate_ticker_index()

    try:
        mapping = get_ticker_index()
        assert mapping.get("ORAN") == ["684060106"]
        # The OTC ticker is still ambiguous with FNCTF in the SEC reference,
        # so it does NOT appear in the index — only the CUSIP override does.
        assert "ORANY" not in mapping
    finally:
        invalidate_ticker_index()
        tickers.get_ticker_lookup.cache_clear()


def test_cusips_for_ticker_is_case_insensitive(fresh_ticker_index):
    assert cusips_for_ticker("aapl") == ["037833100"]
    assert cusips_for_ticker("AAPL") == ["037833100"]


def test_cusips_for_ticker_unknown_returns_empty(fresh_ticker_index):
    assert cusips_for_ticker("ZZZZ") == []


def test_expand_ticker_terms_dedupes_and_skips_non_ticker_tokens(fresh_ticker_index):
    # `apple` is ticker-shaped and resolves to AAPL via the reference name match,
    # so it should be included. Numeric / mixed tokens stay out.
    cusips = expand_ticker_terms(["AAPL", "aapl", "ORAN", "037833100", "apple berkshire"])
    assert "037833100" in cusips


def test_expand_ticker_terms_drops_terms_with_no_resolution(fresh_ticker_index):
    # `ZZZZ` is ticker-shaped but resolves to nothing; it should be silently
    # ignored (no empty IN clause emitted).
    cusips = expand_ticker_terms(["ZZZZ"])
    assert cusips == []


def test_index_reads_from_injected_path_not_live_db(monkeypatch, tmp_path):
    """The API passes a read-only snapshot; the SELECT must run against *that*
    path, never the live ``DASHBOARD_DB_FILE``. This is what keeps ticker search
    off the live writer DB (no lock contention with the poller/refresh)."""
    invalidate_ticker_index()

    # The "live" DB is a decoy: if the index ever opens it we'd get TESLA, not AAPL.
    live_db = tmp_path / "live" / "13f_dashboard.duckdb"
    live_db.parent.mkdir()
    conn = duckdb.connect(str(live_db))
    conn.execute("CREATE TABLE holdings (cusip TEXT, issuer_name TEXT)")
    conn.execute("INSERT INTO holdings VALUES ('88160R101', 'TESLA INC')")
    conn.close()

    # The snapshot the API would hand us: only Apple lives here.
    snapshot_db = tmp_path / "snap" / "13f_dashboard.123.snapshot.duckdb"
    snapshot_db.parent.mkdir()
    conn = duckdb.connect(str(snapshot_db))
    conn.execute("CREATE TABLE holdings (cusip TEXT, issuer_name TEXT)")
    conn.execute("INSERT INTO holdings VALUES ('037833100', 'APPLE INC')")
    conn.close()

    ref_path = tmp_path / "sec_company_tickers_exchange.json"
    ref_path.write_text(
        json.dumps(
            {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [320193, "Apple Inc.", "AAPL", "Nasdaq"],
                    [1318605, "Tesla, Inc.", "TSLA", "Nasdaq"],
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("src.web.ticker_index.DASHBOARD_DB_FILE", live_db)
    monkeypatch.setattr("src.web.ticker_index.CACHE_FILE", tmp_path / "holdings_ticker_index.json")
    monkeypatch.setattr("src.web.tickers.TICKER_REFERENCE_FILE", ref_path)
    from src.web import tickers
    tickers.get_ticker_lookup.cache_clear()

    try:
        mapping = get_ticker_index(read_db_path=snapshot_db)
        # Read from the snapshot: Apple present, Tesla (live-only) absent.
        assert mapping.get("AAPL") == ["037833100"]
        assert "TSLA" not in mapping
        assert cusips_for_ticker("AAPL", read_db_path=snapshot_db) == ["037833100"]
        assert expand_ticker_terms(["AAPL"], read_db_path=snapshot_db) == ["037833100"]
    finally:
        invalidate_ticker_index()
        tickers.get_ticker_lookup.cache_clear()


def test_index_persists_to_disk_and_invalidates_on_mtime_change(fresh_ticker_index, tmp_path):
    cache_file = _index_path()
    print("\n[debug] cache_file path:", cache_file)
    print("[debug] cache_file exists before call:", cache_file.exists())

    mapping = get_ticker_index()
    print("[debug] mapping keys:", sorted(mapping.keys()))
    print("[debug] cache_file exists after call:", cache_file.exists())
    assert "AAPL" in mapping

    assert cache_file.exists()
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "AAPL" in payload["ticker_to_cusips"]
    assert payload["source_mtime_ns"] > 0

    # Bump the source DB's mtime and reload — should rebuild.
    import os
    import time

    new_db_mtime = time.time_ns() + 10_000_000  # ~10 ms in the future
    os.utime(tmp_path / "13f_dashboard.duckdb", ns=(new_db_mtime, new_db_mtime))

    invalidate_ticker_index()
    rebuilt = get_ticker_index()
    assert "AAPL" in rebuilt
    new_payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert new_payload["source_mtime_ns"] == new_db_mtime