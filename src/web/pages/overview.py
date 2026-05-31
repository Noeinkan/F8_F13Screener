"""Overview dashboard page."""

from collections.abc import Callable

import pandas as pd
import plotly.express as px
import streamlit as st

from src.web.formatting import dataframe_to_csv_bytes, fmt_value
from src.web.sql_queries import (
    FILINGS_TIMELINE_SQL,
    FULL_HOLDINGS_EXPORT_SQL,
    LATEST_FUND_OVERVIEW_SQL,
    LATEST_SNAPSHOT_EXPORT_SQL,
    OVERVIEW_RECENT_ACTIVITY_SQL,
    OVERVIEW_SUMMARY_SQL,
    RECENT_FILINGS_OVERVIEW_SQL,
    TOP_HELD_SECURITIES_SQL,
)
from src.web.table_config import COMPACT_TABLE_HEIGHT, DEFAULT_TABLE_HEIGHT, common_holdings_column_config, fund_overview_column_config, recent_filings_column_config
from src.web.ui_components import render_dataframe


def render_overview_page(
    query: Callable[[str, tuple], pd.DataFrame],
    table_exists: Callable[[str], bool],
):
    st.title("Overview — 13F database status")

    dataset = query(OVERVIEW_SUMMARY_SQL)
    recent_activity = query(OVERVIEW_RECENT_ACTIVITY_SQL)
    has_portfolio_values = False

    if not dataset.empty:
        d = dataset.iloc[0]
        recent = recent_activity.iloc[0] if not recent_activity.empty else None
        has_portfolio_values = int(d["value_rows"] or 0) > 0
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Holding rows", f"{int(d['positions']):,}")
        c2.metric("13F filings", f"{int(d['filings']):,}")
        c3.metric("Covered funds", f"{int(d['funds']):,}")
        c4.metric("Latest filing", d["latest_filing_date"] or "-")
        c5.metric(
            "Filings in last ~120 days",
            f"{int(recent['recent_filings']):,}" if recent is not None else "-",
        )

        if recent is not None:
            st.caption(
                f"Funds with at least one filing in the last ~120 days: "
                f"{int(recent['recent_funds']):,}"
            )

        if not has_portfolio_values:
            st.warning(
                "Portfolio values are not available in the current database "
                "(`value_usd` / `value_x1000` are empty). "
                "This overview therefore shows useful signals based on filings, "
                "coverage, and normalized positions, which are the available data."
            )
        else:
            st.success(
                "Portfolio values are available: fund rankings and charts now use the latest valued filing."
            )

    if table_exists("statistics"):
        stats = query("SELECT * FROM statistics WHERE id = 1")
        if not stats.empty:
            s = stats.iloc[0]
            if any(int(s[col]) for col in ("total_checked", "matched", "filtered")):
                st.caption(
                    "Feed monitor stats: "
                    f"checked {int(s['total_checked']):,} | "
                    f"matched {int(s['matched']):,} | "
                    f"filtered {int(s['filtered']):,}"
                )

    st.subheader("Latest filing per fund")
    st.caption(
        "For each fund, we show only the latest available filing, with raw row count and "
        "CUSIP-normalized count. Select a row to open the fund workspace."
    )
    df = query(LATEST_FUND_OVERVIEW_SQL)

    if df.empty:
        st.info("No data in the database yet.")
    else:
        full_export = query(FULL_HOLDINGS_EXPORT_SQL)
        latest_snapshot = query(LATEST_SNAPSHOT_EXPORT_SQL)
        recent_filings = query(RECENT_FILINGS_OVERVIEW_SQL)
        timeline_df = query(FILINGS_TIMELINE_SQL)
        common_holdings = query(TOP_HELD_SECURITIES_SQL)

        d1, d2 = st.columns(2)
        d1.download_button(
            "Download full holdings CSV",
            dataframe_to_csv_bytes(full_export),
            file_name="f8_13f_all_holdings.csv",
            mime="text/csv",
            use_container_width=True,
        )
        d2.download_button(
            "Download latest snapshot per fund",
            dataframe_to_csv_bytes(latest_snapshot),
            file_name="f8_13f_latest_snapshot.csv",
            mime="text/csv",
            use_container_width=True,
        )

        filter_text = st.text_input(
            "Filter fund",
            placeholder="es. AQR, Berkshire, Appaloosa",
        )
        filtered_df = df.copy()
        if filter_text:
            filtered_df = filtered_df[
                filtered_df["Fund"].str.contains(filter_text, case=False, na=False)
            ].copy()

        if has_portfolio_values:
            filtered_df["Portfolio Value"] = filtered_df["value_sum"].apply(fmt_value)

        display_columns = [
            "Fund",
            "Quarters",
            "Latest Filing",
            "Raw 13F Lines",
            "Normalized Positions",
            "Distinct CUSIPs",
        ]
        if has_portfolio_values:
            display_columns.append("Portfolio Value")
        selection_event = st.dataframe(
            filtered_df[display_columns],
            use_container_width=True,
            hide_index=True,
            height=DEFAULT_TABLE_HEIGHT,
            column_config=fund_overview_column_config(),
            on_select="rerun",
            selection_mode="single-row",
        )
        selected_rows = selection_event.get("selection", {}).get("rows", []) if selection_event else []
        if selected_rows:
            selected_idx = selected_rows[0]
            if selected_idx < len(filtered_df):
                selected_fund = filtered_df.iloc[selected_idx]["Fund"]
                st.session_state["fund_analysis_selected_fund"] = selected_fund
                st.session_state["pending_sidebar_page"] = "Fund Analysis"
                st.rerun()

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            if has_portfolio_values:
                fig = px.bar(
                    df.sort_values("value_sum", ascending=False).head(20),
                    x="Fund",
                    y="value_sum",
                    labels={"value_sum": "Value ($000s)", "Fund": ""},
                    title="Top 20 funds by latest filing value",
                )
            else:
                fig = px.bar(
                    df.head(20),
                    x="Fund",
                    y="Normalized Positions",
                    labels={"Normalized Positions": "Positions", "Fund": ""},
                    title="Top 20 funds by normalized positions",
                )
            fig.update_layout(xaxis_tickangle=-40)
            st.plotly_chart(fig, use_container_width=True)

        with chart_col2:
            if not timeline_df.empty:
                fig = px.line(
                    timeline_df.tail(24),
                    x="Month",
                    y="Filings",
                    markers=True,
                    title="Filings stored per month",
                )
                st.plotly_chart(fig, use_container_width=True)

        insights_col1, insights_col2 = st.columns(2)
        with insights_col1:
            st.subheader("Most recent filings")
            render_dataframe(
                recent_filings,
                column_config=recent_filings_column_config(),
                height=COMPACT_TABLE_HEIGHT,
            )

        with insights_col2:
            st.subheader("Most common holdings today")
            render_dataframe(
                common_holdings,
                column_config=common_holdings_column_config(),
                height=COMPACT_TABLE_HEIGHT,
            )