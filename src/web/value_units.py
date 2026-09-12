"""Value-unit helpers for dashboard views -- now pass-throughs.

13F values were reported in thousands of dollars until January 2023 and in
dollars afterwards, and some filers kept sending thousands. These helpers used
to guess the unit at read time from the median implied price (value / shares)
of whatever frame a view had at hand. That guess was wrong in ways a view could
not fix: bonds (priced near $1 per unit of principal) and options made a
bond-heavy fund's dollars look like thousands (Oaktree's $6.28B showed as
$6.28T), and a diff mixed rows from both sides of a unit change into one guess.

The unit is now decided once per filing at the storage layer
(``filings.value_multiplier``, see ``src/core/filing_rollup.py``), and every
analytics query reads ``holdings_effective``, whose ``value_usd`` is already in
dollars. Guessing again here would re-scale correct dollars for funds whose
typical holding trades below a few dollars, so the inference functions return
1. Their signatures stay so the many callers keep working unchanged.
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

CANDIDATE_VALUE_MULTIPLIERS = (1,)
FALLBACK_VALUE_MULTIPLIER = 1


def infer_value_multiplier_from_prices(prices_dollars: pd.Series) -> int:
    """Values reaching views are already dollars; always 1."""
    return 1


def infer_value_multiplier_from_frame(
    frame: pd.DataFrame,
    *,
    value_col: str,
    shares_col: str,
) -> int:
    """Values reaching views are already dollars; always 1."""
    return 1


def infer_value_multiplier_by_group(
    frame: pd.DataFrame,
    *,
    group_col: str,
    value_col: str,
    shares_col: str,
) -> dict[str, int]:
    """One entry of 1 per group, so callers that summarize groups still can."""
    if frame.empty or group_col not in frame.columns:
        return {}
    keys = frame[group_col].drop_duplicates()
    return {("" if pd.isna(key) else str(key)): 1 for key in keys}


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
