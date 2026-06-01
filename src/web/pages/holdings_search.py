"""Holdings Search dashboard page."""

from collections.abc import Callable
import re

import pandas as pd
import streamlit as st

from src.web.formatting import dataframe_to_csv_bytes, fmt_value_dollars
from src.web.instrument_transforms import add_instrument_type_column, style_instrument_type_column
from src.web.table_config import DEFAULT_TABLE_HEIGHT, holdings_column_config
from src.web.tickers import add_ticker_column
from src.web.ui_components import render_dataframe, safe_file_token
from src.web.value_units import apply_value_multiplier_by_group, infer_value_multiplier_by_group, summarize_multipliers


MAX_SEARCH_DISPLAY_ROWS = 1_000


def _split_search_terms(query_text: str) -> list[str]:
    return [term for term in re.split(r"\s+", query_text.strip()) if term]


def _normalize_cusip_term(term: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", term)


def build_holdings_search_filter(query_text: str) -> tuple[str, tuple[str, ...]]:
    clauses = []
    params: list[str] = []
    for term in _split_search_terms(query_text):
        text_pattern = f"%{term}%"
        cusip_pattern = f"%{_normalize_cusip_term(term)}%"
        clauses.append("""
            (
                issuer_name ILIKE ?
                OR fund_name ILIKE ?
                OR cusip ILIKE ?
                OR REGEXP_REPLACE(COALESCE(cusip, ''), '[^0-9A-Za-z]', '', 'g') ILIKE ?
            )
        """)
        params.extend([text_pattern, text_pattern, text_pattern, cusip_pattern])
    return " AND ".join(clauses), tuple(params)


def render_holdings_search_page(query: Callable[[str, tuple], pd.DataFrame]):
    st.title("Holdings Search")
    st.caption("Search across issuers, CUSIPs, and funds. Multiple terms narrow the result set.")

    query_text = st.text_input(
        "Search by issuer, CUSIP, or fund",
        placeholder="e.g. apple, 037833100, apple berkshire",
        key="holdings_search_query",
    )
    st.caption("CUSIP search ignores punctuation, so `037-833 100` matches `037833100`.")

    if not query_text:
        st.info("Enter a search term to begin.")
        st.stop()

    where_sql, search_params = build_holdings_search_filter(query_text)
    if not where_sql:
        st.info("Enter a search term to begin.")
        st.stop()

    df = query(f"""
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
    """, search_params)

    if df.empty:
        st.warning(f"No results for '{query_text}'")
        st.stop()

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
    st.caption(
        "Value displays are auto-normalized by accession using implied per-share prices "
        f"(multipliers: {summarize_multipliers(multiplier_map.values())})."
    )

    funds_count = df["Fund"].nunique(dropna=True)
    issuers_count = df["Issuer"].nunique(dropna=True)
    latest_filing = df["Filing Date"].max()
    m1, m2, m3 = st.columns(3)
    m1.metric("Matching rows", f"{len(df):,}")
    m2.metric("Funds", f"{funds_count:,}")
    m3.metric("Latest filing", latest_filing or "-")

    df["Value"] = df["Value (USD)"].apply(fmt_value_dollars)
    df["Shares"] = df["Shares"].apply(lambda value: f"{int(value):,}" if pd.notna(value) and value else "-")

    st.download_button(
        "Download CSV results",
        dataframe_to_csv_bytes(df),
        file_name=f"f8_13f_search_{safe_file_token(query_text)}.csv",
        mime="text/csv",
    )
    st.subheader("Who holds it today (latest filing per fund)")
    if not latest.empty:
        latest["Value"] = latest["Value (USD)"].apply(fmt_value_dollars)
        latest["Shares"] = latest["Shares"].apply(
            lambda value: f"{int(value):,}" if pd.notna(value) and value else "-"
        )
        latest_display_df = latest[["Ticker", "Type", "Issuer", "Fund", "Filing Date", "Put/Call", "Shares", "Value"]]
        render_dataframe(
            style_instrument_type_column(latest_display_df),
            column_config=holdings_column_config(),
            height=DEFAULT_TABLE_HEIGHT,
        )

    st.subheader("All matching rows")
    display_df = df[["Ticker", "Type", "Issuer", "CUSIP", "Fund", "Filing Date", "Put/Call", "Shares", "Value"]].head(MAX_SEARCH_DISPLAY_ROWS)
    if len(df) > MAX_SEARCH_DISPLAY_ROWS:
        st.caption(f"Showing first {MAX_SEARCH_DISPLAY_ROWS:,} rows. Download the CSV for all {len(df):,} matches.")
    render_dataframe(style_instrument_type_column(display_df), column_config=holdings_column_config(), height=DEFAULT_TABLE_HEIGHT)