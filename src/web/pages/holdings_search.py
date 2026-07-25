"""Holdings Search dashboard page."""

from collections.abc import Callable
from typing import Any
import re

import pandas as pd
import streamlit as st

from src.web.formatting import dataframe_to_csv_bytes, fmt_value_dollars
from src.web.instrument_transforms import add_instrument_type_column, style_instrument_type_column
from src.web.table_config import DEFAULT_TABLE_HEIGHT, holdings_column_config
from src.web.ticker_index import cusips_for_ticker, is_ticker_like
from src.web.tickers import add_ticker_column
from src.web.ui_components import render_dataframe, render_top_bar_note, render_top_bar_spacers, safe_file_token
from src.web.value_units import apply_value_multiplier_by_group, infer_value_multiplier_by_group, summarize_multipliers


MAX_SEARCH_DISPLAY_ROWS = 1_000


def _split_search_terms(query_text: str) -> list[str]:
    return [term for term in re.split(r"\s+", query_text.strip()) if term]


def _normalize_cusip_term(term: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", term)


def build_holdings_search_filter(
    query_text: str,
    *,
    ticker_cusips_by_term: dict[str, list[str]] | None = None,
) -> tuple[str, tuple[str, ...]]:
    """Build a DuckDB WHERE clause + params for the holdings search box.

    Each whitespace-separated term matches ``issuer_name`` / ``fund_name`` /
    ``cusip`` (text) OR, when the term is a ticker that resolved to CUSIPs, any
    of those CUSIPs. The ticker CUSIPs are OR-ed *inside* the term's own group,
    so a pure-ticker query like ``GOOG`` still matches Alphabet even though the
    issuer name contains no "GOOG". Terms are then AND-ed together so multiple
    terms narrow the result.

    ``ticker_cusips_by_term`` maps each term (exactly as it appears in the query)
    to the CUSIPs it resolved to. Callers pre-resolve via
    :func:`resolve_search_tickers_by_term` so this function stays pure and
    trivially testable — it never touches the ticker index itself.
    """
    ticker_cusips_by_term = ticker_cusips_by_term or {}
    clauses = []
    params: list[str] = []
    for term in _split_search_terms(query_text):
        text_pattern = f"%{term}%"
        cusip_pattern = f"%{_normalize_cusip_term(term)}%"
        ors = [
            "issuer_name ILIKE ?",
            "fund_name ILIKE ?",
            "cusip ILIKE ?",
            "REGEXP_REPLACE(COALESCE(cusip, ''), '[^0-9A-Za-z]', '', 'g') ILIKE ?",
        ]
        term_params = [text_pattern, text_pattern, text_pattern, cusip_pattern]

        term_cusips = [str(c).strip() for c in ticker_cusips_by_term.get(term, []) if c]
        if term_cusips:
            placeholders = ",".join(["?"] * len(term_cusips))
            ors.append(f"cusip IN ({placeholders})")
            term_params.extend(term_cusips)

        clauses.append("(" + " OR ".join(ors) + ")")
        params.extend(term_params)

    return " AND ".join(clauses), tuple(params)


def resolve_search_tickers_by_term(
    query_text: str, read_db_path=None
) -> dict[str, list[str]]:
    """Map each ticker-shaped term in ``query_text`` to the CUSIPs it resolves to.

    Keyed by the term exactly as it appears in the query so
    :func:`build_holdings_search_filter` can OR the CUSIPs into that term's
    clause. ``read_db_path`` selects which DB the ticker index reads from; the
    API passes its read-only snapshot so the search never opens the live writer DB.
    """
    resolved: dict[str, list[str]] = {}
    for term in _split_search_terms(query_text):
        if not is_ticker_like(term):
            continue
        cusips = cusips_for_ticker(term, read_db_path)
        if cusips:
            resolved[term] = cusips
    return resolved


def render_holdings_search_page(query: Callable[[str, tuple], pd.DataFrame], top_bar: Any | None = None):
    header = top_bar or st.container()
    with header:
        if top_bar:
            toolbar = st.container(key="f8_toolbar_row_holdings")
            with toolbar:
                search_col, note_col = st.columns([4, 2])
                with search_col:
                    query_text = st.text_input(
                        "Search by issuer, CUSIP, fund, or ticker",
                        placeholder="e.g. apple, 037833100, ORAN, AAPL berkshire",
                        key="holdings_search_query",
                    )
                with note_col:
                    note = "Ticker terms match against the holdings index. Multiple terms narrow results. CUSIP search ignores punctuation."
                    if not query_text:
                        note = f"{note} Enter a search term to begin."
                    render_top_bar_note(note)
        else:
            st.caption("Search across issuers, CUSIPs, funds, and tickers. Multiple terms narrow the result set.")

            query_text = st.text_input(
                "Search by issuer, CUSIP, fund, or ticker",
                placeholder="e.g. apple, 037833100, ORAN, AAPL berkshire",
                key="holdings_search_query",
            )
            st.caption("CUSIP search ignores punctuation, so `037-833 100` matches `037833100`. Ticker terms resolve via the holdings index.")

        if not query_text:
            if top_bar:
                render_top_bar_spacers(6)
            else:
                st.info("Enter a search term to begin.")
            st.stop()

        if top_bar:
            render_top_bar_spacers(6)

    where_sql, search_params = build_holdings_search_filter(
        query_text, ticker_cusips_by_term=resolve_search_tickers_by_term(query_text)
    )
    if not where_sql:
        with header:
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