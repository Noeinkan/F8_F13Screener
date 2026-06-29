"""Consensus trends API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from src.api._consensus_analytics import build_consensus_trend_tables
from src.api.deps import raise_db_error
from src.api.exceptions import DashboardDbError
from src.api.repository import query
from src.api.serialize import dataframe_to_csv_text, records_from_dataframe
from src.web.formatting import fmt_quantity, fmt_signed_quantity, fmt_signed_value_dollars, fmt_value_dollars
from src.web.sql_queries import CONSENSUS_NORMALIZED_POSITIONS_SQL
from src.web.tickers import add_ticker_column

router = APIRouter(prefix="/api/consensus", tags=["consensus"])

SECTION_KEYS = ("accumulation", "distribution", "weight_growth", "latest_consensus")

SECTION_CONFIG: dict[str, dict[str, Any]] = {
    "accumulation": {
        "fund_column": "Funds Buying",
        "chart_column": "Funds Buying",
        "chart_title": "Most broadly accumulated",
        "table_columns": [
            "Ticker",
            "Issuer",
            "CUSIP",
            "Funds Buying",
            "Funds Opening",
            "Funds Increasing",
            "Transitions",
            "Share Delta",
            "Value Delta",
            "Avg Weight Delta",
        ],
        "download_name": "consensus_accumulation",
    },
    "distribution": {
        "fund_column": "Funds Selling",
        "chart_column": "Funds Selling",
        "chart_title": "Most broadly reduced",
        "table_columns": [
            "Ticker",
            "Issuer",
            "CUSIP",
            "Funds Selling",
            "Funds Closing",
            "Funds Decreasing",
            "Transitions",
            "Share Delta",
            "Value Delta",
            "Avg Weight Delta",
        ],
        "download_name": "consensus_distribution",
    },
    "weight_growth": {
        "fund_column": "Funds_With_Weight_Growth",
        "chart_column": "Funds_With_Weight_Growth",
        "chart_title": "Most common portfolio-weight increases",
        "table_columns": [
            "Ticker",
            "Issuer",
            "CUSIP",
            "Funds_With_Weight_Growth",
            "Avg Weight Delta",
            "Median Weight Delta",
            "Share Delta",
            "Value Delta",
        ],
        "download_name": "portfolio_weight_growth",
    },
    "latest_consensus": {
        "fund_column": "Latest_Holders",
        "chart_column": "Latest_Holders",
        "chart_title": "Most widely held latest-quarter positions",
        "table_columns": [
            "Ticker",
            "Issuer",
            "CUSIP",
            "Latest_Holders",
            "Previous_Holders",
            "Holder Delta",
            "Total Shares",
            "Total Value",
            "Avg Portfolio Weight",
        ],
        "download_name": "latest_consensus",
    },
}


def _filter_by_min_funds(df, fund_column: str, min_funds: int, top_n: int):
    if df.empty or fund_column not in df.columns:
        return df.copy()
    return df[df[fund_column] >= min_funds].head(top_n).copy()


def _prepare_display(df):
    if df.empty:
        return df.copy()
    display = add_ticker_column(df.copy())
    if "Aggregate_Share_Delta" in display.columns:
        display["Share Delta"] = display["Aggregate_Share_Delta"].apply(fmt_signed_quantity)
    if "Aggregate_Value_Delta_USD" in display.columns:
        display["Value Delta"] = display["Aggregate_Value_Delta_USD"].apply(fmt_signed_value_dollars)
    if "Average_Weight_Delta_Pct" in display.columns:
        display["Avg Weight Delta"] = display["Average_Weight_Delta_Pct"].apply(lambda value: f"{value:+.2f} pp")
    if "Median_Weight_Delta_Pct" in display.columns:
        display["Median Weight Delta"] = display["Median_Weight_Delta_Pct"].apply(lambda value: f"{value:+.2f} pp")
    if "Total_Shares" in display.columns:
        display["Total Shares"] = display["Total_Shares"].apply(fmt_quantity)
    if "Total_Value_USD" in display.columns:
        display["Total Value"] = display["Total_Value_USD"].apply(fmt_value_dollars)
    if "Average_Portfolio_Weight_Pct" in display.columns:
        display["Avg Portfolio Weight"] = display["Average_Portfolio_Weight_Pct"].apply(lambda value: f"{value:.2f}%")
    if "Holder_Delta" in display.columns:
        display["Holder Delta"] = display["Holder_Delta"].apply(fmt_signed_quantity)
    return display


def _visible_display_rows(df, table_columns: list[str]) -> list[dict[str, object]]:
    display = _prepare_display(df)
    if display.empty:
        return []
    visible_columns = [column for column in table_columns if column in display.columns]
    return records_from_dataframe(display[visible_columns])


def _chart_payload(df, x_col: str, title: str, top_n: int) -> dict[str, object]:
    if df.empty or x_col not in df.columns:
        return {"title": title, "x": [], "y": [], "labels": []}
    chart_df = add_ticker_column(df.head(top_n).copy())
    chart_df["Label"] = chart_df.apply(
        lambda row: str(row.get("Ticker") or row.get("Issuer") or "Unknown"),
        axis=1,
    )
    sorted_df = chart_df.sort_values(x_col)
    return {
        "title": title,
        "x": sorted_df[x_col].tolist(),
        "y": sorted_df["Label"].tolist(),
        "labels": sorted_df["Label"].tolist(),
    }


def _build_section_payload(section_key: str, source_df, *, min_funds: int, top_n: int) -> dict[str, object]:
    config = SECTION_CONFIG[section_key]
    filtered = _filter_by_min_funds(source_df, config["fund_column"], min_funds, top_n)
    return {
        "chart": _chart_payload(filtered, config["chart_column"], config["chart_title"], top_n),
        "rows": _visible_display_rows(filtered, config["table_columns"]),
        "columns": config["table_columns"],
    }


def _load_trend_tables(
    *,
    lookback_quarters: int,
    funds: str,
) -> dict[str, Any]:
    rows = query(CONSENSUS_NORMALIZED_POSITIONS_SQL)
    selected_funds = [item.strip() for item in funds.split(",") if item.strip()] or None
    return build_consensus_trend_tables(
        rows,
        lookback_quarters=lookback_quarters,
        selected_funds=selected_funds,
    )


@router.get("/trends")
def consensus_trends(
    lookback_quarters: int = Query(default=4, ge=2, le=8),
    min_funds: int = Query(default=2, ge=1, le=10),
    top_n: int = Query(default=20, ge=10, le=50),
    funds: str = Query(default=""),
) -> dict[str, object]:
    try:
        tables = _load_trend_tables(lookback_quarters=lookback_quarters, funds=funds)
    except DashboardDbError as exc:
        raise_db_error(exc)
        return {}

    metadata = tables["metadata"]
    return {
        "metadata": metadata,
        "accumulation": _build_section_payload(
            "accumulation",
            tables["accumulation"],
            min_funds=min_funds,
            top_n=top_n,
        ),
        "distribution": _build_section_payload(
            "distribution",
            tables["distribution"],
            min_funds=min_funds,
            top_n=top_n,
        ),
        "weight_growth": _build_section_payload(
            "weight_growth",
            tables["weight_growth"],
            min_funds=min_funds,
            top_n=top_n,
        ),
        "latest_consensus": _build_section_payload(
            "latest_consensus",
            tables["latest_consensus"],
            min_funds=min_funds,
            top_n=top_n,
        ),
    }


@router.get("/trends/export")
def consensus_trends_export(
    section: str = Query(...),
    lookback_quarters: int = Query(default=4, ge=2, le=8),
    min_funds: int = Query(default=2, ge=1, le=10),
    top_n: int = Query(default=20, ge=10, le=50),
    funds: str = Query(default=""),
) -> PlainTextResponse:
    if section not in SECTION_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown section: {section}")

    try:
        tables = _load_trend_tables(lookback_quarters=lookback_quarters, funds=funds)
    except DashboardDbError as exc:
        raise_db_error(exc)
        csv_text = ""
    else:
        config = SECTION_CONFIG[section]
        source_key = section
        filtered = _filter_by_min_funds(
            tables[source_key],
            config["fund_column"],
            min_funds,
            top_n,
        )
        display = _prepare_display(filtered)
        visible_columns = [column for column in config["table_columns"] if column in display.columns]
        csv_text = (
            dataframe_to_csv_text(display[visible_columns])
            if visible_columns and not display.empty
            else ""
        )

    download_name = SECTION_CONFIG[section]["download_name"]
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="f8_13f_{download_name}.csv"',
        },
    )
