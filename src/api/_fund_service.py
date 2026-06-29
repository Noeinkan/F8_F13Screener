"""Fund analysis API helpers."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.api._diff_format import (
    build_compare_highlights,
    build_formatted_diff_sections,
    build_top_movers,
)
from src.api._position_insight import (
    add_position_insight_columns,
    build_position_insight_detail,
    build_position_insight_options,
)
from src.api.repository import (
    fund_has_db_holdings,
    load_accessions_for_fund,
    load_fund_history,
    load_normalized_positions_map,
    query,
)
from src.api.serialize import records_from_dataframe
from src.core.diff import compute_detailed_portfolio_diff
from src.web.charts import (
    build_shares_change_lane_data,
    build_shares_flow_sankey_data,
    build_transition_summary_df,
    scale_shares_flow_values,
    SHARES_FLOW_SCALE_MODES,
)
from src.web.formatting import fmt_accession_label, fmt_value_dollars
from src.web.instrument_transforms import add_instrument_type_column
from src.web.sql_queries import NORMALIZED_ACCESSION_HOLDINGS_SQL, RAW_ACCESSION_HOLDINGS_SQL
from src.web.tickers import add_ticker_column
from src.web.value_units import apply_value_multiplier, infer_value_multiplier_from_frame


def _accession_labels(accessions: pd.DataFrame) -> list[dict[str, str]]:
    return [
        {
            "accession_number": row["accession_number"],
            "filing_date": row["filing_date"],
            "label": fmt_accession_label(row["filing_date"], row["accession_number"]),
        }
        for _, row in accessions.iterrows()
    ]


def build_fund_header(fund: str) -> dict[str, object]:
    accessions = load_accessions_for_fund(fund)
    history_df, _ = load_fund_history(fund)
    latest_filing = None
    quarters = 0
    current_positions = 0
    if not history_df.empty:
        latest = history_df.iloc[-1]
        latest_filing = latest["Filing Date"]
        quarters = len(history_df)
        current_positions = int(latest["Normalized Positions"])
    return {
        "fund": fund,
        "has_db_holdings": fund_has_db_holdings(fund),
        "accessions": _accession_labels(accessions),
        "latest_filing": latest_filing,
        "quarters": quarters,
        "current_positions": current_positions,
    }


def build_fund_snapshot(
    fund: str,
    accession: str,
    *,
    view: str = "normalized",
    top_n: int = 10,
    filter_text: str = "",
) -> dict[str, object]:
    raw_df = query(RAW_ACCESSION_HOLDINGS_SQL, (fund, accession))
    normalized_df = query(NORMALIZED_ACCESSION_HOLDINGS_SQL, (fund, accession))
    if raw_df.empty:
        return {
            "empty": True,
            "rows": [],
            "chart": None,
            "metrics": {},
            "position_insight": {"options": [], "labels": {}, "detail": {"metrics": {}, "rows": [], "captions": []}},
            "value_multiplier": 1,
            "filing_date": None,
        }

    display_df = normalized_df.copy() if view == "normalized" else raw_df.copy()
    display_df = add_ticker_column(display_df)
    value_multiplier = infer_value_multiplier_from_frame(display_df, value_col="Value ($000s)", shares_col="Shares")
    display_df["Value (USD)"] = apply_value_multiplier(display_df["Value ($000s)"], value_multiplier)
    filing_date = display_df["Filing Date"].iloc[0] if "Filing Date" in display_df.columns else None

    if filter_text:
        mask = (
            display_df["Ticker"].astype(str).str.contains(filter_text, case=False, na=False)
            | display_df["Issuer"].astype(str).str.contains(filter_text, case=False, na=False)
            | display_df["CUSIP"].astype(str).str.contains(filter_text, case=False, na=False)
        )
        display_df = display_df.loc[mask].copy()

    top_holdings = display_df.head(top_n)
    chart = {
        "title": f"Top {top_n} by value - {fund}",
        "x": top_holdings["Issuer"].tolist(),
        "y": top_holdings["Value (USD)"].fillna(0).tolist(),
    }

    export_df = display_df.copy()
    export_df["Value"] = export_df["Value (USD)"].apply(fmt_value_dollars)
    export_df = add_instrument_type_column(export_df)
    columns = [col for col in ["Ticker", "Type", "Issuer", "CUSIP", "Class", "Shares", "Put/Call", "Value"] if col in export_df.columns]

    insight_df = add_position_insight_columns(display_df)
    insight_options = build_position_insight_options(insight_df)
    first_key = insight_options["options"][0] if insight_options["options"] else ""
    insight_detail = build_position_insight_detail(insight_df, first_key)

    return {
        "empty": False,
        "value_multiplier": value_multiplier,
        "filing_date": filing_date,
        "metrics": {
            "raw_lines": len(raw_df),
            "normalized_positions": len(normalized_df),
            "compression": 1 - (len(normalized_df) / len(raw_df)) if len(raw_df) else 0,
        },
        "chart": chart,
        "rows": records_from_dataframe(export_df[columns]),
        "position_insight": {
            "options": insight_options["options"],
            "labels": insight_options["labels"],
            "selected_key": first_key,
            "detail": insight_detail,
        },
    }


def build_fund_snapshot_export(
    fund: str,
    accession: str,
    *,
    view: str = "normalized",
    top_n: int = 10,
    filter_text: str = "",
) -> dict[str, Any]:
    """Return the dataframe + a safe filename for the snapshot CSV export."""
    payload = build_fund_snapshot(
        fund, accession, view=view, top_n=top_n, filter_text=filter_text
    )
    if payload.get("empty"):
        return {"columns": [], "rows": [], "filename": f"f8_13f_{fund}_{accession}_{view}.csv"}

    columns = payload["rows"][0].keys() if payload["rows"] else []
    view_token = "normalized" if view == "normalized" else "raw"
    safe_fund = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in fund) or "fund"
    filename = f"f8_13f_{safe_fund}_{accession}_{view_token}.csv"
    return {"columns": list(columns), "rows": payload["rows"], "filename": filename}


def _build_history_summary(history_df: pd.DataFrame) -> dict[str, Any]:
    """Return the latest-quarter KPI summary used by the Timeline KPIs row."""
    if history_df.empty:
        return {}

    latest = history_df.iloc[-1]
    summary: dict[str, Any] = {
        "quarters": len(history_df),
        "latest_filing": latest["Filing Date"],
        "current_positions": int(latest["Normalized Positions"]),
        "raw_13f_lines": int(latest["Raw 13F Lines"]),
        "latest_accession": latest["Accession"],
    }

    previous = history_df.iloc[-2] if len(history_df) > 1 else None
    if previous is not None:
        summary["positions_delta"] = int(latest["Normalized Positions"] - previous["Normalized Positions"])

    value_col = "Portfolio Value (USD)" if "Portfolio Value (USD)" in history_df.columns else "Portfolio Value ($000s)"
    if history_df[value_col].notna().any():
        summary["latest_value"] = latest[value_col]
        if previous is not None and pd.notna(previous[value_col]) and pd.notna(latest[value_col]):
            summary["value_delta"] = float(latest[value_col] - previous[value_col])
        if "Value Multiplier" in history_df.columns:
            unique_multipliers = sorted({int(v) for v in history_df["Value Multiplier"].dropna().tolist()})
            summary["value_multiplier_summary"] = ", ".join(f"x{v}" for v in unique_multipliers)

    return summary


def build_fund_history_payload(fund: str) -> dict[str, object]:
    history_df, transitions = load_fund_history(fund)
    if history_df.empty:
        return {
            "history": [],
            "transitions": [],
            "transitions_chart": None,
            "summary": {},
            "charts": {},
        }

    value_col = "Portfolio Value (USD)" if "Portfolio Value (USD)" in history_df.columns else "Portfolio Value ($000s)"
    has_values = history_df[value_col].notna().any()
    export_df = history_df.copy()
    if has_values:
        export_df["Portfolio Value"] = export_df[value_col].apply(fmt_value_dollars)

    display_columns = ["Filing Date", "Accession", "Normalized Positions", "Raw 13F Lines"]
    if has_values:
        display_columns.append("Portfolio Value")

    positions_chart = {
        "x": export_df["Filing Date Dt"].astype(str).tolist(),
        "y": export_df["Normalized Positions"].tolist(),
        "labels": export_df["Label"].tolist(),
        "title": f"Normalized positions by quarter — {fund}",
    }
    value_chart = None
    if has_values:
        value_chart = {
            "x": export_df["Filing Date Dt"].astype(str).tolist(),
            "y": export_df[value_col].fillna(0).tolist(),
            "labels": export_df["Label"].tolist(),
            "title": f"Portfolio value by quarter — {fund}",
        }

    transitions_chart = None
    if transitions:
        transition_df = build_transition_summary_df(transitions)
        melted = transition_df.melt(
            id_vars=["Transition", "Order"],
            value_vars=["New", "Closed", "Increased", "Decreased"],
            var_name="Category",
            value_name="Positions",
        )
        melted = melted.sort_values(["Order", "Category"])
        series_order = ["New", "Closed", "Increased", "Decreased"]
        x_categories = melted["Transition"].drop_duplicates().tolist()
        series = [
            {
                "name": name,
                "values": melted.loc[melted["Category"] == name, "Positions"].tolist(),
            }
            for name in series_order
        ]
        transitions_chart = {
            "title": f"Quarter-over-quarter changes — {fund}",
            "x": x_categories,
            "series": series,
            "y_label": "Positions",
        }

    return {
        "history": records_from_dataframe(export_df[display_columns]),
        "transitions": transitions,
        "transitions_chart": transitions_chart,
        "summary": _build_history_summary(history_df),
        "charts": {
            "positions": positions_chart,
            "value": value_chart,
            "transitions": records_from_dataframe(build_transition_summary_df(transitions)) if transitions else [],
        },
    }


def build_fund_history_export(fund: str) -> dict[str, Any]:
    """Return the CSV rows + filename for the fund history export."""
    history_df, _ = load_fund_history(fund)
    if history_df.empty:
        return {"columns": [], "rows": [], "filename": f"f8_13f_{fund}_history.csv".replace(" ", "_")}

    value_col = "Portfolio Value (USD)" if "Portfolio Value (USD)" in history_df.columns else "Portfolio Value ($000s)"
    has_values = history_df[value_col].notna().any()
    export_df = history_df.copy()
    if has_values:
        export_df["Portfolio Value"] = export_df[value_col].apply(fmt_value_dollars)

    display_columns = ["Filing Date", "Accession", "Normalized Positions", "Raw 13F Lines"]
    if has_values:
        display_columns.append("Portfolio Value")

    safe_fund = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in fund) or "fund"
    return {
        "columns": display_columns,
        "rows": records_from_dataframe(export_df[display_columns]),
        "filename": f"f8_13f_{safe_fund}_history.csv",
    }


def _resolve_compare_accessions(fund: str, old_accession: str | None, new_accession: str | None) -> tuple[str, str]:
    accessions = load_accessions_for_fund(fund)
    if accessions.empty:
        raise ValueError("No accessions available for fund.")
    accession_list = accessions["accession_number"].tolist()
    resolved_new = new_accession or accession_list[0]
    resolved_old = old_accession or (accession_list[1] if len(accession_list) > 1 else accession_list[0])
    return resolved_old, resolved_new


def _resolve_scale_mode(scale_mode: str | None) -> str:
    candidate = (scale_mode or "linear").lower()
    return candidate if candidate in SHARES_FLOW_SCALE_MODES else "linear"


def build_fund_compare(
    fund: str,
    *,
    old_accession: str | None = None,
    new_accession: str | None = None,
) -> dict[str, object]:
    resolved_old, resolved_new = _resolve_compare_accessions(fund, old_accession, new_accession)
    old_map = load_normalized_positions_map(fund, resolved_old)
    new_map = load_normalized_positions_map(fund, resolved_new)
    diff = compute_detailed_portfolio_diff(old_map, new_map)
    return {
        "fund": fund,
        "old_accession": resolved_old,
        "new_accession": resolved_new,
        "counts": {
            "new": len(diff["new_positions"]),
            "closed": len(diff["closed_positions"]),
            "increased": len(diff["increased"]),
            "decreased": len(diff["decreased"]),
        },
        "diff": diff,
        "highlights": build_compare_highlights(diff),
        "top_movers": build_top_movers(diff),
        "formatted_diff": build_formatted_diff_sections(diff),
    }


def build_compare_sankey(
    fund: str,
    *,
    old_accession: str | None = None,
    new_accession: str | None = None,
    top_n: int = 20,
    top_n_buys: int | None = None,
    top_n_sells: int | None = None,
    scale_mode: str | None = None,
    min_visible_pct: float | None = None,
    include_options: bool = False,
) -> dict[str, Any]:
    payload = build_fund_compare(fund, old_accession=old_accession, new_accession=new_accession)
    sankey = build_shares_flow_sankey_data(
        payload["diff"],
        top_n=top_n,
        top_n_buys=top_n_buys,
        top_n_sells=top_n_sells,
        include_options=include_options,
    )

    raw_values = list(sankey["link"]["value"])
    normalized_scale_mode = _resolve_scale_mode(scale_mode)
    pct_value = float(min_visible_pct or 0)
    display_values = scale_shares_flow_values(
        raw_values,
        scale_mode=normalized_scale_mode,
        min_visible_pct=pct_value,
    )
    sankey["link"]["value"] = display_values
    sankey["raw_values"] = raw_values
    sankey["scale_mode"] = normalized_scale_mode
    sankey["min_visible_pct"] = pct_value
    sankey["include_options"] = bool(include_options)
    sankey["customdata"] = sankey["link"].get("customdata", [])
    return sankey


def build_compare_lanes(
    fund: str,
    *,
    old_accession: str | None = None,
    new_accession: str | None = None,
    top_n: int = 20,
    top_n_buys: int | None = None,
    top_n_sells: int | None = None,
    include_options: bool = False,
) -> dict[str, Any]:
    payload = build_fund_compare(fund, old_accession=old_accession, new_accession=new_accession)
    lanes_df = build_shares_change_lane_data(
        payload["diff"],
        top_n=top_n,
        top_n_buys=top_n_buys,
        top_n_sells=top_n_sells,
        include_options=include_options,
    )
    return {
        "rows": records_from_dataframe(lanes_df) if not lanes_df.empty else [],
    }


def build_compare_export(fund: str, section: str, **params: Any) -> dict[str, Any]:
    """Return the CSV rows + filename for a single diff section (new/closed/changes)."""
    payload = build_fund_compare(**{"fund": fund, **{k: v for k, v in params.items() if k in {"old_accession", "new_accession"}}})
    diff = payload["diff"]
    safe_fund = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in fund) or "fund"
    safe_section = section.lower()

    if safe_section == "new_positions":
        formatted = payload["formatted_diff"]["new_positions"]
        return {
            "columns": list(formatted["rows"][0].keys()) if formatted["rows"] else [],
            "rows": formatted["rows"],
            "filename": f"f8_13f_{safe_fund}_new_positions.csv",
        }
    if safe_section == "closed_positions":
        formatted = payload["formatted_diff"]["closed_positions"]
        return {
            "columns": list(formatted["rows"][0].keys()) if formatted["rows"] else [],
            "rows": formatted["rows"],
            "filename": f"f8_13f_{safe_fund}_closed_positions.csv",
        }
    if safe_section == "share_changes":
        formatted = payload["formatted_diff"]["share_changes"]
        return {
            "columns": list(formatted["rows"][0].keys()) if formatted["rows"] else [],
            "rows": formatted["rows"],
            "filename": f"f8_13f_{safe_fund}_share_changes.csv",
        }
    if safe_section == "top_movers":
        movers = payload["top_movers"]
        return {
            "columns": list(movers["rows"][0].keys()) if movers["rows"] else [],
            "rows": movers["rows"],
            "filename": f"f8_13f_{safe_fund}_top_movers.csv",
        }
    raise ValueError(f"Unknown diff section: {section}")
