"""Tests for dashboard presentation formatting helpers."""

import pandas as pd

from src.web.formatting import (
    dataframe_to_csv_bytes,
    fmt_accession_label,
    fmt_eu_date,
    fmt_quantity,
    fmt_signed_pct,
    fmt_signed_quantity,
    fmt_signed_value,
    fmt_transition_label,
    fmt_value,
)


def test_dataframe_to_csv_bytes_handles_dataframe_and_series():
    frame = pd.DataFrame({"name": ["Apple"], "shares": [10]})
    assert dataframe_to_csv_bytes(frame).replace(b"\r\n", b"\n") == b"name,shares\nApple,10\n"

    series = pd.Series([10], name="shares")
    assert dataframe_to_csv_bytes(series).replace(b"\r\n", b"\n") == b"shares\n10\n"


def test_fmt_value_formats_thousands_of_usd():
    assert fmt_value(None) == "-"
    assert fmt_value(0) == "-"
    assert fmt_value(1) == "$1k"
    assert fmt_value(1_500) == "$1.5M"
    assert fmt_value(2_500_000) == "$2.50B"


def test_fmt_eu_date_formats_iso_dates_and_preserves_invalid_values():
    assert fmt_eu_date("2026-05-15") == "15/05/2026"
    assert fmt_eu_date("not-a-date") == "not-a-date"


def test_accession_and_transition_labels_are_readable():
    assert (
        fmt_accession_label("2026-05-15", "0001193125-26-226661")
        == "15/05/2026 | Accession: 0001193125-26-226661"
    )
    assert (
        fmt_transition_label(
            "2026-02-17",
            "2026-05-15",
            "0001193125-26-054580",
            "0001193125-26-226661",
        )
        == "17/02/2026 -> 15/05/2026 | 0001193125-26-054580 -> 0001193125-26-226661"
    )


def test_fmt_quantity_handles_null_integer_and_float_values():
    assert fmt_quantity(pd.NA) == "-"
    assert fmt_quantity(1200) == "1,200"
    assert fmt_quantity(1200.5) == "1,200.50"


def test_fmt_signed_quantity_includes_positive_sign():
    assert fmt_signed_quantity(pd.NA) == "-"
    assert fmt_signed_quantity(1200) == "+1,200"
    assert fmt_signed_quantity(-1200.5) == "-1,200.50"
    assert fmt_signed_quantity(0) == "0"


def test_fmt_signed_percent_handles_nulls():
    assert fmt_signed_pct(None) == "-"
    assert fmt_signed_pct(12.34) == "+12.3%"
    assert fmt_signed_pct(-12.34) == "-12.3%"


def test_fmt_signed_value_formats_thousands_of_usd():
    assert fmt_signed_value(None) == "-"
    assert fmt_signed_value(0) == "$0"
    assert fmt_signed_value(1500) == "+$1.5M"
    assert fmt_signed_value(-1500) == "-$1.5M"