"""Formatting helpers for Streamlit dashboard presentation."""

import pandas as pd


def dataframe_to_csv_bytes(df: pd.DataFrame | pd.Series) -> bytes:
    frame = df.to_frame() if isinstance(df, pd.Series) else df
    return frame.to_csv(index=False).encode("utf-8")


def fmt_value(val_thousands):
    """Format thousands-of-USD into readable string."""
    if pd.isna(val_thousands) or val_thousands == 0:
        return "-"
    v = float(val_thousands) * 1000
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}k"
    return f"${v:,.0f}"


def fmt_quantity(value):
    """Format share quantities while tolerating nulls and floats."""
    if pd.isna(value):
        return "-"
    numeric = float(value)
    if numeric.is_integer():
        return f"{int(numeric):,}"
    return f"{numeric:,.2f}"


def fmt_signed_quantity(value):
    if pd.isna(value):
        return "-"
    numeric = float(value)
    sign = "+" if numeric > 0 else ""
    if numeric.is_integer():
        return f"{sign}{int(numeric):,}"
    return f"{sign}{numeric:,.2f}"


def fmt_signed_pct(value):
    if value is None or pd.isna(value):
        return "-"
    return f"{value:+.1f}%"


def fmt_signed_value(value_thousands):
    if value_thousands is None or pd.isna(value_thousands):
        return "-"
    if value_thousands == 0:
        return "$0"
    sign = "+" if value_thousands > 0 else "-"
    absolute_value = fmt_value(abs(value_thousands))
    if absolute_value == "-":
        absolute_value = "$0"
    return f"{sign}{absolute_value}"