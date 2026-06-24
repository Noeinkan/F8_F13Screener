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
    fmt_eu_date,
    fmt_quantity,
    fmt_signed_pct,
    fmt_signed_quantity,
    fmt_signed_value_dollars,
    fmt_transition_label,
    fmt_value_dollars,
)
from src.web.instrument_transforms import add_instrument_type_column, style_instrument_type_column
from src.web.sql_queries import NORMALIZED_ACCESSION_HOLDINGS_SQL, RAW_ACCESSION_HOLDINGS_SQL
from src.web.table_config import COMPACT_TABLE_HEIGHT, DEFAULT_TABLE_HEIGHT, diff_column_config, holdings_column_config, timeline_column_config
from src.web.tickers import add_ticker_column
from src.web.ui_components import render_compact_page_index, render_dataframe, render_page_index, render_section, render_top_bar_spacers, safe_file_token
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


def _position_label(position: dict | None) -> str:
    if not position:
        return "-"
    issuer = str(position.get("issuer_name") or "").strip()
    put_call = str(position.get("put_call") or "").strip().upper()
    share_class = str(position.get("share_class") or "").strip()
    suffix = " ".join(part for part in [share_class, put_call] if part)
    return f"{issuer} ({suffix})" if issuer and suffix else issuer or str(position.get("cusip") or "-")


def _largest_by_abs(items: list[dict], key: str) -> dict | None:
    if not items:
        return None
    return max(items, key=lambda item: abs(float(item.get(key) or 0)))


def _largest_by_value(items: list[dict], key: str) -> dict | None:
    if not items:
        return None
    return max(items, key=lambda item: float(item.get(key) or 0))


def _render_compare_highlights(diff: dict) -> None:
    new_position = _largest_by_value(diff["new_positions"], "shares")
    closed_position = _largest_by_value(diff["closed_positions"], "shares")
    increased_position = _largest_by_abs(diff["increased"], "share_change")
    decreased_position = _largest_by_abs(diff["decreased"], "share_change")

    highlight_cols = st.columns(4)
    highlights = [
        ("Largest new", new_position, fmt_quantity(new_position.get("shares")) if new_position else "-", "reported shares"),
        ("Largest closed", closed_position, fmt_quantity(closed_position.get("shares")) if closed_position else "-", "previous shares"),
        (
            "Largest increase",
            increased_position,
            fmt_signed_quantity(increased_position.get("share_change")) if increased_position else "-",
            fmt_signed_pct(increased_position.get("pct_change")) if increased_position else "-",
        ),
        (
            "Largest decrease",
            decreased_position,
            fmt_signed_quantity(decreased_position.get("share_change")) if decreased_position else "-",
            fmt_signed_pct(decreased_position.get("pct_change")) if decreased_position else "-",
        ),
    ]
    for column, (label, position, value, context) in zip(highlight_cols, highlights, strict=False):
        column.metric(label, value, delta=None if context == "-" else context)
        column.caption(_position_label(position))


def _infer_diff_value_multiplier(diff: dict) -> int:
    value_rows = []
    for position in diff["new_positions"] + diff["closed_positions"]:
        value_rows.append({"value": position.get("value_usd"), "shares": position.get("shares")})
    for position in diff["increased"] + diff["decreased"]:
        value_rows.append({"value": position.get("old_value_usd"), "shares": position.get("old_shares")})
        value_rows.append({"value": position.get("new_value_usd"), "shares": position.get("new_shares")})
    return infer_value_multiplier_from_frame(pd.DataFrame(value_rows), value_col="value", shares_col="shares")


def _fmt_value_move(value: Any, multiplier: int) -> str:
    if value is None or pd.isna(value):
        return "-"
    return fmt_signed_value_dollars(float(value) * multiplier)


