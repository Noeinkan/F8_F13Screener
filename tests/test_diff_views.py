"""Tests for dashboard diff presentation helpers."""

from src.web.diff_views import _build_changes_table


def test_build_changes_table_prioritizes_delta_columns_and_sorts_by_magnitude():
    display_df = _build_changes_table([
        {
            "issuer_name": "Small Increase",
            "cusip": "AAA",
            "share_class": "COM",
            "put_call": None,
            "old_shares": 100,
            "new_shares": 105,
            "share_change": 5,
            "pct_change": 5.0,
            "old_value_usd": 10,
            "new_value_usd": 11,
            "value_change": 1,
            "value_pct_change": 10.0,
        },
        {
            "issuer_name": "Large Decrease",
            "cusip": "BBB",
            "share_class": "COM",
            "put_call": None,
            "old_shares": 100,
            "new_shares": 50,
            "share_change": -50,
            "pct_change": -50.0,
            "old_value_usd": 20,
            "new_value_usd": 9,
            "value_change": -11,
            "value_pct_change": -55.0,
        },
    ])

    assert display_df.columns.tolist()[:6] == [
        "Issuer",
        "Direction",
        "Delta %",
        "Delta Shares",
        "Delta Value %",
        "Delta Value",
    ]
    assert display_df.iloc[0]["Issuer"] == "Large Decrease"
    assert display_df.iloc[0]["Direction"] == "Decrease"
    assert display_df.iloc[1]["Direction"] == "Increase"