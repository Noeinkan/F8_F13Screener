"""Tests for dashboard ticker enrichment."""

import pandas as pd

from src.web.tickers import add_ticker_column, build_ticker_lookup


def test_add_ticker_column_matches_sec_company_names_and_aliases():
    lookup = build_ticker_lookup([
        {"name": "NVIDIA Corp", "ticker": "NVDA"},
        {"name": "Taiwan Semiconductor Manufacturing Co Ltd", "ticker": "TSM"},
    ])
    df = pd.DataFrame({
        "Issuer": ["NVIDIA CORPORATION", "TAIWAN SEMICONDUCTOR MANUFAC", "Unknown Issuer"],
        "CUSIP": ["67066G104", "874039100", "000000000"],
    })

    enriched = add_ticker_column(df, lookup=lookup)

    assert enriched.columns.tolist() == ["Ticker", "Issuer", "CUSIP"]
    assert enriched["Ticker"].tolist() == ["NVDA", "TSM", ""]


def test_ticker_lookup_leaves_ambiguous_company_names_blank():
    lookup = build_ticker_lookup([
        {"name": "Alphabet Inc", "ticker": "GOOG"},
        {"name": "Alphabet Inc", "ticker": "GOOGL"},
    ])
    df = pd.DataFrame({"Issuer": ["ALPHABET INC"]})

    enriched = add_ticker_column(df, lookup=lookup)

    assert enriched["Ticker"].tolist() == [""]


def test_ticker_lookup_prefers_primary_listed_ticker_over_preferred_or_otc_rows():
    lookup = build_ticker_lookup([
        {"name": "ORACLE CORP", "ticker": "ORCL", "exchange": "NYSE"},
        {"name": "ORACLE CORP", "ticker": "ORCL-PD", "exchange": "NYSE"},
        {"name": "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD", "ticker": "TSM", "exchange": "NYSE"},
        {"name": "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD", "ticker": "TSMWF", "exchange": "OTC"},
    ])
    df = pd.DataFrame({"Issuer": ["ORACLE CORP", "TAIWAN SEMICONDUCTOR MANUFAC"]})

    enriched = add_ticker_column(df, lookup=lookup)

    assert enriched["Ticker"].tolist() == ["ORCL", "TSM"]