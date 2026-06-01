"""Tests for dashboard SQL query fragments."""

import duckdb
import pandas as pd
import pytest

from src.core.diff import build_position_key
from src.web.pages.holdings_search import build_holdings_search_filter
from src.web.sql_queries import CONSENSUS_NORMALIZED_POSITIONS_SQL, POSITION_KEY_SQL, TOP_HELD_SECURITIES_SQL


@pytest.mark.parametrize(
    ("cusip", "issuer_name", "share_class", "put_call"),
    [
        (" 037833100 ", "Apple Inc", "COM", None),
        ("", "Apple Inc", "COM", "CALL"),
        (None, " Apple Inc ", " COM ", ""),
        (None, None, None, None),
    ],
)
def test_position_key_sql_matches_python_builder(cusip, issuer_name, share_class, put_call):
    sql = f"""
        SELECT {POSITION_KEY_SQL} AS position_key
        FROM (
            SELECT
                ? AS cusip,
                ? AS issuer_name,
                ? AS share_class,
                ? AS put_call
        ) input_row
    """
    sql_key = duckdb.connect(":memory:").execute(
        sql,
        [cusip, issuer_name, share_class, put_call],
    ).fetchone()[0]

    assert sql_key == build_position_key(cusip, issuer_name, share_class, put_call)


def test_holdings_search_filter_matches_tokens_and_normalized_cusip():
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE holdings (
            issuer_name TEXT,
            fund_name TEXT,
            cusip TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO holdings VALUES (?, ?, ?)",
        [
            ("APPLE INC", "Berkshire Hathaway", "037833100"),
            ("APPLE INC", "Other Fund", "037833100"),
            ("Alphabet Inc", "Berkshire Hathaway", "02079K305"),
        ],
    )

    where_sql, params = build_holdings_search_filter("apple berkshire")
    rows = conn.execute(
        f"SELECT issuer_name, fund_name FROM holdings WHERE {where_sql}",
        params,
    ).fetchall()
    assert rows == [("APPLE INC", "Berkshire Hathaway")]

    where_sql, params = build_holdings_search_filter("037-833 100")
    rows = conn.execute(
        f"SELECT issuer_name, fund_name FROM holdings WHERE {where_sql}",
        params,
    ).fetchall()
    assert rows == [("APPLE INC", "Berkshire Hathaway"), ("APPLE INC", "Other Fund")]


def test_top_held_securities_preserves_put_call_exposure_type():
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE holdings (
            fund_name TEXT,
            filing_date TEXT,
            accession_number TEXT,
            cusip TEXT,
            issuer_name TEXT,
            share_class TEXT,
            put_call TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO holdings VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("Fund A", "2026-05-15", "0001", "037833100", "APPLE INC", "COM", None),
            ("Fund B", "2026-05-15", "0002", "037833100", "APPLE INC", "COM", "PUT"),
            ("Fund C", "2026-05-15", "0003", "037833100", "APPLE INC", "COM", None),
        ],
    )

    rows = conn.execute(TOP_HELD_SECURITIES_SQL).fetchdf()

    assert pd.isna(rows.loc[0, "Put/Call"])
    assert rows.loc[1, "Put/Call"] == "PUT"
    assert rows["Funds Holding It"].tolist() == [2, 1]


def test_consensus_normalized_positions_sql_aggregates_position_keys():
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE holdings (
            fund_name TEXT,
            accession_number TEXT,
            filing_date TEXT,
            cusip TEXT,
            issuer_name TEXT,
            share_class TEXT,
            put_call TEXT,
            shares DOUBLE,
            value_usd DOUBLE
        )
    """)
    conn.executemany(
        "INSERT INTO holdings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("Fund A", "0001", "2026-03-31", "AAA111", "AAA Corp", "COM", None, 10, 1_000),
            ("Fund A", "0001", "2026-03-31", "AAA111", "AAA Corp", "COM", None, 15, 1_500),
            ("Fund B", "0002", "2026-03-31", "BBB222", "BBB Corp", "COM", None, 20, 2_000),
        ],
    )

    rows = conn.execute(CONSENSUS_NORMALIZED_POSITIONS_SQL).fetchdf()

    fund_a = rows[rows["fund_name"].eq("Fund A")].iloc[0]
    assert len(rows) == 2
    assert fund_a["shares"] == 25
    assert fund_a["value_usd"] == 2_500
    assert fund_a["raw_lines"] == 2