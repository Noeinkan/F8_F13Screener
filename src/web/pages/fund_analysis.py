"""Unified fund analysis dashboard page."""

from collections.abc import Callable
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from src.core.diff import compute_detailed_portfolio_diff
from src.web.charts import (
    render_portfolio_timeline_charts,
    render_shares_flow_sankey,
    render_transition_counts_chart,
)
from src.web.diff_views import render_detailed_diff_sections
from src.web.fund_selection import initialize_default_fund_selection
from src.web.formatting import (
    dataframe_to_csv_bytes,
    fmt_accession_label,
    fmt_signed_value,
    fmt_transition_label,
    fmt_value,
)
from src.web.instrument_views import render_instrument_history_explorer
from src.web.sql_queries import NORMALIZED_ACCESSION_HOLDINGS_SQL, RAW_ACCESSION_HOLDINGS_SQL
from src.web.table_config import COMPACT_TABLE_HEIGHT, DEFAULT_TABLE_HEIGHT, holdings_column_config, timeline_column_config
from src.web.ui_components import render_dataframe, render_page_index, render_section, safe_file_token


def _build_accession_label_map(accessions: pd.DataFrame) -> dict[str, str]:
    return {
        row["accession_number"]: fmt_accession_label(row["filing_date"], row["accession_number"])
        for _, row in accessions.iterrows()
    }


def _transition_label(transition: dict) -> str:
    return fmt_transition_label(
        transition["from_filing_date"],
        transition["to_filing_date"],
        transition["from_accession_number"],
        transition["to_accession_number"],
    )


def _render_snapshot_mode(
    fund: str,
    require_selection: Callable[[Any | None, str], Any],
    accessions: pd.DataFrame,
    query: Callable[[str, tuple], pd.DataFrame],
) -> None:
    if accessions.empty:
        st.info("No quarter available for this fund.")
        return

    label_map = _build_accession_label_map(accessions)
    selected_acc = require_selection(
        st.selectbox(
            "Quarter (accession)",
            list(label_map.keys()),
            format_func=lambda key: label_map[key],
            key="fund_analysis_snapshot_accession",
        ),
        "Select a quarter to continue.",
    )

    raw_df = query(RAW_ACCESSION_HOLDINGS_SQL, (fund, selected_acc))
    normalized_df = query(NORMALIZED_ACCESSION_HOLDINGS_SQL, (fund, selected_acc))

    if raw_df.empty:
        st.info("No holdings found for this quarter.")
        return

    controls_col, chart_col = st.columns([1, 3])
    with controls_col:
        view_mode = st.radio(
            "Holdings view",
            ["Normalized by CUSIP", "Raw 13F lines"],
            horizontal=False,
            key="fund_analysis_snapshot_view",
        )
        top_n = st.slider("Top holdings", min_value=5, max_value=25, value=10, step=5, key="fund_analysis_snapshot_top_n")
        st.caption("Normalized aggregates rows with the same CUSIP and is best for portfolio analysis.")

    display_df = normalized_df.copy() if view_mode == "Normalized by CUSIP" else raw_df.copy()

    c1, c2, c3 = st.columns(3)
    c1.metric("Raw 13F lines", f"{len(raw_df):,}")
    c2.metric("Normalized positions", f"{len(normalized_df):,}")
    compression_ratio = 1 - (len(normalized_df) / len(raw_df))
    c3.metric("Compression", f"{compression_ratio:.1%}")

    with chart_col:
        top_holdings = display_df.head(top_n)
        fig = px.bar(
            top_holdings,
            x="Issuer",
            y="Value ($000s)",
            title=f"Top {top_n} by value - {fund}",
        )
        fig.update_layout(xaxis_tickangle=-30, height=360, margin={"l": 8, "r": 8, "t": 52, "b": 96})
        st.plotly_chart(fig, use_container_width=True)

    view_label = "normalized positions" if view_mode == "Normalized by CUSIP" else "raw 13F lines"
    st.subheader(f"All {view_label} ({len(display_df):,})")
    search_col, export_col = st.columns([3, 1])
    with search_col:
        search = st.text_input("Filter by name or CUSIP", key="fund_analysis_snapshot_filter")
    filtered_df = display_df.copy()
    if search:
        mask = (
            filtered_df["Issuer"].str.contains(search, case=False, na=False)
            | filtered_df["CUSIP"].str.contains(search, case=False, na=False)
        )
        filtered_df = filtered_df.loc[mask].copy()

    with export_col:
        view_token = "normalized" if view_mode == "Normalized by CUSIP" else "raw"
        st.download_button(
            "Download CSV",
            dataframe_to_csv_bytes(filtered_df),
            file_name=f"f8_13f_{safe_file_token(fund)}_{selected_acc}_{view_token}.csv",
            mime="text/csv",
            key="fund_analysis_snapshot_download",
        )
    render_dataframe(filtered_df, column_config=holdings_column_config(), height=DEFAULT_TABLE_HEIGHT)


