"""Fund Detail dashboard page."""

from collections.abc import Callable
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from src.web.formatting import dataframe_to_csv_bytes
from src.web.sql_queries import NORMALIZED_ACCESSION_HOLDINGS_SQL, RAW_ACCESSION_HOLDINGS_SQL


def render_fund_detail_page(
    get_fund_options: Callable[[], list[str]],
    require_selection: Callable[[Any | None, str], Any],
    fund_has_db_holdings: Callable[[str], bool],
    load_accessions_for_fund: Callable[[str], pd.DataFrame],
    query: Callable[[str, tuple], pd.DataFrame],
):
    st.title("Fund Detail")

    funds = get_fund_options()
    if not funds:
        st.info("No data in the database yet.")
        st.stop()

    if st.session_state.get("fund_detail_selected_fund") not in funds:
        st.session_state["fund_detail_selected_fund"] = funds[0]

    fund = require_selection(
        st.selectbox("Select fund", funds, key="fund_detail_selected_fund"),
        "Select a fund to continue.",
    )

    if not fund_has_db_holdings(fund):
        st.warning(
            "This fund is selectable from configuration, but the holdings DB does not contain rows "
            "for this fund yet. The quarter list comes from local cache."
        )

    accessions = load_accessions_for_fund(fund)
    if accessions.empty:
        st.info("No quarter available for this fund.")
        st.stop()

    label_map = {
        row["accession_number"]: f"{row['filing_date']}  ({row['accession_number']})"
        for _, row in accessions.iterrows()
    }
    selected_acc = require_selection(
        st.selectbox(
            "Quarter (accession)",
            list(label_map.keys()),
            format_func=lambda key: label_map[key],
        ),
        "Select a quarter to continue.",
    )

    raw_df = query(RAW_ACCESSION_HOLDINGS_SQL, (fund, selected_acc))
    normalized_df = query(NORMALIZED_ACCESSION_HOLDINGS_SQL, (fund, selected_acc))

    if raw_df.empty:
        st.info("No holdings found for this quarter.")
        st.stop()

    c1, c2, c3 = st.columns(3)
    c1.metric("Raw 13F lines", f"{len(raw_df):,}")
    c2.metric("Normalized positions", f"{len(normalized_df):,}")
    compression_ratio = 1 - (len(normalized_df) / len(raw_df))
    c3.metric("Compression", f"{compression_ratio:.1%}")

    view_mode = st.radio(
        "Holdings view",
        ["Normalized by CUSIP", "Raw 13F lines"],
        horizontal=True,
    )
    st.caption(
        "The normalized view aggregates 13F rows with the same CUSIP, "
        "summing shares and value. This is the correct view for funds like AQR."
    )

    display_df = normalized_df.copy() if view_mode == "Normalized by CUSIP" else raw_df.copy()

    st.subheader(f"Top 10 holdings — {fund}")
    top10 = display_df.head(10)
    fig = px.bar(
        top10,
        x="Issuer",
        y="Value ($000s)",
        title=f"Top 10 by value — {fund}",
    )
    fig.update_layout(xaxis_tickangle=-30)
    st.plotly_chart(fig, use_container_width=True)

    view_label = "normalized positions" if view_mode == "Normalized by CUSIP" else "raw 13F lines"
    st.subheader(f"All {view_label} ({len(display_df):,})")
    search = st.text_input("Filter by name or CUSIP")
    filtered_df = display_df.copy()
    if search:
        mask = (
            filtered_df["Issuer"].str.contains(search, case=False, na=False)
            | filtered_df["CUSIP"].str.contains(search, case=False, na=False)
        )
        filtered_df = filtered_df.loc[mask].copy()

    st.download_button(
        "Download CSV for selected quarter",
        dataframe_to_csv_bytes(filtered_df),
        file_name=(
            f"f8_13f_{selected_acc}_normalized.csv"
            if view_mode == "Normalized by CUSIP"
            else f"f8_13f_{selected_acc}_raw.csv"
        ),
        mime="text/csv",
    )
    st.dataframe(filtered_df, use_container_width=True, hide_index=True)