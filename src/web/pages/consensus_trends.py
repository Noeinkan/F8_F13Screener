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
from src.web.ui_components import render_dataframe, render_page_index, render_section, safe_file_token
from src.web.value_units import apply_value_multiplier_by_group, infer_value_multiplier_by_group, summarize_multipliers


MOVEMENT_BUY_TYPES = {"New position", "Increased"}
MOVEMENT_SELL_TYPES = {"Closed position", "Decreased"}


def _as_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _first_non_empty(series: pd.Series) -> str:
    for value in series:
        if value is not None and not pd.isna(value) and str(value).strip():
            return str(value)
    return ""


def _latest_quarter_snapshots(rows: pd.DataFrame, selected_funds: Iterable[str] | None = None) -> pd.DataFrame:
    if rows.empty:
        return rows.copy()

    df = rows.copy()
    if selected_funds:
        selected = {str(fund) for fund in selected_funds}
        df = df[df["fund_name"].isin(selected)].copy()
    if df.empty:
        return df

    df["filing_date_dt"] = pd.to_datetime(df["filing_date"], errors="coerce")
    df = df[df["filing_date_dt"].notna()].copy()
    if df.empty:
        return df

    df["quarter_period"] = df["filing_date_dt"].dt.to_period("Q")
    df["Quarter"] = df["quarter_period"].astype(str)

    multiplier_map = infer_value_multiplier_by_group(
        df,
        group_col="accession_number",
        value_col="value_usd",
        shares_col="shares",
    )
    df["value_usd_display"] = apply_value_multiplier_by_group(
        df,
        group_col="accession_number",
        value_col="value_usd",
        multiplier_map=multiplier_map,
    )
    df.attrs["value_multiplier_summary"] = summarize_multipliers(multiplier_map.values())

    filing_keys = (
        df[["fund_name", "Quarter", "filing_date_dt", "accession_number"]]
        .drop_duplicates()
        .sort_values(["fund_name", "Quarter", "filing_date_dt", "accession_number"])
        .drop_duplicates(["fund_name", "Quarter"], keep="last")
    )
    latest = df.merge(
        filing_keys[["fund_name", "Quarter", "accession_number"]],
        on=["fund_name", "Quarter", "accession_number"],
        how="inner",
    ).copy()
    latest.attrs["value_multiplier_summary"] = df.attrs.get("value_multiplier_summary", "x1")

    portfolio_totals = (
        latest.groupby(["fund_name", "Quarter"], dropna=False)["value_usd_display"]
        .sum(min_count=1)
        .rename("portfolio_value_usd")
        .reset_index()
    )
    latest = latest.merge(portfolio_totals, on=["fund_name", "Quarter"], how="left")
    latest["portfolio_weight_pct"] = 0.0
    valid_total = latest["portfolio_value_usd"].notna() & (latest["portfolio_value_usd"] > 0)
    latest.loc[valid_total, "portfolio_weight_pct"] = (
        latest.loc[valid_total, "value_usd_display"] / latest.loc[valid_total, "portfolio_value_usd"] * 100
    )
    latest.attrs["value_multiplier_summary"] = df.attrs.get("value_multiplier_summary", "x1")
    return latest


def _window_snapshots(snapshots: pd.DataFrame, lookback_quarters: int) -> pd.DataFrame:
    if snapshots.empty:
        return snapshots.copy()

    quarters = sorted(snapshots["quarter_period"].dropna().unique())
    selected_quarters = quarters[-lookback_quarters:]
    window = snapshots[snapshots["quarter_period"].isin(selected_quarters)].copy()
    window.attrs["selected_quarters"] = [str(quarter) for quarter in selected_quarters]
    window.attrs["value_multiplier_summary"] = snapshots.attrs.get("value_multiplier_summary", "x1")
    return window