def _render_timeline_mode(fund: str, history_df: pd.DataFrame, transitions: list[dict]) -> None:
    if history_df.empty:
        st.info("No history available for this fund.")
        return

    latest_snapshot = history_df.iloc[-1]
    has_portfolio_values = history_df["Portfolio Value ($000s)"].notna().any()

    previous_snapshot = history_df.iloc[-2] if len(history_df) > 1 else None
    positions_delta = None
    value_delta = None
    if previous_snapshot is not None:
        positions_delta = int(latest_snapshot["Normalized Positions"] - previous_snapshot["Normalized Positions"])
        if has_portfolio_values and pd.notna(latest_snapshot["Portfolio Value ($000s)"]) and pd.notna(previous_snapshot["Portfolio Value ($000s)"]):
            value_delta = latest_snapshot["Portfolio Value ($000s)"] - previous_snapshot["Portfolio Value ($000s)"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Available quarters", f"{len(history_df):,}")
    c2.metric("Latest filing", latest_snapshot["Filing Date"])
    c3.metric(
        "Current positions",
        f"{int(latest_snapshot['Normalized Positions']):,}",
        delta=f"{positions_delta:+,}" if positions_delta is not None else None,
    )
    c4.metric(
        "Latest filing value",
        fmt_value(latest_snapshot["Portfolio Value ($000s)"]) if has_portfolio_values else "-",
        delta=fmt_signed_value(value_delta) if value_delta is not None else None,
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
        key="fund_analysis_timeline_download",
    )

    display_columns = [
        "Filing Date",
        "Accession",
        "Normalized Positions",
        "Raw 13F Lines",
    ]
    if has_portfolio_values:
        display_columns.append("Portfolio Value")
    render_dataframe(
        summary_export[display_columns],
        column_config=timeline_column_config(),
        height=COMPACT_TABLE_HEIGHT,
    )

    render_portfolio_timeline_charts(history_df, fund, key_prefix="fund_analysis_timeline")

    if not transitions:
        st.info("At least one more quarter is needed to calculate quarter-over-quarter changes.")
        return

    render_transition_counts_chart(transitions, fund, key="fund_analysis_timeline_transitions")

    latest_first_transitions = list(reversed(transitions))
    selected_transition_index = st.selectbox(
        "Transition drill-down",
        options=list(range(len(latest_first_transitions))),
        index=0,
        format_func=lambda index: _transition_label(latest_first_transitions[index]),
        key="fund_analysis_timeline_transition",
    )
    selected_transition = latest_first_transitions[selected_transition_index]

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("New positions", selected_transition["new_count"])
    d2.metric("Closed positions", selected_transition["closed_count"])
    d3.metric("Increased", selected_transition["increased_count"])
    d4.metric("Decreased", selected_transition["decreased_count"])

    st.subheader(
        f"Transition details: {selected_transition['from_filing_date']} -> {selected_transition['to_filing_date']}"
    )
    render_detailed_diff_sections(selected_transition, dense=True)


def _render_compare_mode(
    fund: str,
    require_selection: Callable[[Any | None, str], Any],
    accessions: pd.DataFrame,
    history_df: pd.DataFrame,
    transitions: list[dict],
    load_normalized_positions_map: Callable[[str, str], dict],
    load_fund_instrument_history: Callable[[str], pd.DataFrame],
) -> None:
    if len(accessions) < 2:
        st.warning("At least 2 quarters are required to compute the diff.")
        return

    label_map = _build_accession_label_map(accessions)
    acc_list = list(label_map.keys())

    preset = st.radio(
        "Comparison preset",
        ["Latest vs previous", "Manual quarters"],
        horizontal=True,
        key="fund_analysis_compare_preset",
    )

    if preset == "Latest vs previous":
        acc_new = acc_list[0]
        acc_old = acc_list[1]
        col1, col2 = st.columns(2)
        col1.text_input("NEW quarter", label_map[acc_new], disabled=True, key="fund_analysis_compare_latest_new")
        col2.text_input("PREVIOUS quarter", label_map[acc_old], disabled=True, key="fund_analysis_compare_latest_old")
    else:
        col1, col2 = st.columns(2)
        with col1:
            acc_new = require_selection(
                st.selectbox(
                    "NEW quarter",
                    acc_list,
                    format_func=lambda key: label_map[key],
                    index=0,
                    key="fund_analysis_compare_acc_new",
                ),
                "Select the new quarter.",
            )
        with col2:
            acc_old = require_selection(
                st.selectbox(
                    "PREVIOUS quarter",
                    acc_list,
                    format_func=lambda key: label_map[key],
                    index=1,
                    key="fund_analysis_compare_acc_old",
                ),
                "Select the previous quarter.",
            )

    if acc_new == acc_old:
        st.warning("Select two different quarters.")
        return

    old_map = load_normalized_positions_map(fund, acc_old)
    new_map = load_normalized_positions_map(fund, acc_new)
    diff = compute_detailed_portfolio_diff(old_map, new_map, min_change_pct=0)

    st.caption(
        "Normalized comparison by position. Common shares, CALLs, and PUTs remain separate "
        "even when they share the same underlying CUSIP; positions without CUSIP use the fallback "
        "issuer/class/put-call."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("New positions", len(diff["new_positions"]))
    c2.metric("Closed positions", len(diff["closed_positions"]))
    c3.metric("Increased", len(diff["increased"]))
    c4.metric("Decreased", len(diff["decreased"]))
    st.subheader("Shares Flow Sankey")
    st.caption(
        "Delta Shares = NEW quarter shares - PREVIOUS quarter shares. "
        "Line thickness represents share count, not market value."
    )
    top_n_flows = st.slider("Show top N flows", min_value=5, max_value=50, value=20, step=5, key="fund_analysis_compare_top_n")
    render_shares_flow_sankey(diff, fund, top_n=top_n_flows)

    if not history_df.empty:
        st.subheader("Fund historical trend")
        st.caption(
            "These charts use all filings available in the DB for the selected fund, "
            "so the comparison between the two quarters remains readable in historical context."
        )
        render_portfolio_timeline_charts(history_df, fund, key_prefix="fund_analysis_compare")
        if transitions:
            render_transition_counts_chart(
                transitions,
                fund,
                title=f"Portfolio changes over time - {fund}",
                key="fund_analysis_compare_transitions",
            )
        with st.expander("Instrument history explorer", expanded=False):
            instrument_history_df = load_fund_instrument_history(fund)
            render_instrument_history_explorer(history_df, instrument_history_df, fund, require_selection)

    render_detailed_diff_sections(diff, dense=True)


def render_fund_analysis_page(
    get_fund_options: Callable[[], list[str]],
    require_selection: Callable[[Any | None, str], Any],
    fund_has_db_holdings: Callable[[str], bool],
    load_accessions_for_fund: Callable[[str], pd.DataFrame],
    load_fund_history: Callable[[str], tuple[pd.DataFrame, list[dict]]],
    load_normalized_positions_map: Callable[[str, str], dict],
    load_fund_instrument_history: Callable[[str], pd.DataFrame],
    query: Callable[[str, tuple], pd.DataFrame],
) -> None:
    st.title("Fund Analysis")
    st.caption("One fund workspace for current holdings, historical trajectory, and quarter-over-quarter changes.")

    funds = get_fund_options()
    if not funds:
        st.info("No data in the database yet.")
        st.stop()

    initialize_default_fund_selection(st.session_state, "fund_analysis_selected_fund", funds)

    fund = require_selection(
        st.selectbox("Select fund", funds, key="fund_analysis_selected_fund"),
        "Select a fund to continue.",
    )

    if not fund_has_db_holdings(fund):
        st.warning(
            "This fund is selectable from configuration, but the holdings DB does not contain rows "
            "for this fund yet. Some views may use local cache metadata when available."
        )

    accessions = load_accessions_for_fund(fund)
    history_df, transitions = load_fund_history(fund)

    if not history_df.empty:
        latest_snapshot = history_df.iloc[-1]
        top_cols = st.columns(4)
        top_cols[0].metric("Selected fund", fund)
        top_cols[1].metric("Latest filing", latest_snapshot["Filing Date"])
        top_cols[2].metric("Quarters", f"{len(history_df):,}")
        top_cols[3].metric("Current positions", f"{int(latest_snapshot['Normalized Positions']):,}")

    render_page_index([
        ("Snapshot", "Snapshot"),
        ("Timeline", "Timeline"),
        ("Compare", "Compare"),
    ])

    render_section("Snapshot", "Inspect one filing: normalized portfolio, raw 13F lines, top holdings, and export.")
    _render_snapshot_mode(fund, require_selection, accessions, query)

    st.divider()
    render_section("Timeline", "Scan every quarter available for the fund and drill into the latest portfolio transition.")
    _render_timeline_mode(fund, history_df, transitions)

    st.divider()
    render_section("Compare", "Compare two quarters, review position flows, and inspect detailed share changes.")
    _render_compare_mode(
        fund,
        require_selection,
        accessions,
        history_df,
        transitions,
        load_normalized_positions_map,
        load_fund_instrument_history,
    )