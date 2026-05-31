"""Holdings Search dashboard page."""

from collections.abc import Callable

import pandas as pd
import streamlit as st

from src.web.formatting import dataframe_to_csv_bytes, fmt_value


def render_holdings_search_page(query: Callable[[str, tuple], pd.DataFrame]):
    st.title("Holdings Search")

    query_text = st.text_input("Search by issuer name or CUSIP", placeholder="e.g. Apple, 037833100")

    if not query_text:
        st.info("Enter a search term to begin.")
        st.stop()

    search_pattern = f"%{query_text}%"
    df = query("""
        SELECT
            issuer_name AS "Issuer",
            cusip       AS "CUSIP",
            fund_name   AS "Fund",
            filing_date AS "Filing Date",
            shares      AS "Shares",
            value_usd   AS "Value ($000s)",
            accession_number AS "Accession"
        FROM holdings
        WHERE issuer_name LIKE ? OR cusip LIKE ?
        ORDER BY filing_date DESC, value_usd DESC NULLS LAST
    """, (search_pattern, search_pattern))

    if df.empty:
        st.warning(f"No results for '{query_text}'")
        st.stop()

    latest_dates = df.groupby("Fund", dropna=False)["Filing Date"].transform("max")
    latest = df.loc[
        df["Filing Date"].eq(latest_dates),
        ["Fund", "Filing Date", "Shares", "Value ($000s)"],
    ].copy()
    latest = latest.sort_values("Value ($000s)", ascending=False, na_position="last")

    st.success(f"{len(df)} results found")
    df["Value"] = df["Value ($000s)"].apply(fmt_value)
    df["Shares"] = df["Shares"].apply(lambda value: f"{int(value):,}" if pd.notna(value) and value else "-")

    st.download_button(
        "Download CSV results",
        dataframe_to_csv_bytes(df),
        file_name="f8_13f_search_results.csv",
        mime="text/csv",
    )
    st.dataframe(
        df[["Issuer", "CUSIP", "Fund", "Filing Date", "Shares", "Value"]],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Who holds it today (latest filing per fund)")
    if not latest.empty:
        latest["Value"] = latest["Value ($000s)"].apply(fmt_value)
        latest["Shares"] = latest["Shares"].apply(
            lambda value: f"{int(value):,}" if pd.notna(value) and value else "-"
        )
        st.dataframe(
            latest[["Fund", "Filing Date", "Shares", "Value"]],
            use_container_width=True,
            hide_index=True,
        )