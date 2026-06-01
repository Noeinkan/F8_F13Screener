import pandas as pd

from src.web.pages.consensus_trends import build_consensus_trend_tables


def _row(fund, accession, filing_date, position_key, issuer, shares, value):
    return {
        "fund_name": fund,
        "accession_number": accession,
        "filing_date": filing_date,
        "position_key": position_key,
        "cusip": position_key,
        "issuer_name": issuer,
        "share_class": "COM",
        "put_call": None,
        "shares": shares,
        "value_usd": value,
        "raw_lines": 1,
    }


def test_consensus_trends_detects_cross_fund_movements_and_weight_growth():
    rows = pd.DataFrame([
        _row("Fund A", "a-2025q4", "2025-12-31", "AAA", "AAA Corp", 100, 10_000),
        _row("Fund A", "a-2025q4", "2025-12-31", "BBB", "BBB Corp", 100, 10_000),
        _row("Fund A", "a-2026q1", "2026-03-31", "AAA", "AAA Corp", 150, 18_000),
        _row("Fund A", "a-2026q1", "2026-03-31", "CCC", "CCC Corp", 50, 2_000),
        _row("Fund B", "b-2025q4", "2025-12-31", "AAA", "AAA Corp", 100, 10_000),
        _row("Fund B", "b-2025q4", "2025-12-31", "BBB", "BBB Corp", 100, 10_000),
        _row("Fund B", "b-2026q1", "2026-03-31", "AAA", "AAA Corp", 120, 12_000),
        _row("Fund B", "b-2026q1", "2026-03-31", "BBB", "BBB Corp", 80, 8_000),
    ])

    tables = build_consensus_trend_tables(rows, lookback_quarters=2)

    accumulation = tables["accumulation"].set_index("position_key")
    assert accumulation.loc["AAA", "Funds Buying"] == 2
    assert accumulation.loc["AAA", "Funds Increasing"] == 2
    assert accumulation.loc["AAA", "Aggregate_Share_Delta"] == 70
    assert accumulation.loc["CCC", "Funds Opening"] == 1

    distribution = tables["distribution"].set_index("position_key")
    assert distribution.loc["BBB", "Funds Selling"] == 2
    assert distribution.loc["BBB", "Funds Closing"] == 1
    assert distribution.loc["BBB", "Funds Decreasing"] == 1
    assert distribution.loc["BBB", "Aggregate_Share_Delta"] == -120

    weight_growth = tables["weight_growth"].set_index("position_key")
    assert weight_growth.loc["AAA", "Funds_With_Weight_Growth"] == 2
    assert weight_growth.loc["AAA", "Average_Weight_Delta_Pct"] > 0

    latest_consensus = tables["latest_consensus"].set_index("position_key")
    assert latest_consensus.loc["AAA", "Latest_Holders"] == 2
    assert latest_consensus.loc["AAA", "Holder_Delta"] == 0
    assert latest_consensus.loc["CCC", "Holder_Delta"] == 1
    assert latest_consensus.loc["BBB", "Holder_Delta"] == -1


def test_consensus_trends_respects_selected_funds():
    rows = pd.DataFrame([
        _row("Fund A", "a-2025q4", "2025-12-31", "AAA", "AAA Corp", 100, 10_000),
        _row("Fund A", "a-2026q1", "2026-03-31", "AAA", "AAA Corp", 150, 18_000),
        _row("Fund B", "b-2025q4", "2025-12-31", "AAA", "AAA Corp", 100, 10_000),
        _row("Fund B", "b-2026q1", "2026-03-31", "AAA", "AAA Corp", 120, 12_000),
    ])

    tables = build_consensus_trend_tables(rows, lookback_quarters=2, selected_funds=["Fund A"])

    assert tables["metadata"]["funds"] == 1
    accumulation = tables["accumulation"].set_index("position_key")
    assert accumulation.loc["AAA", "Funds Buying"] == 1
    assert accumulation.loc["AAA", "Aggregate_Share_Delta"] == 50