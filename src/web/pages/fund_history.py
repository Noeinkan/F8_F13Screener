"""Fund History dashboard page."""

from collections.abc import Callable
from typing import Any

import pandas as pd
import streamlit as st

from src.web.charts import render_portfolio_timeline_charts, render_transition_counts_chart
from src.web.diff_views import render_detailed_diff_sections
from src.web.formatting import dataframe_to_csv_bytes, fmt_value


def transition_label(transition: dict) -> str:
    return (
        f"{transition['from_filing_date']} → {transition['to_filing_date']}  "
        f"({transition['from_accession_number']} → {transition['to_accession_number']})"
    )


def render_fund_history_page(
    get_fund_options: Callable[[], list[str]],
    require_selection: Callable[[Any | None, str], Any],
    fund_has_db_holdings: Callable[[str], bool],
    load_fund_history: Callable[[str], tuple[pd.DataFrame, list[dict]]],
):
    st.title("Fund History — Quarter over Quarter")

    funds = get_fund_options()
    if not funds:
        st.info("No data in the database yet.")
        st.stop()

    fund = require_selection(
        st.selectbox("Select fund", funds, key="fund_history_fund"),
        "Select a fund to view history.",
    )

    if not fund_has_db_holdings(fund):
        st.warning(
            "This fund is selectable from configuration, but the holdings DB does not contain rows "
            "for this fund yet."
        )

    history_df, transitions = load_fund_history(fund)

    if history_df.empty:
        st.info("No history available for this fund.")
        st.stop()

    latest_snapshot = history_df.iloc[-1]
    has_portfolio_values = history_df["Portfolio Value ($000s)"].notna().any()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Available quarters", f"{len(history_df):,}")
    c2.metric("Latest filing", latest_snapshot["Filing Date"])
    c3.metric("Current positions", f"{int(latest_snapshot['Normalized Positions']):,}")
    c4.metric(
        "Latest filing value",
        fmt_value(latest_snapshot["Portfolio Value ($000s)"]) if has_portfolio_values else "-",
    )

    st.caption(
        "The opened/closed/improved/decreased categories use share changes. "
        "Portfolio values are shown as additional context when present in the DB."
    )

    summary_export = history_df.copy()
    if has_portfolio_values:
        summary_export["Portfolio Value"] = summary_export["Portfolio Value ($000s)"].apply(fmt_value)

    st.subheader("Quarter timeline")
    st.download_button(
        "Download fund timeline",
        dataframe_to_csv_bytes(summary_export.drop(columns=["Filing Date Dt"])),
        file_name=f"f8_13f_{fund}_history.csv".replace(" ", "_"),
        mime="text/csv",
    )

    display_columns = [
        "Filing Date",
        "Accession",
        "Normalized Positions",
        "Raw 13F Lines",
    ]
    if has_portfolio_values:
        display_columns.append("Portfolio Value")
    st.dataframe(summary_export[display_columns], use_container_width=True, hide_index=True)

    render_portfolio_timeline_charts(history_df, fund)

    if not transitions:
        st.info("At least one more quarter is needed to calculate quarter-over-quarter changes.")
        st.stop()

    render_transition_counts_chart(transitions, fund)

    latest_first_transitions = list(reversed(transitions))
    selected_transition_index = st.selectbox(
        "Transition drill-down",
        options=list(range(len(latest_first_transitions))),
        index=0,
        format_func=lambda index: transition_label(latest_first_transitions[index]),
    )
    selected_transition = latest_first_transitions[selected_transition_index]

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("New positions", selected_transition["new_count"])
    d2.metric("Closed positions", selected_transition["closed_count"])
    d3.metric("Increased", selected_transition["increased_count"])
    d4.metric("Decreased", selected_transition["decreased_count"])

    st.subheader(
        f"Transition details: {selected_transition['from_filing_date']} → {selected_transition['to_filing_date']}"
    )
    render_detailed_diff_sections(selected_transition)