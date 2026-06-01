"""Tests for dashboard instrument-history transforms."""

import pandas as pd

from src.web.instrument_transforms import (
    add_instrument_type_column,
    build_fund_instrument_history,
    build_instrument_label,
    build_instrument_option_summary,
    build_instrument_timeseries,
    instrument_display_type_label,
    instrument_type_cell_styles,
    instrument_type_label,
)


def test_build_instrument_label_separates_equity_and_options():
    assert instrument_type_label(None) == "Equity"
    assert build_instrument_label(" Apple Inc ", " COM ", None, " 037833100 ") == (
        "Apple Inc | COM | Equity | 037833100"
    )
    assert build_instrument_label("Apple Inc", "COM", "CALL", "037833100") == (
        "Apple Inc | COM | CALL | 037833100"
    )


def test_instrument_display_type_labels_purchase_put_and_call():
    assert instrument_display_type_label(None) == "Purchase"
    assert instrument_display_type_label("") == "Purchase"
    assert instrument_display_type_label(" put ") == "Put"
    assert instrument_display_type_label("CALL") == "Call"
    assert instrument_display_type_label("PUT,CALL") == "Mixed"


def test_add_instrument_type_column_inserts_after_ticker_and_is_idempotent():
    rows = pd.DataFrame({
        "Ticker": ["AAPL", "TSLA", "NVDA"],
        "Issuer": ["Apple Inc", "Tesla Inc", "Nvidia Corporation"],
        "Put/Call": [None, "CALL", "PUT"],
    })

    result = add_instrument_type_column(rows)
    assert result.columns.tolist() == ["Ticker", "Type", "Issuer", "Put/Call"]
    assert result["Type"].tolist() == ["Purchase", "Call", "Put"]

    result = add_instrument_type_column(result.assign(**{"Put/Call": ["PUT", None, "CALL"]}))
    assert result.columns.tolist() == ["Ticker", "Type", "Issuer", "Put/Call"]
    assert result["Type"].tolist() == ["Put", "Purchase", "Call"]


def test_instrument_type_cell_styles_only_type_column():
    row = pd.Series({"Ticker": "NVDA", "Type": "Put", "Issuer": "Nvidia Corporation"})

    styles = instrument_type_cell_styles(row)

    assert styles[0] == ""
    assert "rgba(248, 81, 73" in styles[1]
    assert "font-weight: 700" in styles[1]
    assert styles[2] == ""

    sell_styles = instrument_type_cell_styles(pd.Series({"Ticker": "HLT", "Type": "Sell"}))
    assert "rgba(248, 81, 73" in sell_styles[1]


def test_build_fund_instrument_history_adds_dashboard_columns():
    rows = pd.DataFrame([
        {
            "accession_number": "0001",
            "filing_date": "2024-02-14",
            "cusip": "037833100",
            "issuer_name": "Apple Inc",
            "share_class": "COM",
            "put_call": None,
            "shares": 100,
            "value_usd": 10,
            "raw_lines": 1,
        }
    ])

    result = build_fund_instrument_history(rows)

    assert result.loc[0, "Position Key"] == "037833100|COM|"
    assert result.loc[0, "Instrument Type"] == "Equity"
    assert result.loc[0, "Instrument Label"] == "Apple Inc | COM | Equity | 037833100"
    assert result.loc[0, "Label"] == "2024-02-14 (0001)"


def test_build_instrument_option_summary_prefers_latest_filing():
    instrument_history_df = pd.DataFrame([
        {
            "Position Key": "AAA|COM|",
            "Filing Date Dt": pd.Timestamp("2024-02-14"),
            "Value ($000s)": 10,
            "Shares": 100,
            "Instrument Label": "A | COM | Equity | AAA",
        },
        {
            "Position Key": "AAA|COM|",
            "Filing Date Dt": pd.Timestamp("2024-05-14"),
            "Value ($000s)": 12,
            "Shares": 120,
            "Instrument Label": "A | COM | Equity | AAA",
        },
    ])

    result = build_instrument_option_summary(instrument_history_df)

    assert len(result) == 1
    assert result.loc[0, "Shares"] == 120
    assert bool(result.loc[0, "Present In Latest Filing"])


def test_build_instrument_timeseries_includes_missing_quarters():
    history_df = pd.DataFrame([
        {
            "Filing Date": "2024-02-14",
            "Filing Date Dt": pd.Timestamp("2024-02-14"),
            "Accession": "0001",
            "Label": "2024-02-14 (0001)",
        },
        {
            "Filing Date": "2024-05-14",
            "Filing Date Dt": pd.Timestamp("2024-05-14"),
            "Accession": "0002",
            "Label": "2024-05-14 (0002)",
        },
    ])
    instrument_history_df = pd.DataFrame([
        {
            "Position Key": "AAA|COM|",
            "Filing Date": "2024-02-14",
            "Filing Date Dt": pd.Timestamp("2024-02-14"),
            "Accession": "0001",
            "Issuer": "Apple Inc",
            "CUSIP": "AAA",
            "Class": "COM",
            "Put/Call": None,
            "Instrument Type": "Equity",
            "Instrument Label": "Apple Inc | COM | Equity | AAA",
            "Shares": 100,
            "Value ($000s)": 10,
        }
    ])

    result = build_instrument_timeseries(history_df, instrument_history_df, "AAA|COM|")

    assert result["Position Status"].tolist() == ["Present", "Missing"]
    assert result["Shares Filled"].tolist() == [100, 0]
    assert result.loc[1, "Δ Shares"] == -100