"""Tests for dashboard SQL query fragments."""

import duckdb
import pytest

from src.core.diff import build_position_key
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