def _build_pair_movements(window: pd.DataFrame) -> pd.DataFrame:
    movement_rows: list[pd.DataFrame] = []
    if window.empty:
        return pd.DataFrame()

    for fund, fund_df in window.groupby("fund_name", sort=False):
        fund_quarters = sorted(fund_df["quarter_period"].dropna().unique())
        for before_quarter, after_quarter in zip(fund_quarters, fund_quarters[1:]):
            before = fund_df[fund_df["quarter_period"].eq(before_quarter)].set_index("position_key")
            after = fund_df[fund_df["quarter_period"].eq(after_quarter)].set_index("position_key")
            joined = before[[
                "cusip",
                "issuer_name",
                "share_class",
                "put_call",
                "shares",
                "value_usd_display",
                "portfolio_weight_pct",
            ]].merge(
                after[[
                    "cusip",
                    "issuer_name",
                    "share_class",
                    "put_call",
                    "shares",
                    "value_usd_display",
                    "portfolio_weight_pct",
                ]],
                left_index=True,
                right_index=True,
                how="outer",
                suffixes=("_before", "_after"),
                indicator=True,
            )
            if joined.empty:
                continue

            joined = joined.reset_index()
            joined["fund_name"] = fund
            joined["from_quarter"] = str(before_quarter)
            joined["to_quarter"] = str(after_quarter)
            joined["present_before"] = joined["_merge"].ne("right_only")
            joined["present_after"] = joined["_merge"].ne("left_only")
            joined["issuer_name"] = joined["issuer_name_after"].combine_first(joined["issuer_name_before"])
            joined["cusip"] = joined["cusip_after"].combine_first(joined["cusip_before"])
            joined["share_class"] = joined["share_class_after"].combine_first(joined["share_class_before"])
            joined["put_call"] = joined["put_call_after"].combine_first(joined["put_call_before"])

            joined["shares_before"] = _as_numeric(joined["shares_before"])
            joined["shares_after"] = _as_numeric(joined["shares_after"])
            joined["value_before_usd"] = _as_numeric(joined["value_usd_display_before"])
            joined["value_after_usd"] = _as_numeric(joined["value_usd_display_after"])
            joined["weight_before_pct"] = _as_numeric(joined["portfolio_weight_pct_before"])
            joined["weight_after_pct"] = _as_numeric(joined["portfolio_weight_pct_after"])
            joined["delta_shares"] = joined["shares_after"].fillna(0) - joined["shares_before"].fillna(0)
            joined["delta_value_usd"] = joined["value_after_usd"].fillna(0) - joined["value_before_usd"].fillna(0)
            joined["delta_weight_pct"] = joined["weight_after_pct"].fillna(0) - joined["weight_before_pct"].fillna(0)
            joined["movement"] = "Unchanged"
            joined.loc[~joined["present_before"] & joined["present_after"], "movement"] = "New position"
            joined.loc[joined["present_before"] & ~joined["present_after"], "movement"] = "Closed position"
            joined.loc[joined["present_before"] & joined["present_after"] & (joined["delta_shares"] > 0), "movement"] = "Increased"
            joined.loc[joined["present_before"] & joined["present_after"] & (joined["delta_shares"] < 0), "movement"] = "Decreased"
            movement_rows.append(joined[[
                "fund_name",
                "from_quarter",
                "to_quarter",
                "position_key",
                "issuer_name",
                "cusip",
                "share_class",
                "put_call",
                "movement",
                "shares_before",
                "shares_after",
                "delta_shares",
                "value_before_usd",
                "value_after_usd",
                "delta_value_usd",
                "weight_before_pct",
                "weight_after_pct",
                "delta_weight_pct",
            ]])

    if not movement_rows:
        return pd.DataFrame()
    return pd.concat(movement_rows, ignore_index=True)


def _aggregate_movement_side(movements: pd.DataFrame, movement_types: set[str], side_name: str) -> pd.DataFrame:
    side = movements[movements["movement"].isin(movement_types)].copy()
    if side.empty:
        return pd.DataFrame()

    grouped = side.groupby("position_key", dropna=False, sort=False)
    result = grouped.agg(
        Issuer=("issuer_name", _first_non_empty),
        CUSIP=("cusip", _first_non_empty),
        Funds=("fund_name", "nunique"),
        Transitions=("movement", "count"),
        Aggregate_Share_Delta=("delta_shares", "sum"),
        Aggregate_Value_Delta_USD=("delta_value_usd", "sum"),
        Average_Weight_Delta_Pct=("delta_weight_pct", "mean"),
    ).reset_index()

    if side_name == "buying":
        result["Funds Opening"] = result["position_key"].map(
            side[side["movement"].eq("New position")].groupby("position_key")["fund_name"].nunique()
        )
        result["Funds Increasing"] = result["position_key"].map(
            side[side["movement"].eq("Increased")].groupby("position_key")["fund_name"].nunique()
        )
        result = result.rename(columns={"Funds": "Funds Buying"})
        sort_columns = ["Funds Buying", "Aggregate_Value_Delta_USD", "Aggregate_Share_Delta"]
        ascending = [False, False, False]
    else:
        result["Funds Closing"] = result["position_key"].map(
            side[side["movement"].eq("Closed position")].groupby("position_key")["fund_name"].nunique()
        )
        result["Funds Decreasing"] = result["position_key"].map(
            side[side["movement"].eq("Decreased")].groupby("position_key")["fund_name"].nunique()
        )
        result = result.rename(columns={"Funds": "Funds Selling"})
        sort_columns = ["Funds Selling", "Aggregate_Value_Delta_USD", "Aggregate_Share_Delta"]
        ascending = [False, True, True]

    count_columns = [column for column in result.columns if column.startswith("Funds ")]
    result[count_columns] = result[count_columns].fillna(0).astype(int)
    return result.sort_values(sort_columns, ascending=ascending).reset_index(drop=True)