def _build_top_movers_table(diff: dict, *, limit: int = 12) -> tuple[pd.DataFrame, int]:
    value_multiplier = _infer_diff_value_multiplier(diff)
    rows = []

    for position in diff["new_positions"]:
        shares = float(position.get("shares") or 0)
        rows.append({
            "Ticker": position.get("cusip"),
            "Type": "Purchase",
            "Movement": "New",
            "Issuer": position.get("issuer_name"),
            "Delta Shares": fmt_signed_quantity(shares),
            "Delta %": "New",
            "Delta Value": _fmt_value_move(position.get("value_usd"), value_multiplier),
            "Shares Before": "-",
            "Shares After": fmt_quantity(shares),
            "CUSIP": position.get("cusip"),
            "Class": position.get("share_class"),
            "Put/Call": position.get("put_call"),
            "_Sort Magnitude": abs(shares),
        })

    for position in diff["closed_positions"]:
        shares = float(position.get("shares") or 0)
        value = position.get("value_usd")
        rows.append({
            "Ticker": position.get("cusip"),
            "Type": "Sell",
            "Movement": "Closed",
            "Issuer": position.get("issuer_name"),
            "Delta Shares": fmt_signed_quantity(-shares),
            "Delta %": "Closed",
            "Delta Value": _fmt_value_move(-float(value), value_multiplier) if value is not None and not pd.isna(value) else "-",
            "Shares Before": fmt_quantity(shares),
            "Shares After": "-",
            "CUSIP": position.get("cusip"),
            "Class": position.get("share_class"),
            "Put/Call": position.get("put_call"),
            "_Sort Magnitude": abs(shares),
        })

    for movement, positions in [("Increase", diff["increased"]), ("Decrease", diff["decreased"])]:
        for position in positions:
            share_change = float(position.get("share_change") or 0)
            rows.append({
                "Ticker": position.get("cusip"),
                "Type": "Purchase" if share_change > 0 else "Sell",
                "Movement": movement,
                "Issuer": position.get("issuer_name"),
                "Delta Shares": fmt_signed_quantity(share_change),
                "Delta %": fmt_signed_pct(position.get("pct_change")),
                "Delta Value": _fmt_value_move(position.get("value_change"), value_multiplier),
                "Shares Before": fmt_quantity(position.get("old_shares")),
                "Shares After": fmt_quantity(position.get("new_shares")),
                "CUSIP": position.get("cusip"),
                "Class": position.get("share_class"),
                "Put/Call": position.get("put_call"),
                "_Sort Magnitude": abs(share_change),
            })

    if not rows:
        return pd.DataFrame(), value_multiplier

    movers_df = pd.DataFrame(rows).sort_values(["_Sort Magnitude", "Issuer"], ascending=[False, True]).head(limit)
    movers_df = add_ticker_column(movers_df.drop(columns=["_Sort Magnitude"]))
    return movers_df, value_multiplier


def _render_top_movers_table(diff: dict) -> None:
    movers_df, value_multiplier = _build_top_movers_table(diff)
    if movers_df.empty:
        return

    st.subheader("Top movers")
    st.caption(
        "Largest position changes by absolute share delta across new, closed, increased, and decreased positions "
        f"(value multiplier x{value_multiplier})."
    )
    render_dataframe(
        style_instrument_type_column(movers_df),
        column_config=diff_column_config(),
        height=COMPACT_TABLE_HEIGHT,
    )


