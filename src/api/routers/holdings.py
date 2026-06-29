"""Holdings search API routes."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

import pandas as pd

from src.api.deps import raise_db_error
from src.api.exceptions import DashboardDbError
from src.api.repository import query
from src.api.serialize import dataframe_to_csv_text, records_from_dataframe
from src.web.formatting import fmt_value_dollars
from src.web.instrument_transforms import add_instrument_type_column
from src.web.pages.holdings_search import MAX_SEARCH_DISPLAY_ROWS, build_holdings_search_filter
from src.web.tickers import add_ticker_column
from src.web.value_units import apply_value_multiplier_by_group, infer_value_multiplier_by_group, summarize_multipliers

router = APIRouter(prefix="/api/holdings", tags=["holdings"])


def _search_holdings(query_text: str, limit: int) -> dict[str, object]:
    where_sql, search_params = build_holdings_search_filter(query_text)
    if not where_sql:
        raise HTTPException(status_code=400, detail="Enter at least one search term.")

    df = query(
        f"""
        SELECT
            issuer_name AS "Issuer",
            cusip       AS "CUSIP",
            fund_name   AS "Fund",
            filing_date AS "Filing Date",
            put_call   AS "Put/Call",
            shares      AS "Shares",
            value_usd   AS "Value ($000s)",
            accession_number AS "Accession"
        FROM holdings
        WHERE {where_sql}
        ORDER BY filing_date DESC, value_usd DESC NULLS LAST
        """,
        search_params,
    )
    if df.empty:
        return {
            "query": query_text,
            "total_matches": 0,
            "funds_count": 0,
            "issuers_count": 0,
            "latest_filing": None,
            "latest_by_fund": [],
            "all_rows": [],
            "truncated": False,
        }

    df = add_instrument_type_column(add_ticker_column(df))
    latest_dates = df.groupby("Fund", dropna=False)["Filing Date"].transform("max")
    latest = df.loc[
        df["Filing Date"].eq(latest_dates),
        ["Ticker", "Type", "Issuer", "Fund", "Filing Date", "Put/Call", "Shares", "Value ($000s)", "Accession"],
    ].copy()
    latest = latest.sort_values("Value ($000s)", ascending=False, na_position="last")

    multiplier_map = infer_value_multiplier_by_group(
        df.rename(columns={"Accession": "accession_number", "Value ($000s)": "value_usd"}),
        group_col="accession_number",
        value_col="value_usd",
        shares_col="Shares",
    )
    df["Value (USD)"] = apply_value_multiplier_by_group(
        df.rename(columns={"Accession": "accession_number", "Value ($000s)": "value_usd"}),
        group_col="accession_number",
        value_col="value_usd",
        multiplier_map=multiplier_map,
    )
    latest["Value (USD)"] = apply_value_multiplier_by_group(
        latest.rename(columns={"Accession": "accession_number", "Value ($000s)": "value_usd"}),
        group_col="accession_number",
        value_col="value_usd",
        multiplier_map=multiplier_map,
    )

    df["Value"] = df["Value (USD)"].apply(fmt_value_dollars)
    df["Shares"] = df["Shares"].apply(lambda value: f"{int(value):,}" if pd.notna(value) and value else "-")
    latest["Value"] = latest["Value (USD)"].apply(fmt_value_dollars)
    latest["Shares"] = latest["Shares"].apply(lambda value: f"{int(value):,}" if pd.notna(value) and value else "-")

    display_all = df[
        ["Ticker", "Type", "Issuer", "CUSIP", "Fund", "Filing Date", "Put/Call", "Shares", "Value"]
    ].head(limit)
    display_latest = latest[["Ticker", "Type", "Issuer", "Fund", "Filing Date", "Put/Call", "Shares", "Value"]]

    return {
        "query": query_text,
        "total_matches": len(df),
        "funds_count": int(df["Fund"].nunique(dropna=True)),
        "issuers_count": int(df["Issuer"].nunique(dropna=True)),
        "latest_filing": df["Filing Date"].max(),
        "value_multiplier_summary": summarize_multipliers(multiplier_map.values()),
        "latest_by_fund": records_from_dataframe(display_latest),
        "all_rows": records_from_dataframe(display_all),
        "truncated": len(df) > limit,
    }


@router.get("/search")
def holdings_search(
    q: str = Query(min_length=1),
    limit: int = Query(default=MAX_SEARCH_DISPLAY_ROWS, ge=1, le=MAX_SEARCH_DISPLAY_ROWS),
) -> dict[str, object]:
    try:
        return _search_holdings(q, limit)
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {}


def _safe_search_file_token(query_text: str) -> str:
    token = re.sub(r"[^0-9A-Za-z._-]+", "_", query_text.strip())
    token = token.strip("_")
    return token or "search"


@router.get("/search/export")
def holdings_search_export(q: str = Query(min_length=1)) -> PlainTextResponse:
    try:
        payload = _search_holdings(q, MAX_SEARCH_DISPLAY_ROWS)
    except DashboardDbError as exc:
        raise_db_error(exc)
        csv_text = ""
    else:
        rows = payload.get("all_rows", [])
        csv_text = dataframe_to_csv_text(pd.DataFrame(rows)) if rows else ""
    file_token = _safe_search_file_token(q)
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="f8_13f_search_{file_token}.csv"',
        },
    )