def _aggregate_weight_growth(movements: pd.DataFrame) -> pd.DataFrame:
    growth = movements[movements["delta_weight_pct"] > 0].copy()
    if growth.empty:
        return pd.DataFrame()

    result = growth.groupby("position_key", dropna=False, sort=False).agg(
        Issuer=("issuer_name", _first_non_empty),
        CUSIP=("cusip", _first_non_empty),
        Funds_With_Weight_Growth=("fund_name", "nunique"),
        Average_Weight_Delta_Pct=("delta_weight_pct", "mean"),
        Median_Weight_Delta_Pct=("delta_weight_pct", "median"),
        Aggregate_Value_Delta_USD=("delta_value_usd", "sum"),
        Aggregate_Share_Delta=("delta_shares", "sum"),
    ).reset_index()
    return result.sort_values(
        ["Funds_With_Weight_Growth", "Average_Weight_Delta_Pct"],
        ascending=[False, False],
    ).reset_index(drop=True)


def _aggregate_latest_consensus(window: pd.DataFrame) -> pd.DataFrame:
    if window.empty:
        return pd.DataFrame()

    quarters = sorted(window["quarter_period"].dropna().unique())
    latest_quarter = quarters[-1]
    previous_quarter = quarters[-2] if len(quarters) > 1 else None
    latest = window[window["quarter_period"].eq(latest_quarter)].copy()
    if latest.empty:
        return pd.DataFrame()

    result = latest.groupby("position_key", dropna=False, sort=False).agg(
        Issuer=("issuer_name", _first_non_empty),
        CUSIP=("cusip", _first_non_empty),
        Latest_Holders=("fund_name", "nunique"),
        Total_Shares=("shares", "sum"),
        Total_Value_USD=("value_usd_display", "sum"),
        Average_Portfolio_Weight_Pct=("portfolio_weight_pct", "mean"),
    ).reset_index()

    if previous_quarter is not None:
        previous_holders = (
            window[window["quarter_period"].eq(previous_quarter)]
            .groupby("position_key")["fund_name"]
            .nunique()
            .rename("Previous_Holders")
        )
        result = result.merge(previous_holders, on="position_key", how="left")
    else:
        result["Previous_Holders"] = 0

    result["Previous_Holders"] = result["Previous_Holders"].fillna(0).astype(int)
    result["Holder_Delta"] = result["Latest_Holders"] - result["Previous_Holders"]
    return result.sort_values(
        ["Latest_Holders", "Holder_Delta", "Total_Value_USD"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def build_consensus_trend_tables(
    rows: pd.DataFrame,
    *,
    lookback_quarters: int = 4,
    selected_funds: Iterable[str] | None = None,
) -> dict[str, Any]:
    snapshots = _latest_quarter_snapshots(rows, selected_funds)
    window = _window_snapshots(snapshots, lookback_quarters)
    movements = _build_pair_movements(window)

    selected_quarters = window.attrs.get("selected_quarters", []) if not window.empty else []
    return {
        "snapshots": window,
        "movements": movements,
        "accumulation": _aggregate_movement_side(movements, MOVEMENT_BUY_TYPES, "buying") if not movements.empty else pd.DataFrame(),
        "distribution": _aggregate_movement_side(movements, MOVEMENT_SELL_TYPES, "selling") if not movements.empty else pd.DataFrame(),
        "weight_growth": _aggregate_weight_growth(movements) if not movements.empty else pd.DataFrame(),
        "latest_consensus": _aggregate_latest_consensus(window),
        "metadata": {
            "funds": int(window["fund_name"].nunique()) if not window.empty else 0,
            "quarters": selected_quarters,
            "latest_quarter": selected_quarters[-1] if selected_quarters else "-",
            "movement_rows": len(movements),
            "value_multiplier_summary": snapshots.attrs.get("value_multiplier_summary", "x1"),
        },
    }


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
) -> None:
    st.title("Consensus Trends")
    st.caption("Cross-fund 13F movement, ownership, and portfolio-weight patterns across recent filing quarters.")
    render_page_index([
        ("Accumulation", "Consensus accumulation"),
        ("Distribution", "Consensus distribution"),
        ("Weight growth", "Growing portfolio weight"),
        ("Consensus", "Crowded and emerging consensus"),
    ])

    with st.spinner("Loading normalized cross-fund holdings..."):
        rows = query(CONSENSUS_NORMALIZED_POSITIONS_SQL)
    if rows.empty:
        st.info("No holdings are available yet.")
        return

    all_funds = get_fund_options()
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