def _fmt_price(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"${float(value):,.2f}"


def _option_kind(value: Any) -> str:
    return str(value or "").strip().upper()


def _infer_assumed_transaction_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""

    year = int(parsed.year)
    month = int(parsed.month)
    day = int(parsed.day)
    quarter_end_days = {3: 31, 6: 30, 9: 30, 12: 31}
    if month in quarter_end_days and day == quarter_end_days[month]:
        return parsed.strftime("%Y-%m-%d")
    if month <= 3:
        return f"{year - 1}-12-31"
    if month <= 6:
        return f"{year}-03-31"
    if month <= 9:
        return f"{year}-06-30"
    return f"{year}-09-30"


def _add_position_insight_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    shares = pd.to_numeric(df["Shares"], errors="coerce")
    values = pd.to_numeric(df["Value (USD)"], errors="coerce")
    option_kinds = df["Put/Call"].apply(_option_kind)
    is_option = option_kinds.isin(["PUT", "CALL"])

    df["Assumed Transaction Date"] = df["Filing Date"].apply(_infer_assumed_transaction_date)
    df["Implied Filing Price"] = values.div(shares.where(shares != 0))
    df["Estimated Contracts"] = (shares / 100).where(is_option)
    df["_Insight Key"] = df.apply(
        lambda row: str(row.get("CUSIP") or "").strip()
        or "|".join(str(row.get(part) or "").strip() for part in ["Issuer", "Class", "Put/Call"]),
        axis=1,
    )
    return df


def _render_position_insight(source_df: pd.DataFrame) -> None:
    if source_df.empty:
        st.info("No positions match the current filter.")
        return

    candidate_df = source_df[source_df["_Insight Key"].astype(str).str.strip() != ""].copy()
    if candidate_df.empty:
        st.info("No position keys are available for insight extraction.")
        return

    candidate_order = (
        candidate_df.groupby("_Insight Key", dropna=False)["Value (USD)"]
        .sum()
        .sort_values(ascending=False)
        .index
        .tolist()
    )
    labels = {}
    for insight_key in candidate_order:
        group = candidate_df[candidate_df["_Insight Key"] == insight_key]
        top_row = group.sort_values("Value (USD)", ascending=False).iloc[0]
        ticker = str(top_row.get("Ticker") or "").strip()
        issuer = str(top_row.get("Issuer") or "").strip()
        cusip = str(top_row.get("CUSIP") or "").strip()
        label_parts = [part for part in [ticker, issuer, cusip] if part]
        labels[insight_key] = " | ".join(label_parts) or str(insight_key)

    selected_key = st.selectbox(
        "Position insight",
        candidate_order,
        format_func=lambda key: labels.get(key, str(key)),
        key="fund_analysis_snapshot_position_insight",
    )
    selected_df = candidate_df[candidate_df["_Insight Key"] == selected_key].copy()
    shares = pd.to_numeric(selected_df["Shares"], errors="coerce")
    values = pd.to_numeric(selected_df["Value (USD)"], errors="coerce")
    option_kinds = selected_df["Put/Call"].apply(_option_kind)
    option_mask = option_kinds.isin(["PUT", "CALL"])
    common_mask = ~option_mask
    implied_prices = pd.to_numeric(selected_df["Implied Filing Price"], errors="coerce").dropna()

    transaction_dates = sorted({fmt_eu_date(value) for value in selected_df.get("Assumed Transaction Date", pd.Series(dtype=object)).dropna() if value})
    transaction_date_label = ", ".join(transaction_dates) if transaction_dates else "-"
    price_label = _fmt_price(implied_prices.median() if not implied_prices.empty else None)

    metric_cols = st.columns(4)
    metric_cols[0].metric("Assumed transaction date", transaction_date_label)
    metric_cols[1].metric("Implied filing price", price_label)
    metric_cols[2].metric("Reported value", fmt_value_dollars(values.fillna(0).sum()))
    metric_cols[3].metric("Underlying shares", fmt_quantity(shares.fillna(0).sum()))
    st.caption(
        "Assumed transaction date is inferred as the 13F report-period quarter end from the SEC filing date; "
        "13F filings do not provide per-position trade dates."
    )

    if option_mask.any():
        option_df = selected_df[option_mask].copy()
        option_values = pd.to_numeric(option_df["Value (USD)"], errors="coerce").fillna(0)
        option_shares = pd.to_numeric(option_df["Shares"], errors="coerce").fillna(0)
        option_contracts = pd.to_numeric(option_df["Estimated Contracts"], errors="coerce").fillna(0)
        by_kind = option_df.assign(_value=option_values, _contracts=option_contracts).groupby(option_df["Put/Call"].apply(_option_kind)).agg(
            notional=("_value", "sum"),
            contracts=("_contracts", "sum"),
        )
        option_parts = [
            f"{kind}: {fmt_value_dollars(row['notional'])} notional, {fmt_quantity(row['contracts'])} contracts"
            for kind, row in by_kind.iterrows()
        ]
        st.caption("Option rows: " + "; ".join(option_parts))
        st.caption(
            "13F option rows are treated as underlying notional exposure. The reported value is not the option premium paid."
        )

        if common_mask.any():
            common_value = values[common_mask].fillna(0).sum()
            common_shares = shares[common_mask].fillna(0).sum()
            option_value = option_values.sum()
            structure_ratio = option_value / common_value if common_value else None
            ratio_text = f"; option/common reported value ratio: {structure_ratio:,.1f}x" if structure_ratio else ""
            st.caption(
                "Same-CUSIP common share stub: "
                f"{fmt_quantity(common_shares)} shares, {fmt_value_dollars(common_value)} reported value{ratio_text}."
            )

    detail_cols = [
        "Ticker",
        "Type",
        "Assumed Transaction Date",
        "Filing Date",
        "Issuer",
        "CUSIP",
        "Class",
        "Shares",
        "Put/Call",
        "Value",
        "Implied Filing Price",
        "Estimated Contracts",
    ]
    render_dataframe(
        style_instrument_type_column(selected_df[[col for col in detail_cols if col in selected_df.columns]]),
        column_config=holdings_column_config(),
        height=COMPACT_TABLE_HEIGHT,
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
    display_df = _add_position_insight_columns(display_df)
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

        with st.expander("Position insight", expanded=True):
            _render_position_insight(filtered_df)

        export_df = filtered_df.drop(columns=["_Insight Key"], errors="ignore")

        with export_col:
            view_token = "normalized" if view_mode == "Normalized by CUSIP" else "raw"
            st.download_button(
                "Download CSV",
                dataframe_to_csv_bytes(export_df),
                file_name=f"f8_13f_{safe_file_token(fund)}_{selected_acc}_{view_token}.csv",
                mime="text/csv",
                key="fund_analysis_snapshot_download",
            )
        table_df = filtered_df.drop(columns=["Value ($000s)", "Value (USD)", "_Insight Key"], errors="ignore")
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
        "Timeline is the quarter-level history view. Use Compare for position-level change tables and exports."
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

    with st.expander("Quarter-over-quarter activity", expanded=True):
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
        if st.button("Inspect selected transition in Compare", key="fund_analysis_timeline_send_to_compare"):
            st.session_state["fund_analysis_compare_preset"] = "Manual quarters"
            st.session_state["fund_analysis_compare_acc_new"] = selected_transition["to_accession_number"]
            st.session_state["fund_analysis_compare_acc_old"] = selected_transition["from_accession_number"]
            st.toast("Compare is set to the selected transition.")
        st.caption(
            "Detailed new, closed, and share-change tables are consolidated in Compare so each transition is inspected in one place."
        )


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
        "Compare is the position-level change workspace. Common shares, CALLs, and PUTs remain separate "
        "even when they share the same underlying CUSIP; positions without CUSIP use the fallback "
        "issuer/class/put-call."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("New positions", len(diff["new_positions"]))
    c2.metric("Closed positions", len(diff["closed_positions"]))
    c3.metric("Increased", len(diff["increased"]))
    c4.metric("Decreased", len(diff["decreased"]))
    _render_compare_highlights(diff)
    _render_top_movers_table(diff)

    with st.expander("Visual movement summary", expanded=True):
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
        st.divider()
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
    top_bar: Any | None = None,
) -> None:
    header = top_bar or st.container()
    with header:
        if not top_bar:
            st.caption("One fund workspace for filing inventory, quarter history, and position-level change analysis.")

        funds = get_fund_options()
        if not funds:
            st.info("No data in the database yet.")
            st.stop()

        initialize_default_fund_selection(st.session_state, "fund_analysis_selected_fund", funds)

        if top_bar:
            select_col, links_col = st.columns([3, 2])
            with select_col:
                fund = require_selection(
                    st.selectbox("Select fund", funds, key="fund_analysis_selected_fund"),
                    "Select a fund to continue.",
                )
            with links_col:
                render_compact_page_index([
                    ("Snapshot", "Snapshot"),
                    ("Timeline", "Timeline"),
                    ("Compare", "Compare"),
                ])
            render_top_bar_spacers(3)
        else:
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

    if not top_bar:
        render_page_index([
            ("Snapshot", "Snapshot"),
            ("Timeline", "Timeline"),
            ("Compare", "Compare"),
        ])

    render_section("Snapshot", "Inspect one selected filing: holdings inventory, top positions, and export.")
    _render_snapshot_mode(fund, require_selection, accessions, query)

    st.divider()
    render_section("Timeline", "Scan quarter history, portfolio trajectory, and activity levels.")
    _render_timeline_mode(fund, history_df, transitions)

    st.divider()
    render_section("Compare", "Compare two quarters and inspect position-level change tables.")
    _render_compare_mode(
        fund,
        require_selection,
        accessions,
        load_normalized_positions_map,
    )