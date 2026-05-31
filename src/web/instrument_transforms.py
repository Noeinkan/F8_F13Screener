"""Pure instrument history transforms for dashboard views."""

from typing import Any

import pandas as pd

from src.core.diff import build_position_key


def normalize_text_cell(value: Any) -> str:
    if value is None or value is pd.NA:
        return ""

    normalized = str(value).strip()
    return "" if normalized.lower() == "nan" else normalized


def instrument_type_label(put_call: str | None) -> str:
    normalized = normalize_text_cell(put_call).upper()
    return normalized or "Equity"


def instrument_share_class_label(share_class: str | None) -> str:
    normalized = normalize_text_cell(share_class)
    return normalized or "-"


def build_instrument_label(
    issuer_name: str | None,
    share_class: str | None,
    put_call: str | None,
    cusip: str | None,
) -> str:
    parts = [
        normalize_text_cell(issuer_name) or "Unknown issuer",
        instrument_share_class_label(share_class),
        instrument_type_label(put_call),
    ]
    normalized_cusip = normalize_text_cell(cusip)
    if normalized_cusip:
        parts.append(normalized_cusip)
    return " | ".join(parts)


def build_fund_instrument_history(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()

    instrument_df = rows.rename(columns={
        "accession_number": "Accession",
        "filing_date": "Filing Date",
        "cusip": "CUSIP",
        "issuer_name": "Issuer",
        "share_class": "Class",
        "put_call": "Put/Call",
        "shares": "Shares",
        "value_usd": "Value ($000s)",
        "raw_lines": "Raw 13F Lines",
    }).copy()
    instrument_df["Filing Date Dt"] = pd.to_datetime(instrument_df["Filing Date"])
    instrument_df["Position Key"] = instrument_df.apply(
        lambda row: build_position_key(
            row.get("CUSIP"),
            row.get("Issuer"),
            row.get("Class"),
            row.get("Put/Call"),
        ),
        axis=1,
    )
    instrument_df["Instrument Type"] = instrument_df["Put/Call"].apply(instrument_type_label)
    instrument_df["Instrument Label"] = instrument_df.apply(
        lambda row: build_instrument_label(
            row.get("Issuer"),
            row.get("Class"),
            row.get("Put/Call"),
            row.get("CUSIP"),
        ),
        axis=1,
    )
    instrument_df["Label"] = instrument_df.apply(
        lambda row: f"{row['Filing Date']} ({row['Accession']})",
        axis=1,
    )
    return instrument_df.sort_values(["Filing Date Dt", "Instrument Label"]).reset_index(drop=True)


def build_instrument_option_summary(instrument_history_df: pd.DataFrame) -> pd.DataFrame:
    if instrument_history_df.empty:
        return pd.DataFrame()

    latest_filing_dt = instrument_history_df["Filing Date Dt"].max()
    option_summary_df = (
        instrument_history_df
        .sort_values(
            ["Filing Date Dt", "Value ($000s)", "Shares", "Instrument Label"],
            ascending=[False, False, False, True],
            na_position="last",
        )
        .groupby("Position Key", as_index=False)
        .first()
    )
    option_summary_df["Present In Latest Filing"] = option_summary_df["Filing Date Dt"].eq(latest_filing_dt)
    return option_summary_df.sort_values(
        ["Present In Latest Filing", "Value ($000s)", "Shares", "Instrument Label"],
        ascending=[False, False, False, True],
        na_position="last",
    ).reset_index(drop=True)


def build_instrument_timeseries(
    history_df: pd.DataFrame,
    instrument_history_df: pd.DataFrame,
    position_key: str,
) -> pd.DataFrame:
    selected_rows = instrument_history_df.loc[
        instrument_history_df["Position Key"] == position_key
    ].copy()
    if selected_rows.empty:
        return pd.DataFrame()

    base_df = history_df[["Filing Date", "Filing Date Dt", "Accession", "Label"]].copy()
    selected_metadata = selected_rows.sort_values("Filing Date Dt").iloc[-1]
    selected_rows = selected_rows[
        [
            "Filing Date",
            "Accession",
            "Issuer",
            "CUSIP",
            "Class",
            "Put/Call",
            "Instrument Type",
            "Instrument Label",
            "Shares",
            "Value ($000s)",
        ]
    ]

    timeseries_df = base_df.merge(
        selected_rows,
        on=["Filing Date", "Accession"],
        how="left",
    )
    for column in ["Issuer", "CUSIP", "Class", "Put/Call", "Instrument Type", "Instrument Label"]:
        timeseries_df[column] = timeseries_df[column].fillna(selected_metadata[column])

    timeseries_df["Present"] = timeseries_df["Shares"].notna()
    timeseries_df["Position Status"] = timeseries_df["Present"].map({True: "Present", False: "Missing"})
    timeseries_df["Shares Filled"] = timeseries_df["Shares"].fillna(0)
    timeseries_df["Previous Shares"] = timeseries_df["Shares Filled"].shift(1)
    timeseries_df["Previous Filing"] = timeseries_df["Filing Date"].shift(1)
    timeseries_df["Δ Shares"] = timeseries_df["Shares Filled"].diff()
    timeseries_df["Δ %"] = timeseries_df.apply(
        lambda row: (
            None
            if pd.isna(row["Previous Shares"]) or row["Previous Shares"] == 0
            else (row["Δ Shares"] / row["Previous Shares"]) * 100
        ),
        axis=1,
    )
    return timeseries_df