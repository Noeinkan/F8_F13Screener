"""Cross-fund consensus analytics (no Streamlit)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

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


_PAIR_SIDE_COLUMNS = [
    "cusip",
    "issuer_name",
    "share_class",
    "put_call",
    "shares",
    "value_usd_display",
    "portfolio_weight_pct",
]

_MOVEMENT_COLUMNS = [
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
]


def _build_pair_movements(window: pd.DataFrame) -> pd.DataFrame:
    """Position moves between each fund's consecutive quarters in the window.

    One outer join over every (fund, consecutive quarter pair) at once: each
    quarter is the "after" side of the pair that ends on it and the "before"
    side of the pair that starts on it. A loop per fund and pair gave the same
    rows about ten times slower on the full dataset.
    """
    if window.empty:
        return pd.DataFrame()

    df = window[["fund_name", "quarter_period", "position_key", *_PAIR_SIDE_COLUMNS]].copy()
    df["quarter_rank"] = df.groupby("fund_name")["quarter_period"].rank(method="dense").astype(int)
    last_rank = df.groupby("fund_name")["quarter_rank"].transform("max")

    side_columns = ["fund_name", "pair_rank", "position_key", *_PAIR_SIDE_COLUMNS]
    before = df[df["quarter_rank"] < last_rank].assign(pair_rank=lambda f: f["quarter_rank"])[side_columns]
    after = df[df["quarter_rank"] > 1].assign(pair_rank=lambda f: f["quarter_rank"] - 1)[side_columns]
    if before.empty and after.empty:
        return pd.DataFrame()

    joined = before.merge(
        after,
        on=["fund_name", "pair_rank", "position_key"],
        how="outer",
        suffixes=("_before", "_after"),
        indicator=True,
    )
    if joined.empty:
        return pd.DataFrame()

    labels = df[["fund_name", "quarter_rank", "quarter_period"]].drop_duplicates(["fund_name", "quarter_rank"])
    labels = labels.assign(quarter=labels["quarter_period"].astype(str))
    from_labels = labels.rename(columns={"quarter_rank": "pair_rank", "quarter": "from_quarter"})
    to_labels = labels.assign(pair_rank=labels["quarter_rank"] - 1).rename(columns={"quarter": "to_quarter"})
    joined = joined.merge(from_labels[["fund_name", "pair_rank", "from_quarter"]], on=["fund_name", "pair_rank"], how="left")
    joined = joined.merge(to_labels[["fund_name", "pair_rank", "to_quarter"]], on=["fund_name", "pair_rank"], how="left")

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

    # The row order the per-fund loop produced: funds as they first appear in
    # the window, then pairs, then position key. Downstream "first non-empty
    # issuer name" picks depend on it.
    fund_order = {fund: index for index, fund in enumerate(pd.unique(window["fund_name"]))}
    joined["_fund_order"] = joined["fund_name"].map(fund_order)
    joined = joined.sort_values(["_fund_order", "pair_rank", "position_key"], kind="stable")
    return joined[_MOVEMENT_COLUMNS].reset_index(drop=True)


def _first_non_empty_by(frame: pd.DataFrame, group_col: str, value_col: str) -> pd.Series:
    """``_first_non_empty`` for every group at once: first non-blank value, as text."""
    text = frame[value_col].astype("string")
    cleaned = frame[[group_col]].assign(_value=text.where(text.str.strip().ne("")))
    return cleaned.groupby(group_col, dropna=False, sort=False)["_value"].first().fillna("").astype(str)


def _with_issuer_and_cusip(result: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    """Put Issuer and CUSIP first on a frame grouped by ``position_key``."""
    result.insert(0, "CUSIP", _first_non_empty_by(source, "position_key", "cusip"))
    result.insert(0, "Issuer", _first_non_empty_by(source, "position_key", "issuer_name"))
    return result.reset_index()


def _aggregate_movement_side(movements: pd.DataFrame, movement_types: set[str], side_name: str) -> pd.DataFrame:
    side = movements[movements["movement"].isin(movement_types)].copy()
    if side.empty:
        return pd.DataFrame()

    grouped = side.groupby("position_key", dropna=False, sort=False)
    result = grouped.agg(
        Funds=("fund_name", "nunique"),
        Transitions=("movement", "count"),
        Aggregate_Share_Delta=("delta_shares", "sum"),
        Aggregate_Value_Delta_USD=("delta_value_usd", "sum"),
        Average_Weight_Delta_Pct=("delta_weight_pct", "mean"),
    )
    result = _with_issuer_and_cusip(result, side)

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
        Funds_With_Weight_Growth=("fund_name", "nunique"),
        Average_Weight_Delta_Pct=("delta_weight_pct", "mean"),
        Median_Weight_Delta_Pct=("delta_weight_pct", "median"),
        Aggregate_Value_Delta_USD=("delta_value_usd", "sum"),
        Aggregate_Share_Delta=("delta_shares", "sum"),
    )
    result = _with_issuer_and_cusip(result, growth)
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
        Latest_Holders=("fund_name", "nunique"),
        Total_Shares=("shares", "sum"),
        Total_Value_USD=("value_usd_display", "sum"),
        Average_Portfolio_Weight_Pct=("portfolio_weight_pct", "mean"),
    )
    result = _with_issuer_and_cusip(result, latest)

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
