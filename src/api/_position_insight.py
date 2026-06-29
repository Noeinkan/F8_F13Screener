"""Pure (Streamlit-free) helpers for the Snapshot "position insight" panel.

Ported from the inline logic in ``src/web/pages/fund_analysis.py``
(``_add_position_insight_columns`` and ``_render_position_insight``) so the
React UI can render the same panel without depending on Streamlit.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.web.formatting import fmt_eu_date, fmt_quantity, fmt_value_dollars


def _fmt_price(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"${float(value):,.2f}"


def _option_kind(value: Any) -> str:
    return str(value or "").strip().upper()


def _infer_assumed_transaction_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""

    year = int(parsed.year)
    month = int(parsed.month)
    day = int(parsed.day)
    quarter_end_days = {3: 31, 6: 30, 9: 30, 12: 31}
    if month in quarter_end_days and day == quarter_end_days[month]:
        return parsed.strftime("%Y-%m-%d")
    if month <= 3:
        return f"{year - 1}-12-31"
    if month <= 6:
        return f"{year}-03-31"
    if month <= 9:
        return f"{year}-06-30"
    return f"{year}-09-30"


def _insight_key(row: pd.Series) -> str:
    cusip = str(row.get("CUSIP") or "").strip()
    if cusip:
        return cusip
    return "|".join(
        str(row.get(part) or "").strip() for part in ["Issuer", "Class", "Put/Call"]
    )


def add_position_insight_columns(display_df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived columns consumed by the position insight panel."""
    if display_df.empty:
        return display_df

    df = display_df.copy()
    shares = pd.to_numeric(df["Shares"], errors="coerce")
    values = pd.to_numeric(df["Value (USD)"], errors="coerce")
    option_kinds = df["Put/Call"].apply(_option_kind)
    is_option = option_kinds.isin(["PUT", "CALL"])

    df["Assumed Transaction Date"] = df["Filing Date"].apply(_infer_assumed_transaction_date)
    df["Implied Filing Price"] = values.div(shares.where(shares != 0))
    df["Estimated Contracts"] = (shares / 100).where(is_option)
    df["_Insight Key"] = df.apply(_insight_key, axis=1)
    return df


def _option_summary(selected_df: pd.DataFrame) -> dict[str, Any]:
    option_mask = selected_df["Put/Call"].apply(_option_kind).isin(["PUT", "CALL"])
    if not option_mask.any():
        return {"has_options": False, "parts": [], "common_summary": ""}

    option_df = selected_df[option_mask].copy()
    option_values = pd.to_numeric(option_df["Value (USD)"], errors="coerce").fillna(0)
    option_shares = pd.to_numeric(option_df["Shares"], errors="coerce").fillna(0)
    option_contracts = pd.to_numeric(option_df["Estimated Contracts"], errors="coerce").fillna(0)

    aggregated = option_df.assign(_value=option_values, _contracts=option_contracts).groupby(
        option_df["Put/Call"].apply(_option_kind)
    ).agg(notional=("_value", "sum"), contracts=("_contracts", "sum"))

    parts = [
        f"{kind}: {fmt_value_dollars(row['notional'])} notional, {fmt_quantity(row['contracts'])} contracts"
        for kind, row in aggregated.iterrows()
    ]

    common_summary = ""
    common_mask = ~option_mask
    if common_mask.any():
        common_values = pd.to_numeric(selected_df["Value (USD)"], errors="coerce").fillna(0)
        common_shares = pd.to_numeric(selected_df["Shares"], errors="coerce").fillna(0)
        common_value = common_values[common_mask].sum()
        common_shares_total = common_shares[common_mask].sum()
        option_value = option_values.sum()
        ratio = option_value / common_value if common_value else None
        ratio_text = f"; option/common reported value ratio: {ratio:,.1f}x" if ratio else ""
        common_summary = (
            f"Same-CUSIP common share stub: {fmt_quantity(common_shares_total)} shares, "
            f"{fmt_value_dollars(common_value)} reported value{ratio_text}."
        )

    return {"has_options": True, "parts": parts, "common_summary": common_summary}


