"""Tests for dashboard SQL query fragments."""

import duckdb
import pytest

from src.core.diff import build_position_key
from src.web.pages.holdings_search import build_holdings_search_filter
from src.web.sql_queries import POSITION_KEY_SQL


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