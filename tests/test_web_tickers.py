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


def test_ticker_lookup_resolves_ambiguous_names_by_cusip_override():
    lookup = build_ticker_lookup([
        {"name": "Alphabet Inc", "ticker": "GOOG"},
        {"name": "Alphabet Inc", "ticker": "GOOGL"},
    ])
    df = pd.DataFrame({
        "Issuer": ["ALPHABET INC", "ALPHABET INC"],
        "CUSIP": ["02079K305", "02079K107"],
    })

    enriched = add_ticker_column(df, lookup=lookup)

    assert enriched["Ticker"].tolist() == ["GOOG", "GOOGL"]


def test_ticker_lookup_drops_noise_word_of_in_alias_keys():
    lookup = build_ticker_lookup([
        {"name": "BANK OF AMERICA CORP", "ticker": "BAC", "exchange": "NYSE"},
    ])
    df = pd.DataFrame({"Issuer": ["BANK AMERICA CORP"]})

    enriched = add_ticker_column(df, lookup=lookup)

    assert enriched["Ticker"].tolist() == ["BAC"]


def test_ticker_lookup_aliases_intl_to_international():
    lookup = build_ticker_lookup([
        {"name": "PHILIP MORRIS INTERNATIONAL INC", "ticker": "PM", "exchange": "NYSE"},
    ])
    df = pd.DataFrame({"Issuer": ["PHILIP MORRIS INTL INC"]})

    enriched = add_ticker_column(df, lookup=lookup)

    assert enriched["Ticker"].tolist() == ["PM"]


def test_ticker_lookup_matches_word_order_insensitive_alias():
    lookup = build_ticker_lookup([
        {"name": "WALT DISNEY CO", "ticker": "DIS", "exchange": "NYSE"},
    ])
    df = pd.DataFrame({"Issuer": ["DISNEY WALT CO"]})

    enriched = add_ticker_column(df, lookup=lookup)

    assert enriched["Ticker"].tolist() == ["DIS"]


def test_ticker_lookup_strips_sec_jurisdiction_suffix():
    lookup = build_ticker_lookup([
        {"name": "BANK OF AMERICA CORP /DE/", "ticker": "BAC", "exchange": "NYSE"},
    ])
    df = pd.DataFrame({"Issuer": ["BANK AMERICA CORP"]})

    enriched = add_ticker_column(df, lookup=lookup)

    assert enriched["Ticker"].tolist() == ["BAC"]


def test_ticker_lookup_resolves_berkshire_dual_class_by_cusip():
    lookup = build_ticker_lookup([
        {"name": "BERKSHIRE HATHAWAY INC", "ticker": "BRK-A", "exchange": "NYSE"},
        {"name": "BERKSHIRE HATHAWAY INC", "ticker": "BRK-B", "exchange": "NYSE"},
    ])
    df = pd.DataFrame({
        "Issuer": ["BERKSHIRE HATHAWAY INC CL B", "BERKSHIRE HATHAWAY INC"],
        "CUSIP": ["084670702", "084670108"],
    })

    enriched = add_ticker_column(df, lookup=lookup)

    assert enriched["Ticker"].tolist() == ["BRK-B", "BRK-A"]


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


def test_ticker_lookup_resolves_etfs_missing_from_sec_reference_by_cusip():
    # IVV (iShares Core S&P 500 ETF) is absent from the SEC
    # company_tickers_exchange.json reference entirely, so the empty lookup
    # simulates that scenario and the CUSIP override must still resolve it.
    lookup = build_ticker_lookup([])
    df = pd.DataFrame({
        "Issuer": ["ISHARES TR", "STATE STR SPDR S&P 500 ETF T"],
        "CUSIP": ["464287200", "78462F103"],
    })

    enriched = add_ticker_column(df, lookup=lookup)

    assert enriched["Ticker"].tolist() == ["IVV", "SPY"]