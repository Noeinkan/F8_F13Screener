"""Serialize pandas objects for JSON responses."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.floating, float)):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return value


def records_from_dataframe(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    normalized = df.where(pd.notna(df), None)
    rows: list[dict[str, Any]] = []
    for record in normalized.to_dict(orient="records"):
        rows.append({key: _json_value(value) for key, value in record.items()})
    return rows


def dataframe_to_csv_text(df: pd.DataFrame) -> str:
    return df.to_csv(index=False)
