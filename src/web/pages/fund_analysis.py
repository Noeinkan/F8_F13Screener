"""Unified fund analysis dashboard page."""

from collections.abc import Callable
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from src.core.diff import compute_detailed_portfolio_diff
from src.web.charts import (
    render_portfolio_timeline_charts,
    render_shares_change_lanes,
    render_shares_flow_sankey,
    render_transition_counts_chart,
)
from src.web.diff_views import render_detailed_diff_sections
from src.web.fund_selection import initialize_default_fund_selection
from src.web.formatting import (
    dataframe_to_csv_bytes,
    fmt_accession_label,
    fmt_signed_value_dollars,
    fmt_transition_label,
    fmt_value_dollars,
)
from src.web.instrument_transforms import add_instrument_type_column, style_instrument_type_column
from src.web.sql_queries import NORMALIZED_ACCESSION_HOLDINGS_SQL, RAW_ACCESSION_HOLDINGS_SQL
from src.web.table_config import COMPACT_TABLE_HEIGHT, DEFAULT_TABLE_HEIGHT, holdings_column_config, timeline_column_config
from src.web.tickers import add_ticker_column
from src.web.ui_components import render_dataframe, render_page_index, render_section, safe_file_token
from src.web.value_units import apply_value_multiplier, infer_value_multiplier_from_frame


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
    display_df = add_ticker_column(display_df)
    value_multiplier = infer_value_multiplier_from_frame(display_df, value_col="Value ($000s)", shares_col="Shares")
    display_df["Value (USD)"] = apply_value_multiplier(display_df["Value ($000s)"], value_multiplier)
    st.caption(f"Value scale for this filing is auto-normalized (multiplier x{value_multiplier}).")

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
            y="Value (USD)",
            title=f"Top {top_n} by value - {fund}",
        )
        fig.update_layout(xaxis_tickangle=-30, height=360, margin={"l": 8, "r": 8, "t": 52, "b": 96})
        st.plotly_chart(fig, use_container_width=True)

    view_label = "normalized positions" if view_mode == "Normalized by CUSIP" else "raw 13F lines"
    with st.expander(f"All {view_label} ({len(display_df):,})", expanded=True):
        search_col, export_col = st.columns([3, 1])
        with search_col:
            search = st.text_input("Filter by ticker, name, or CUSIP", key="fund_analysis_snapshot_filter")
        filtered_df = display_df.copy()
        if search:
            mask = (
                filtered_df["Ticker"].str.contains(search, case=False, na=False)
                | filtered_df["Issuer"].str.contains(search, case=False, na=False)
                | filtered_df["CUSIP"].str.contains(search, case=False, na=False)
            )
            filtered_df = filtered_df.loc[mask].copy()
        filtered_df["Value"] = filtered_df["Value (USD)"].apply(fmt_value_dollars)
        filtered_df = add_instrument_type_column(filtered_df)

        with export_col:
            view_token = "normalized" if view_mode == "Normalized by CUSIP" else "raw"
            st.download_button(
                "Download CSV",
                dataframe_to_csv_bytes(filtered_df),
                file_name=f"f8_13f_{safe_file_token(fund)}_{selected_acc}_{view_token}.csv",
                mime="text/csv",
                key="fund_analysis_snapshot_download",
            )
        table_df = filtered_df.drop(columns=["Value ($000s)", "Value (USD)"], errors="ignore")
        render_dataframe(
            style_instrument_type_column(table_df),
            column_config=holdings_column_config(),
            height=DEFAULT_TABLE_HEIGHT,
        )


def _render_timeline_mode(fund: str, history_df: pd.DataFrame, transitions: list[dict]) -> None:
    if history_df.empty:
        st.info("No history available for this fund.")
        return

    latest_snapshot = history_df.iloc[-1]
    value_col = "Portfolio Value (USD)" if "Portfolio Value (USD)" in history_df.columns else "Portfolio Value ($000s)"
    has_portfolio_values = history_df[value_col].notna().any()

    previous_snapshot = history_df.iloc[-2] if len(history_df) > 1 else None
    positions_delta = None
    value_delta = None
    if previous_snapshot is not None:
        positions_delta = int(latest_snapshot["Normalized Positions"] - previous_snapshot["Normalized Positions"])
        if has_portfolio_values and pd.notna(latest_snapshot[value_col]) and pd.notna(previous_snapshot[value_col]):
            value_delta = latest_snapshot[value_col] - previous_snapshot[value_col]

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
        fmt_value_dollars(latest_snapshot[value_col]) if has_portfolio_values else "-",
        delta=fmt_signed_value_dollars(value_delta) if value_delta is not None else None,
    )

    if "Value Multiplier" in history_df.columns and not history_df["Value Multiplier"].dropna().empty:
        unique_multipliers = sorted({int(value) for value in history_df["Value Multiplier"].dropna().tolist()})
        multipliers_text = ", ".join(f"x{value}" for value in unique_multipliers)
        st.caption(f"Historical portfolio values are normalized by filing (multipliers: {multipliers_text}).")

    st.caption(
        "The opened/closed/improved/decreased categories use share changes. "
        "Portfolio values are shown as additional context when present in the DB."
    )

    summary_export = history_df.copy()
    if has_portfolio_values:
        summary_export["Portfolio Value"] = summary_export[value_col].apply(fmt_value_dollars)

    with st.expander("Quarter timeline", expanded=True):
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

    with st.expander("Quarter-over-quarter changes", expanded=True):
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

    with st.expander(
        f"Transition detail tables: {selected_transition['from_filing_date']} -> {selected_transition['to_filing_date']}",
        expanded=True,
    ):
        render_detailed_diff_sections(selected_transition, dense=True)


def _render_compare_mode(
    fund: str,
    require_selection: Callable[[Any | None, str], Any],
    accessions: pd.DataFrame,
    load_normalized_positions_map: Callable[[str, str], dict],
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
    with st.expander("Shares Flow Sankey", expanded=True):
        st.caption(
            "Delta Shares = NEW quarter shares - PREVIOUS quarter shares. "
            "Hover labels always show raw share deltas; thickness can be display-scaled for readability."
        )
        sankey_controls = st.columns(4)
        with sankey_controls[0]:
            top_n_buy_flows = st.slider("Top N buy flows", min_value=5, max_value=50, value=20, step=5, key="fund_analysis_compare_top_n_buys")
        with sankey_controls[1]:
            top_n_sell_flows = st.slider("Top N sell flows", min_value=5, max_value=50, value=20, step=5, key="fund_analysis_compare_top_n_sells")
        with sankey_controls[2]:
            scale_mode = st.selectbox(
                "Thickness scale",
                ["sqrt", "linear", "log"],
                format_func=lambda value: {"sqrt": "Sqrt", "linear": "Linear", "log": "Log"}[value],
                key="fund_analysis_compare_sankey_scale",
            )
        with sankey_controls[3]:
            min_visible_pct = st.slider("Min visible thickness", min_value=0, max_value=10, value=0, step=1, format="%d%%", key="fund_analysis_compare_min_visible_pct")
        render_shares_flow_sankey(
            diff,
            fund,
            top_n_buys=top_n_buy_flows,
            top_n_sells=top_n_sell_flows,
            scale_mode=scale_mode,
            min_visible_pct=float(min_visible_pct),
        )

    with st.expander("Position size before/after", expanded=True):
        render_shares_change_lanes(
            diff,
            fund,
            top_n_buys=top_n_buy_flows,
            top_n_sells=top_n_sell_flows,
        )

    with st.expander("Detailed change tables", expanded=True):
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
        load_normalized_positions_map,
    )