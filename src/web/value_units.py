"""Shared value-unit inference and scaling helpers for dashboard views."""

from __future__ import annotations

import math
from typing import Iterable

import pandas as pd

CANDIDATE_VALUE_MULTIPLIERS = (1, 1000)
FALLBACK_VALUE_MULTIPLIER = 1000


def _score_price_scale(median_price: float, target_price: float = 100.0) -> float:
    if median_price <= 0:
        return float("inf")
    return abs(math.log10(median_price) - math.log10(target_price))


def infer_value_multiplier_from_prices(prices_dollars: pd.Series) -> int:
    """
    Infer whether stored values are likely dollars (x1) or thousands (x1000).

    The chosen scale is the one whose median implied per-share price is closer to
    a typical equity price anchor in log space.
    """
    valid = pd.to_numeric(prices_dollars, errors="coerce")
    valid = valid[(valid > 0) & valid.notna()]
    if valid.empty:
        return FALLBACK_VALUE_MULTIPLIER

    median_dollars = float(valid.median())
    scored = {
        multiplier: _score_price_scale(median_dollars * multiplier)
        for multiplier in CANDIDATE_VALUE_MULTIPLIERS
    }
    return min(scored, key=scored.get)


def infer_value_multiplier_from_frame(
    frame: pd.DataFrame,
    *,
    value_col: str,
    shares_col: str,
) -> int:
    if frame.empty or value_col not in frame.columns or shares_col not in frame.columns:
        return FALLBACK_VALUE_MULTIPLIER

    values = pd.to_numeric(frame[value_col], errors="coerce")
    shares = pd.to_numeric(frame[shares_col], errors="coerce")
    valid = pd.DataFrame({"value": values, "shares": shares})
    valid = valid[(valid["value"] > 0) & (valid["shares"] > 0)]
    if valid.empty:
        return FALLBACK_VALUE_MULTIPLIER

    implied_prices = valid["value"] / valid["shares"]
    return infer_value_multiplier_from_prices(implied_prices)


def infer_value_multiplier_by_group(
    frame: pd.DataFrame,
    *,
    group_col: str,
    value_col: str,
    shares_col: str,
) -> dict[str, int]:
    if frame.empty or group_col not in frame.columns:
        return {}

    multiplier_map: dict[str, int] = {}
    grouped = frame.groupby(group_col, dropna=False, sort=False)
    for group_key, group_df in grouped:
        key = "" if pd.isna(group_key) else str(group_key)
        multiplier_map[key] = infer_value_multiplier_from_frame(
            group_df,
            value_col=value_col,
            shares_col=shares_col,
        )
    return multiplier_map


def apply_value_multiplier(values: pd.Series, multiplier: int) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric * multiplier


def apply_value_multiplier_by_group(
    frame: pd.DataFrame,
    *,
    group_col: str,
    value_col: str,
    multiplier_map: dict[str, int],
    default_multiplier: int = FALLBACK_VALUE_MULTIPLIER,
) -> pd.Series:
    if frame.empty or value_col not in frame.columns or group_col not in frame.columns:
        return pd.Series(dtype=float)

    def _lookup_multiplier(group_value) -> int:
        key = "" if pd.isna(group_value) else str(group_value)
        return int(multiplier_map.get(key, default_multiplier))

    multipliers = frame[group_col].apply(_lookup_multiplier)
    return apply_value_multiplier(frame[value_col], 1) * multipliers


def summarize_multipliers(multiplier_values: Iterable[int]) -> str:
    ordered = sorted({int(value) for value in multiplier_values if value})
    if not ordered:
        return "x1"
    return ", ".join(f"x{value}" for value in ordered)