def build_position_insight_options(display_df: pd.DataFrame) -> dict[str, Any]:
    """Return the options list (label + key) for the Snapshot position insight selector."""
    if display_df.empty:
        return {"options": [], "labels": {}}

    df = display_df.copy()
    df["_Insight Key"] = df.apply(_insight_key, axis=1)
    candidates = df[df["_Insight Key"].astype(str).str.strip() != ""].copy()
    if candidates.empty:
        return {"options": [], "labels": {}}

    candidate_order = (
        candidates.groupby("_Insight Key", dropna=False)["Value (USD)"]
        .sum()
        .sort_values(ascending=False)
        .index
        .tolist()
    )

    labels: dict[str, str] = {}
    for key in candidate_order:
        group = candidates[candidates["_Insight Key"] == key]
        top_row = group.sort_values("Value (USD)", ascending=False).iloc[0]
        ticker = str(top_row.get("Ticker") or "").strip()
        issuer = str(top_row.get("Issuer") or "").strip()
        cusip = str(top_row.get("CUSIP") or "").strip()
        label_parts = [part for part in (ticker, issuer, cusip) if part]
        labels[key] = " | ".join(label_parts) or str(key)

    return {"options": candidate_order, "labels": labels}


def build_position_insight_detail(display_df: pd.DataFrame, insight_key: str) -> dict[str, Any]:
    """Return the metrics + detail rows for a single selected insight key."""
    if display_df.empty or not insight_key:
        return {
            "metrics": {
                "transaction_date": "-",
                "implied_filing_price": "-",
                "reported_value": "-",
                "underlying_shares": "-",
            },
            "rows": [],
            "option_caption": "",
            "common_caption": "",
            "captions": [
                "Assumed transaction date is inferred as the 13F report-period quarter end from the SEC filing date; "
                "13F filings do not provide per-position trade dates.",
            ],
        }

    df = display_df.copy()
    df["_Insight Key"] = df.apply(_insight_key, axis=1)
    selected = df[df["_Insight Key"] == insight_key].copy()
    if selected.empty:
        return {
            "metrics": {
                "transaction_date": "-",
                "implied_filing_price": "-",
                "reported_value": "-",
                "underlying_shares": "-",
            },
            "rows": [],
            "option_caption": "",
            "common_caption": "",
            "captions": [
                "Assumed transaction date is inferred as the 13F report-period quarter end from the SEC filing date; "
                "13F filings do not provide per-position trade dates.",
            ],
        }

    shares = pd.to_numeric(selected["Shares"], errors="coerce")
    values = pd.to_numeric(selected["Value (USD)"], errors="coerce")
    implied_prices = pd.to_numeric(selected["Implied Filing Price"], errors="coerce").dropna()

    transaction_dates = sorted(
        {
            fmt_eu_date(value)
            for value in selected.get("Assumed Transaction Date", pd.Series(dtype=object)).dropna()
            if value
        }
    )

    option_summary = _option_summary(selected)
    captions = [
        "Assumed transaction date is inferred as the 13F report-period quarter end from the SEC filing date; "
        "13F filings do not provide per-position trade dates.",
    ]
    if option_summary["has_options"]:
        captions.append(
            "Option rows: " + "; ".join(option_summary["parts"])
        )
        captions.append(
            "13F option rows are treated as underlying notional exposure. The reported value is not the option premium paid."
        )
        if option_summary["common_summary"]:
            captions.append(option_summary["common_summary"])

    detail_columns = [
        "Ticker",
        "Type",
        "Assumed Transaction Date",
        "Filing Date",
        "Issuer",
        "CUSIP",
        "Class",
        "Shares",
        "Put/Call",
        "Value",
        "Implied Filing Price",
        "Estimated Contracts",
    ]

    detail_df = selected[[col for col in detail_columns if col in selected.columns]].copy()

    return {
        "metrics": {
            "transaction_date": ", ".join(transaction_dates) if transaction_dates else "-",
            "implied_filing_price": _fmt_price(implied_prices.median() if not implied_prices.empty else None),
            "reported_value": fmt_value_dollars(values.fillna(0).sum()),
            "underlying_shares": fmt_quantity(shares.fillna(0).sum()),
        },
        "rows": detail_df.replace({pd.NA: None}).where(pd.notna(detail_df), None).to_dict(orient="records"),
        "option_caption": (
            "13F option rows are treated as underlying notional exposure. "
            "The reported value is not the option premium paid."
            if option_summary["has_options"]
            else ""
        ),
        "common_caption": option_summary["common_summary"],
        "captions": captions,
    }
