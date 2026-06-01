"""Pure instrument history transforms for dashboard views."""

from typing import Any

import pandas as pd

from src.core.diff import build_position_key
from src.web.value_units import apply_value_multiplier_by_group, infer_value_multiplier_by_group


def normalize_text_cell(value: Any) -> str:
    if value is None or value is pd.NA:
        return ""

    normalized = str(value).strip()
    return "" if normalized.lower() == "nan" else normalized


def instrument_type_label(put_call: str | None) -> str:
    normalized = normalize_text_cell(put_call).upper()
    return normalized or "Equity"


def instrument_display_type_label(put_call: str | None) -> str:
    normalized = normalize_text_cell(put_call).upper()
    if not normalized:
        return "Purchase"
    if normalized == "PUT":
        return "Put"
    if normalized == "CALL":
        return "Call"
    if "," in normalized:
        return "Mixed"
    return normalized.title()


def add_instrument_type_column(
    df: pd.DataFrame,
    *,
    put_call_column: str = "Put/Call",
    type_column: str = "Type",
) -> pd.DataFrame:
    display_df = df.copy()
    if put_call_column not in display_df.columns:
        return display_df

    type_values = display_df[put_call_column].apply(instrument_display_type_label)
    if type_column in display_df.columns:
        display_df[type_column] = type_values
        return display_df

    columns = display_df.columns.tolist()
    if "Ticker" in columns:
        insert_at = columns.index("Ticker") + 1
    elif "Issuer" in columns:
        insert_at = columns.index("Issuer") + 1
    else:
        insert_at = 0
    display_df.insert(insert_at, type_column, type_values)
    return display_df


def instrument_type_cell_styles(row: pd.Series, *, type_column: str = "Type") -> list[str]:
    styles = ["" for _column in row.index]
    if type_column not in row.index:
        return styles

    label = normalize_text_cell(row[type_column]).lower()
    color = {
        "purchase": "rgba(46, 160, 67, 0.28)",
        "sell": "rgba(248, 81, 73, 0.28)",
        "put": "rgba(248, 81, 73, 0.28)",
        "call": "rgba(31, 111, 235, 0.28)",
    }.get(label, "rgba(139, 148, 158, 0.22)")
    styles[list(row.index).index(type_column)] = f"background-color: {color}; font-weight: 700"
    return styles


def style_instrument_type_column(df: pd.DataFrame, *, type_column: str = "Type"):
    return df.style.apply(lambda row: instrument_type_cell_styles(row, type_column=type_column), axis=1)


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
    multiplier_map = infer_value_multiplier_by_group(
        instrument_df.rename(columns={"Accession": "accession_number", "Value ($000s)": "value_usd"}),
        group_col="accession_number",
        value_col="value_usd",
        shares_col="Shares",
    )
    instrument_df["Value (USD)"] = apply_value_multiplier_by_group(
        instrument_df.rename(columns={"Accession": "accession_number", "Value ($000s)": "value_usd"}),
        group_col="accession_number",
        value_col="value_usd",
        multiplier_map=multiplier_map,
    )
    instrument_df["Value Multiplier"] = instrument_df["Accession"].map(
        lambda accession: multiplier_map.get(str(accession), 1)
    )
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

    value_sort_col = "Value (USD)" if "Value (USD)" in instrument_history_df.columns else "Value ($000s)"
    latest_filing_dt = instrument_history_df["Filing Date Dt"].max()
    option_summary_df = (
        instrument_history_df
        .sort_values(
            ["Filing Date Dt", value_sort_col, "Shares", "Instrument Label"],
            ascending=[False, False, False, True],
            na_position="last",
        )
        .groupby("Position Key", as_index=False)
        .first()
    )
    option_summary_df["Present In Latest Filing"] = option_summary_df["Filing Date Dt"].eq(latest_filing_dt)
    return option_summary_df.sort_values(
        ["Present In Latest Filing", value_sort_col, "Shares", "Instrument Label"],
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
    selected_columns = [
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
        "Value (USD)",
        "Value Multiplier",
    ]
    selected_rows = selected_rows[[column for column in selected_columns if column in selected_rows.columns]]

    if "Value (USD)" not in selected_rows.columns and "Value ($000s)" in selected_rows.columns:
        selected_rows["Value (USD)"] = selected_rows["Value ($000s)"]

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