"""Cross-fund consensus trend dashboard page."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from src.web.formatting import (
    dataframe_to_csv_bytes,
    fmt_quantity,
    fmt_signed_quantity,
    fmt_signed_value_dollars,
    fmt_value_dollars,
)
from src.web.sql_queries import CONSENSUS_NORMALIZED_POSITIONS_SQL
from src.web.table_config import DEFAULT_TABLE_HEIGHT
from src.web.tickers import add_ticker_column
from src.web.ui_components import render_compact_page_index, render_dataframe, render_page_index, render_section, render_top_bar_spacers, safe_file_token
from src.web.value_units import apply_value_multiplier_by_group, infer_value_multiplier_by_group, summarize_multipliers


from src.api._consensus_analytics import MOVEMENT_BUY_TYPES, MOVEMENT_SELL_TYPES, build_consensus_trend_tables

def _display_label(row: pd.Series) -> str:
    ticker = str(row.get("Ticker") or "").strip()
    issuer = str(row.get("Issuer") or "").strip()
    return ticker or issuer or "Unknown"


def _prepare_display(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    display = add_ticker_column(df.copy())
    if "Aggregate_Share_Delta" in display.columns:
        display["Share Delta"] = display["Aggregate_Share_Delta"].apply(fmt_signed_quantity)
    if "Aggregate_Value_Delta_USD" in display.columns:
        display["Value Delta"] = display["Aggregate_Value_Delta_USD"].apply(fmt_signed_value_dollars)
    if "Average_Weight_Delta_Pct" in display.columns:
        display["Avg Weight Delta"] = display["Average_Weight_Delta_Pct"].apply(lambda value: f"{value:+.2f} pp")
    if "Median_Weight_Delta_Pct" in display.columns:
        display["Median Weight Delta"] = display["Median_Weight_Delta_Pct"].apply(lambda value: f"{value:+.2f} pp")
    if "Total_Shares" in display.columns:
        display["Total Shares"] = display["Total_Shares"].apply(fmt_quantity)
    if "Total_Value_USD" in display.columns:
        display["Total Value"] = display["Total_Value_USD"].apply(fmt_value_dollars)
    if "Average_Portfolio_Weight_Pct" in display.columns:
        display["Avg Portfolio Weight"] = display["Average_Portfolio_Weight_Pct"].apply(lambda value: f"{value:.2f}%")
    if "Holder_Delta" in display.columns:
        display["Holder Delta"] = display["Holder_Delta"].apply(fmt_signed_quantity)
    return display


def _render_bar(df: pd.DataFrame, *, x_col: str, title: str, key: str, top_n: int) -> None:
    if df.empty or x_col not in df.columns:
        st.info("No matching securities for this filter.")
        return

    chart_df = add_ticker_column(df.head(top_n).copy())
    chart_df["Label"] = chart_df.apply(_display_label, axis=1)
    fig = px.bar(
        chart_df.sort_values(x_col),
        x=x_col,
        y="Label",
        orientation="h",
        hover_data=[column for column in ["Issuer", "CUSIP"] if column in chart_df.columns],
        title=title,
    )
    fig.update_layout(height=360, margin={"l": 8, "r": 8, "t": 52, "b": 36}, yaxis_title="", xaxis_title="")
    st.plotly_chart(fig, use_container_width=True, key=key)


def _filter_by_min_funds(df: pd.DataFrame, fund_column: str, min_funds: int, top_n: int) -> pd.DataFrame:
    if df.empty or fund_column not in df.columns:
        return df.copy()
    return df[df[fund_column] >= min_funds].head(top_n).copy()


def _render_leaderboard(
    title: str,
    description: str,
    df: pd.DataFrame,
    *,
    fund_column: str,
    chart_column: str,
    chart_title: str,
    table_columns: list[str],
    download_name: str,
    top_n: int,
    key_prefix: str,
) -> None:
    render_section(title, description)
    _render_bar(df, x_col=chart_column, title=chart_title, key=f"{key_prefix}_chart", top_n=top_n)
    display = _prepare_display(df)
    if display.empty:
        st.info("No rows match the current filters.")
        return

    st.download_button(
        "Download CSV",
        dataframe_to_csv_bytes(display),
        file_name=f"f8_13f_{safe_file_token(download_name)}.csv",
        mime="text/csv",
        key=f"{key_prefix}_download",
    )
    visible_columns = [column for column in table_columns if column in display.columns]
    render_dataframe(display[visible_columns], height=DEFAULT_TABLE_HEIGHT)


def render_consensus_trends_page(
    query: Callable[[str, tuple], pd.DataFrame],
    get_fund_options: Callable[[], list[str]],
    top_bar: Any | None = None,
) -> None:
    header = top_bar or st.container()
    with header:
        page_index_items = [
            ("Accumulation", "Consensus accumulation"),
            ("Distribution", "Consensus distribution"),
            ("Weight growth", "Growing portfolio weight"),
            ("Consensus", "Crowded and emerging consensus"),
        ]
        if not top_bar:
            st.caption("Cross-fund 13F movement, ownership, and portfolio-weight patterns across recent filing quarters.")
            render_page_index(page_index_items)

    all_funds = get_fund_options()
    with header:
        if top_bar:
            toolbar = st.container(key="f8_toolbar_row_consensus")
            with toolbar:
                controls = st.columns([1.2, 1.1, 1.1, 3.6, 2.2])
                with controls[0]:
                    lookback_quarters = st.selectbox(
                        "Window",
                        [2, 4, 6, 8],
                        index=1,
                        format_func=lambda value: f"Last {value} quarters",
                        key="consensus_trends_window",
                    )
                with controls[1]:
                    min_funds = st.selectbox("Minimum funds", list(range(1, 11)), index=1, key="consensus_trends_min_funds")
                with controls[2]:
                    top_n = st.selectbox("Rows", list(range(10, 55, 5)), index=2, key="consensus_trends_top_n")
                with controls[3]:
                    selected_funds = st.multiselect(
                        "Fund subset",
                        all_funds,
                        default=[],
                        placeholder="All tracked funds",
                        key="consensus_trends_fund_subset",
                    )
                with controls[4]:
                    render_compact_page_index(page_index_items)
        else:
            toolbar = st.container()
            with toolbar:
                controls = st.columns([1, 1, 1, 3])
                with controls[0]:
                    lookback_quarters = st.selectbox(
                        "Window",
                        [2, 4, 6, 8],
                        index=1,
                        format_func=lambda value: f"Last {value} quarters",
                        key="consensus_trends_window",
                    )
                with controls[1]:
                    min_funds = st.slider("Minimum funds", min_value=1, max_value=10, value=2, step=1, key="consensus_trends_min_funds")
                with controls[2]:
                    top_n = st.slider("Rows", min_value=10, max_value=50, value=20, step=5, key="consensus_trends_top_n")
                with controls[3]:
                    selected_funds = st.multiselect(
                        "Fund subset",
                        all_funds,
                        default=[],
                        placeholder="All tracked funds",
                        key="consensus_trends_fund_subset",
                    )
        if top_bar:
            render_top_bar_spacers(8)

    with st.spinner("Loading normalized cross-fund holdings..."):
        rows = query(CONSENSUS_NORMALIZED_POSITIONS_SQL)
    if rows.empty:
        st.info("No holdings are available yet.")
        return

    tables = build_consensus_trend_tables(
        rows,
        lookback_quarters=lookback_quarters,
        selected_funds=selected_funds,
    )
    metadata = tables["metadata"]

    metric_cols = st.columns(4)
    metric_cols[0].metric("Funds analyzed", f"{metadata['funds']:,}")
    metric_cols[1].metric("Quarters", f"{len(metadata['quarters']):,}")
    metric_cols[2].metric("Latest quarter", metadata["latest_quarter"])
    metric_cols[3].metric("Position transitions", f"{metadata['movement_rows']:,}")
    if metadata["quarters"]:
        st.caption(
            "Window: "
            f"{metadata['quarters'][0]} through {metadata['quarters'][-1]}. "
            f"Value displays are auto-normalized by accession ({metadata['value_multiplier_summary']})."
        )

    accumulation = _filter_by_min_funds(tables["accumulation"], "Funds Buying", min_funds, top_n)
    distribution = _filter_by_min_funds(tables["distribution"], "Funds Selling", min_funds, top_n)
    weight_growth = _filter_by_min_funds(tables["weight_growth"], "Funds_With_Weight_Growth", min_funds, top_n)
    latest_consensus = _filter_by_min_funds(tables["latest_consensus"], "Latest_Holders", min_funds, top_n)

    _render_leaderboard(
        "Consensus accumulation",
        "Positions opened or increased by multiple funds across the selected window.",
        accumulation,
        fund_column="Funds Buying",
        chart_column="Funds Buying",
        chart_title="Most broadly accumulated",
        table_columns=[
            "Ticker",
            "Issuer",
            "CUSIP",
            "Funds Buying",
            "Funds Opening",
            "Funds Increasing",
            "Transitions",
            "Share Delta",
            "Value Delta",
            "Avg Weight Delta",
        ],
        download_name="consensus_accumulation",
        top_n=top_n,
        key_prefix="consensus_accumulation",
    )

    _render_leaderboard(
        "Consensus distribution",
        "Positions reduced or closed by multiple funds across the selected window.",
        distribution,
        fund_column="Funds Selling",
        chart_column="Funds Selling",
        chart_title="Most broadly reduced",
        table_columns=[
            "Ticker",
            "Issuer",
            "CUSIP",
            "Funds Selling",
            "Funds Closing",
            "Funds Decreasing",
            "Transitions",
            "Share Delta",
            "Value Delta",
            "Avg Weight Delta",
        ],
        download_name="consensus_distribution",
        top_n=top_n,
        key_prefix="consensus_distribution",
    )

    _render_leaderboard(
        "Growing portfolio weight",
        "Positions becoming larger parts of portfolios, including cases where share count was flat but portfolio weight rose.",
        weight_growth,
        fund_column="Funds_With_Weight_Growth",
        chart_column="Funds_With_Weight_Growth",
        chart_title="Most common portfolio-weight increases",
        table_columns=[
            "Ticker",
            "Issuer",
            "CUSIP",
            "Funds_With_Weight_Growth",
            "Avg Weight Delta",
            "Median Weight Delta",
            "Share Delta",
            "Value Delta",
        ],
        download_name="portfolio_weight_growth",
        top_n=top_n,
        key_prefix="consensus_weight_growth",
    )

    _render_leaderboard(
        "Crowded and emerging consensus",
        "Latest-quarter ownership breadth, holder-count changes, and aggregate exposure.",
        latest_consensus,
        fund_column="Latest_Holders",
        chart_column="Latest_Holders",
        chart_title="Most widely held latest-quarter positions",
        table_columns=[
            "Ticker",
            "Issuer",
            "CUSIP",
            "Latest_Holders",
            "Previous_Holders",
            "Holder Delta",
            "Total Shares",
            "Total Value",
            "Avg Portfolio Weight",
        ],
        download_name="latest_consensus",
        top_n=top_n,
        key_prefix="consensus_latest",
    )
