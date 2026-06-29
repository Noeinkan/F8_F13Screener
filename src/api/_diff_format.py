"""Pure (Streamlit-free) formatters for Fund Analysis diff payloads.

These helpers port the display logic that previously lived inside
``src/web/diff_views.py`` and ``src/web/pages/fund_analysis.py`` so the
React UI (and any other consumer) can render the same formatted tables
and CSV exports without depending on Streamlit at runtime.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.api.serialize import records_from_dataframe
from src.web.formatting import (
    fmt_quantity,
    fmt_signed_pct,
    fmt_signed_quantity,
    fmt_signed_value_dollars,
    fmt_value_dollars,
)
from src.web.instrument_transforms import add_instrument_type_column
from src.web.tickers import add_ticker_column
from src.web.value_units import infer_value_multiplier_from_frame


def _numeric_or_zero(value: Any) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return float(value)


def _change_direction(pct_change: float | None) -> str:
    if pct_change is None or pd.isna(pct_change):
        return ""
    return "Increase" if pct_change > 0 else "Decrease"


def _infer_positions_value_multiplier(positions_df: pd.DataFrame) -> int:
    if positions_df.empty:
        return 1
    return infer_value_multiplier_from_frame(positions_df, value_col="value_usd", shares_col="shares")


def _infer_diff_value_multiplier(diff: dict) -> int:
    rows: list[dict[str, Any]] = []
    for position in diff.get("new_positions", []) + diff.get("closed_positions", []):
        rows.append({"value": position.get("value_usd"), "shares": position.get("shares")})
    for position in diff.get("increased", []) + diff.get("decreased", []):
        rows.append({"value": position.get("old_value_usd"), "shares": position.get("old_shares")})
        rows.append({"value": position.get("new_value_usd"), "shares": position.get("new_shares")})
    if not rows:
        return 1
    return infer_value_multiplier_from_frame(pd.DataFrame(rows), value_col="value", shares_col="shares")


def _infer_changes_value_multiplier(changes_df: pd.DataFrame) -> int:
    if changes_df.empty:
        return 1
    old_mult = infer_value_multiplier_from_frame(changes_df, value_col="old_value_usd", shares_col="old_shares")
    new_mult = infer_value_multiplier_from_frame(changes_df, value_col="new_value_usd", shares_col="new_shares")
    return 1000 if 1000 in (old_mult, new_mult) else 1


def _fmt_value_move(value: Any, multiplier: int) -> str:
    if value is None or pd.isna(value):
        return "-"
    return fmt_signed_value_dollars(float(value) * multiplier)


def _largest_by_value(items: list[dict], key: str) -> dict | None:
    if not items:
        return None
    return max(items, key=lambda item: _numeric_or_zero(item.get(key)))


def _largest_by_abs(items: list[dict], key: str) -> dict | None:
    if not items:
        return None
    return max(items, key=lambda item: abs(_numeric_or_zero(item.get(key))))


def _position_label(position: dict | None) -> str:
    if not position:
        return "-"
    issuer = str(position.get("issuer_name") or "").strip()
    put_call = str(position.get("put_call") or "").strip().upper()
    share_class = str(position.get("share_class") or "").strip()
    suffix = " ".join(part for part in [share_class, put_call] if part)
    if issuer and suffix:
        return f"{issuer} ({suffix})"
    if issuer:
        return issuer
    return str(position.get("cusip") or "-")


def build_compare_highlights(diff: dict) -> list[dict[str, Any]]:
    """Return the four-largest-position highlight tiles for the Compare tab."""
    new_position = _largest_by_value(diff.get("new_positions", []), "shares")
    closed_position = _largest_by_value(diff.get("closed_positions", []), "shares")
    increased_position = _largest_by_abs(diff.get("increased", []), "share_change")
    decreased_position = _largest_by_abs(diff.get("decreased", []), "share_change")

    return [
        {
            "label": "Largest new",
            "position_label": _position_label(new_position),
            "value": fmt_quantity(new_position.get("shares")) if new_position else "-",
            "context": "reported shares",
        },
        {
            "label": "Largest closed",
            "position_label": _position_label(closed_position),
            "value": fmt_quantity(closed_position.get("shares")) if closed_position else "-",
            "context": "previous shares",
        },
        {
            "label": "Largest increase",
            "position_label": _position_label(increased_position),
            "value": fmt_signed_quantity(increased_position.get("share_change")) if increased_position else "-",
            "context": fmt_signed_pct(increased_position.get("pct_change")) if increased_position else "-",
        },
        {
            "label": "Largest decrease",
            "position_label": _position_label(decreased_position),
            "value": fmt_signed_quantity(decreased_position.get("share_change")) if decreased_position else "-",
            "context": fmt_signed_pct(decreased_position.get("pct_change")) if decreased_position else "-",
        },
    ]


def build_top_movers(diff: dict, *, limit: int = 12) -> dict[str, Any]:
    """Build the formatted top-movers table (and capture the value multiplier caption)."""
    rows: list[dict[str, Any]] = []

    for position in diff.get("new_positions", []):
        shares = _numeric_or_zero(position.get("shares"))
        rows.append({
            "Ticker": position.get("cusip"),
            "Type": "Purchase",
            "Movement": "New",
            "Issuer": position.get("issuer_name"),
            "Delta Shares": fmt_signed_quantity(shares),
            "Delta %": "New",
            "Delta Value": _fmt_value_move(position.get("value_usd"), _infer_diff_value_multiplier(diff)),
            "Shares Before": "-",
            "Shares After": fmt_quantity(shares),
            "CUSIP": position.get("cusip"),
            "Class": position.get("share_class"),
            "Put/Call": position.get("put_call"),
            "_Sort Magnitude": abs(shares),
        })

    for position in diff.get("closed_positions", []):
        shares = _numeric_or_zero(position.get("shares"))
        value = position.get("value_usd")
        rows.append({
            "Ticker": position.get("cusip"),
            "Type": "Sell",
            "Movement": "Closed",
            "Issuer": position.get("issuer_name"),
            "Delta Shares": fmt_signed_quantity(-shares),
            "Delta %": "Closed",
            "Delta Value": _fmt_value_move(-float(value), _infer_diff_value_multiplier(diff))
                if value is not None and not pd.isna(value)
                else "-",
            "Shares Before": fmt_quantity(shares),
            "Shares After": "-",
            "CUSIP": position.get("cusip"),
            "Class": position.get("share_class"),
            "Put/Call": position.get("put_call"),
            "_Sort Magnitude": abs(shares),
        })

    for movement, positions in (("Increase", diff.get("increased", [])), ("Decrease", diff.get("decreased", []))):
        for position in positions:
            share_change = _numeric_or_zero(position.get("share_change"))
            rows.append({
                "Ticker": position.get("cusip"),
                "Type": "Purchase" if share_change > 0 else "Sell",
                "Movement": movement,
                "Issuer": position.get("issuer_name"),
                "Delta Shares": fmt_signed_quantity(share_change),
                "Delta %": fmt_signed_pct(position.get("pct_change")),
                "Delta Value": _fmt_value_move(position.get("value_change"), _infer_diff_value_multiplier(diff)),
                "Shares Before": fmt_quantity(position.get("old_shares")),
                "Shares After": fmt_quantity(position.get("new_shares")),
                "CUSIP": position.get("cusip"),
                "Class": position.get("share_class"),
                "Put/Call": position.get("put_call"),
                "_Sort Magnitude": abs(share_change),
            })

    if not rows:
        return {"rows": [], "value_multiplier": _infer_diff_value_multiplier(diff)}

    movers_df = (
        pd.DataFrame(rows)
        .sort_values(["_Sort Magnitude", "Issuer"], ascending=[False, True])
        .head(limit)
        .drop(columns=["_Sort Magnitude"])
    )
    movers_df = add_instrument_type_column(add_ticker_column(movers_df), put_call_column="Put/Call")
    if "Type" in movers_df.columns:
        movers_df["Type"] = movers_df["Type"].fillna(movers_df.get("Type"))

    return {
        "rows": records_from_dataframe(movers_df),
        "value_multiplier": _infer_diff_value_multiplier(diff),
    }


def build_new_positions_section(diff: dict) -> dict[str, Any]:
    new_positions = diff.get("new_positions", []) or []
    if not new_positions:
        return {"rows": [], "count": 0, "value_multiplier": 1, "type_label": "Purchase"}

    new_df = pd.DataFrame(new_positions).sort_values(
        ["value_usd", "issuer_name"],
        ascending=[False, True],
        na_position="last",
    )
    multiplier = _infer_positions_value_multiplier(new_df)
    new_df["Shares"] = new_df["shares"].apply(fmt_quantity)
    new_df["Value"] = (new_df["value_usd"] * multiplier).apply(fmt_value_dollars)
    display_df = add_instrument_type_column(
        add_ticker_column(pd.DataFrame({
            "Issuer": new_df["issuer_name"],
            "CUSIP": new_df["cusip"],
            "Class": new_df["share_class"],
            "Put/Call": new_df["put_call"],
            "Shares": new_df["Shares"],
            "Value": new_df["Value"],
        }))
    )
    display_df["Type"] = "Purchase"
    return {
        "rows": records_from_dataframe(display_df),
        "count": len(new_positions),
        "value_multiplier": multiplier,
        "type_label": "Purchase",
    }


def build_closed_positions_section(diff: dict) -> dict[str, Any]:
    closed_positions = diff.get("closed_positions", []) or []
    if not closed_positions:
        return {"rows": [], "count": 0, "value_multiplier": 1, "type_label": "Sell"}

    closed_df = pd.DataFrame(closed_positions).sort_values(
        ["value_usd", "issuer_name"],
        ascending=[False, True],
        na_position="last",
    )
    multiplier = _infer_positions_value_multiplier(closed_df)
    closed_df["Previous Shares"] = closed_df["shares"].apply(fmt_quantity)
    closed_df["Previous Value"] = (closed_df["value_usd"] * multiplier).apply(fmt_value_dollars)
    display_df = add_instrument_type_column(
        add_ticker_column(pd.DataFrame({
            "Issuer": closed_df["issuer_name"],
            "CUSIP": closed_df["cusip"],
            "Class": closed_df["share_class"],
            "Put/Call": closed_df["put_call"],
            "Previous Shares": closed_df["Previous Shares"],
            "Previous Value": closed_df["Previous Value"],
        }))
    )
    display_df["Type"] = "Sell"
    return {
        "rows": records_from_dataframe(display_df),
        "count": len(closed_positions),
        "value_multiplier": multiplier,
        "type_label": "Sell",
    }


def build_share_changes_section(diff: dict) -> dict[str, Any]:
    changes = list(diff.get("increased", []) or []) + list(diff.get("decreased", []) or [])
    if not changes:
        return {"rows": [], "count": 0, "value_multiplier": 1}

    changes_df = pd.DataFrame(changes).copy()
    multiplier = _infer_changes_value_multiplier(changes_df)
    changes_df["old_value_display"] = changes_df["old_value_usd"] * multiplier
    changes_df["new_value_display"] = changes_df["new_value_usd"] * multiplier
    changes_df["value_change_display"] = changes_df["value_change"] * multiplier
    changes_df["Direction"] = changes_df["pct_change"].apply(_change_direction)
    changes_df["Magnitude"] = changes_df["pct_change"].abs()
    changes_df = changes_df.sort_values(["Magnitude", "issuer_name"], ascending=[False, True])
    changes_df["Shares Before"] = changes_df["old_shares"].apply(fmt_quantity)
    changes_df["Shares After"] = changes_df["new_shares"].apply(fmt_quantity)
    changes_df["Delta Shares"] = changes_df["share_change"].apply(fmt_signed_quantity)
    changes_df["Delta %"] = changes_df["pct_change"].apply(fmt_signed_pct)
    changes_df["Value Before"] = changes_df["old_value_display"].apply(fmt_value_dollars)
    changes_df["Value After"] = changes_df["new_value_display"].apply(fmt_value_dollars)
    changes_df["Delta Value"] = changes_df["value_change_display"].apply(fmt_signed_value_dollars)
    changes_df["Delta Value %"] = changes_df["value_pct_change"].apply(fmt_signed_pct)
    display_df = pd.DataFrame({
        "Issuer": changes_df["issuer_name"],
        "Direction": changes_df["Direction"],
        "Delta %": changes_df["Delta %"],
        "Delta Shares": changes_df["Delta Shares"],
        "Delta Value %": changes_df["Delta Value %"],
        "Delta Value": changes_df["Delta Value"],
        "Shares Before": changes_df["Shares Before"],
        "Shares After": changes_df["Shares After"],
        "Value Before": changes_df["Value Before"],
        "Value After": changes_df["Value After"],
        "CUSIP": changes_df["cusip"],
        "Class": changes_df["share_class"],
        "Put/Call": changes_df["put_call"],
    })
    display_df = add_instrument_type_column(add_ticker_column(display_df))
    display_df["Type"] = display_df["Direction"].map({"Increase": "Purchase", "Decrease": "Sell"})
    return {
        "rows": records_from_dataframe(display_df),
        "count": len(changes),
        "value_multiplier": multiplier,
    }


def build_formatted_diff_sections(diff: dict) -> dict[str, Any]:
    """Return every formatted diff section + the related multiplier captions."""
    new_section = build_new_positions_section(diff)
    closed_section = build_closed_positions_section(diff)
    changes_section = build_share_changes_section(diff)
    return {
        "new_positions": new_section,
        "closed_positions": closed_section,
        "share_changes": changes_section,
        "has_any": bool(new_section["count"] or closed_section["count"] or changes_section["count"]),
    }
