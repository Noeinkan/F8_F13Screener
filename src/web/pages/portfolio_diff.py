"""Portfolio Diff dashboard page."""

from collections.abc import Callable
from typing import Any

import pandas as pd
import streamlit as st

from src.core.diff import compute_detailed_portfolio_diff
from src.web.charts import (
    render_portfolio_timeline_charts,
    render_shares_flow_sankey,
    render_transition_counts_chart,
)
from src.web.diff_views import render_detailed_diff_sections
from src.web.instrument_views import render_instrument_history_explorer


def render_portfolio_diff_page(
    get_fund_options: Callable[[], list[str]],
    require_selection: Callable[[Any | None, str], Any],
    fund_has_db_holdings: Callable[[str], bool],
    load_accessions_for_fund: Callable[[str], pd.DataFrame],
    load_normalized_positions_map: Callable[[str, str], dict],
    load_fund_history: Callable[[str], tuple[pd.DataFrame, list[dict]]],
    load_fund_instrument_history: Callable[[str], pd.DataFrame],
):
    st.title("Portfolio Diff — Quarter over Quarter")

    funds = get_fund_options()
    if not funds:
        st.info("No data in the database yet.")
        st.stop()

    fund = require_selection(
        st.selectbox("Select fund", funds, key="portfolio_diff_fund"),
        "Select a fund to calculate the diff.",
    )

    if not fund_has_db_holdings(fund):
        st.warning(
            "This fund is selectable from configuration, but the holdings DB does not contain rows "
            "for this fund yet."
        )

    accessions = load_accessions_for_fund(fund)
    if len(accessions) < 2:
        st.warning("At least 2 quarters are required to compute the diff.")
        st.stop()

    label_map = {
        row["accession_number"]: f"{row['filing_date']}  ({row['accession_number']})"
        for _, row in accessions.iterrows()
    }
    acc_list = list(label_map.keys())

    col1, col2 = st.columns(2)
    with col1:
        acc_new = require_selection(
            st.selectbox("NEW quarter", acc_list, format_func=lambda key: label_map[key], index=0),
            "Select the new quarter.",
        )
    with col2:
        acc_old = require_selection(
            st.selectbox("PREVIOUS quarter", acc_list, format_func=lambda key: label_map[key], index=1),
            "Select the previous quarter.",
        )

    if acc_new == acc_old:
        st.warning("Select two different quarters.")
        st.stop()

    old_map = load_normalized_positions_map(fund, acc_old)
    new_map = load_normalized_positions_map(fund, acc_new)
    diff = compute_detailed_portfolio_diff(old_map, new_map)
    history_df, transitions = load_fund_history(fund)
    instrument_history_df = load_fund_instrument_history(fund)

    st.caption(
        "Normalized comparison by position. Common shares, CALLs, and PUTs remain separate "
        "even when they share the same underlying CUSIP; positions without CUSIP use the fallback "
        "issuer/class/put-call."
    )

    if not history_df.empty:
        st.subheader("Fund historical trend")
        st.caption(
            "These charts use all filings available in the DB for the selected fund, "
            "so the comparison between the two quarters remains readable in historical context."
        )
        render_portfolio_timeline_charts(history_df, fund)
        if transitions:
            render_transition_counts_chart(
                transitions,
                fund,
                title=f"Portfolio changes over time — {fund}",
            )
        render_instrument_history_explorer(history_df, instrument_history_df, fund, require_selection)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("New positions", len(diff["new_positions"]))
    c2.metric("Closed positions", len(diff["closed_positions"]))
    c3.metric("Increased", len(diff["increased"]))
    c4.metric("Decreased", len(diff["decreased"]))
    st.subheader("Shares flow")
    st.caption(
        "Δ Shares = NEW quarter shares - PREVIOUS quarter shares. "
        "Line thickness represents share count, not market value."
    )
    render_shares_flow_sankey(diff, fund)
    render_detailed_diff_sections(diff)