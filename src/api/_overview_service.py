"""Overview page analytics."""

from __future__ import annotations

import pandas as pd

from src.api.repository import query
from src.api.serialize import records_from_dataframe
from src.web.formatting import fmt_value_dollars
from src.web.instrument_transforms import add_instrument_type_column
from src.web.sql_queries import (
    FILINGS_TIMELINE_SQL,
    LATEST_FUND_OVERVIEW_SQL,
    OVERVIEW_RECENT_ACTIVITY_SQL,
    OVERVIEW_SUMMARY_SQL,
    RECENT_FILINGS_OVERVIEW_SQL,
    TOP_HELD_SECURITIES_SQL,
)
from src.web.tickers import add_ticker_column
from src.web.value_units import apply_value_multiplier_by_group, infer_value_multiplier_by_group, summarize_multipliers


def _load_accession_multiplier_map(accession_numbers: list[str]) -> dict[str, int]:
    unique_accessions = [str(item) for item in accession_numbers if item]
    if not unique_accessions:
        return {}

    placeholders = ", ".join(["?"] * len(unique_accessions))
    rows = query(
        f"""
        SELECT accession_number, shares, value_usd
        FROM holdings
        WHERE accession_number IN ({placeholders})
          AND shares IS NOT NULL
          AND value_usd IS NOT NULL
        """,
        tuple(unique_accessions),
    )
    if rows.empty:
        return {}
    return infer_value_multiplier_by_group(
        rows,
        group_col="accession_number",
        value_col="value_usd",
        shares_col="shares",
    )


def build_overview_summary() -> dict[str, object]:
    dataset = query(OVERVIEW_SUMMARY_SQL)
    recent_activity = query(OVERVIEW_RECENT_ACTIVITY_SQL)
    if dataset.empty:
        return {
            "has_data": False,
            "has_portfolio_values": False,
            "summary": {},
            "recent_activity": {},
        }

    row = dataset.iloc[0]
    recent = recent_activity.iloc[0] if not recent_activity.empty else None
    has_portfolio_values = int(row["value_rows"] or 0) > 0
    return {
        "has_data": True,
        "has_portfolio_values": has_portfolio_values,
        "summary": {
            "positions": int(row["positions"] or 0),
            "filings": int(row["filings"] or 0),
            "funds": int(row["funds"] or 0),
            "latest_filing_date": row["latest_filing_date"],
        },
        "recent_activity": {
            "recent_filings": int(recent["recent_filings"] or 0) if recent is not None else 0,
            "recent_funds": int(recent["recent_funds"] or 0) if recent is not None else 0,
        },
    }


def build_overview_funds(filter_text: str = "") -> dict[str, object]:
    summary = build_overview_summary()
    df = query(LATEST_FUND_OVERVIEW_SQL)
    if df.empty:
        return {**summary, "funds": [], "value_multiplier_summary": None}

    if filter_text:
        df = df[df["Fund"].str.contains(filter_text, case=False, na=False)].copy()

    multiplier_summary = None
    if summary["has_portfolio_values"]:
        accession_multiplier_map = _load_accession_multiplier_map(
            df["accession_number"].dropna().astype(str).tolist(),
        )
        df["value_sum_usd"] = apply_value_multiplier_by_group(
            df,
            group_col="accession_number",
            value_col="value_sum",
            multiplier_map=accession_multiplier_map,
        )
        df["Portfolio Value"] = df["value_sum_usd"].apply(fmt_value_dollars)
        multiplier_summary = summarize_multipliers(accession_multiplier_map.values())

    chart_df = df.copy()
    if summary["has_portfolio_values"] and "value_sum_usd" in chart_df.columns:
        chart_source = chart_df.sort_values("value_sum_usd", ascending=False).head(20)
        chart = {
            "title": "Top 20 funds by latest filing value",
            "x": chart_source["Fund"].tolist(),
            "y": chart_source["value_sum_usd"].fillna(0).tolist(),
            "y_label": "Value (USD)",
        }
    else:
        chart_source = chart_df.head(20)
        chart = {
            "title": "Top 20 funds by normalized positions",
            "x": chart_source["Fund"].tolist(),
            "y": chart_source["Normalized Positions"].fillna(0).tolist(),
            "y_label": "Positions",
        }

    display_columns = [
        "Fund",
        "Quarters",
        "Latest Filing",
        "Raw 13F Lines",
        "Normalized Positions",
        "Distinct CUSIPs",
    ]
    if summary["has_portfolio_values"]:
        display_columns.append("Portfolio Value")

    return {
        **summary,
        "funds": records_from_dataframe(df[display_columns]),
        "chart": chart,
        "value_multiplier_summary": multiplier_summary,
    }


def build_filings_timeline() -> list[dict[str, object]]:
    timeline = query(FILINGS_TIMELINE_SQL)
    return records_from_dataframe(timeline.tail(24))


def build_recent_filings() -> list[dict[str, object]]:
    return records_from_dataframe(query(RECENT_FILINGS_OVERVIEW_SQL))


def build_top_held() -> list[dict[str, object]]:
    holdings = add_instrument_type_column(add_ticker_column(query(TOP_HELD_SECURITIES_SQL)))
    return records_from_dataframe(holdings)
