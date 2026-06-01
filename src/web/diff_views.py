"""Streamlit renderers for portfolio diff views."""

import pandas as pd
import streamlit as st

from src.web.formatting import (
    dataframe_to_csv_bytes,
    fmt_quantity,
    fmt_signed_pct,
    fmt_signed_quantity,
    fmt_signed_value_dollars,
    fmt_value_dollars,
)
from src.web.instrument_transforms import add_instrument_type_column, instrument_type_cell_styles, style_instrument_type_column
from src.web.table_config import DEFAULT_TABLE_HEIGHT, LARGE_TABLE_HEIGHT, diff_column_config, holdings_column_config
from src.web.tickers import add_ticker_column
from src.web.ui_components import render_dataframe
from src.web.value_units import infer_value_multiplier_from_frame


def _change_direction(pct_change: float) -> str:
    return "Increase" if pct_change > 0 else "Decrease"


def _infer_changes_value_multiplier(changes_df: pd.DataFrame) -> int:
    old_mult = infer_value_multiplier_from_frame(changes_df, value_col="old_value_usd", shares_col="old_shares")
    new_mult = infer_value_multiplier_from_frame(changes_df, value_col="new_value_usd", shares_col="new_shares")
    return 1000 if 1000 in (old_mult, new_mult) else 1


def _build_changes_table(changes: list[dict]) -> tuple[pd.DataFrame, int]:
    changes_df = pd.DataFrame(changes).copy()
    value_multiplier = _infer_changes_value_multiplier(changes_df)
    changes_df["old_value_display"] = changes_df["old_value_usd"] * value_multiplier
    changes_df["new_value_display"] = changes_df["new_value_usd"] * value_multiplier
    changes_df["value_change_display"] = changes_df["value_change"] * value_multiplier

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
    return display_df, value_multiplier


def _infer_positions_value_multiplier(positions_df: pd.DataFrame) -> int:
    return infer_value_multiplier_from_frame(positions_df, value_col="value_usd", shares_col="shares")


def _style_changes_table(row: pd.Series) -> list[str]:
    base_color = "rgba(46, 160, 67, 0.18)" if row["Direction"] == "Increase" else "rgba(248, 81, 73, 0.18)"
    accent_color = "rgba(46, 160, 67, 0.34)" if row["Direction"] == "Increase" else "rgba(248, 81, 73, 0.34)"
    accent_columns = {"Direction", "Delta %", "Delta Shares", "Delta Value %", "Delta Value"}
    styles = [
        f"background-color: {accent_color}; font-weight: 600" if column in accent_columns else f"background-color: {base_color}"
        for column in row.index
    ]
    for index, type_style in enumerate(instrument_type_cell_styles(row)):
        if type_style:
            styles[index] = type_style
    return styles


def render_detailed_diff_sections(diff: dict, *, dense: bool = False, table_height: int | None = None):
    height = table_height or (DEFAULT_TABLE_HEIGHT if dense else LARGE_TABLE_HEIGHT)

    if diff["new_positions"]:
        st.subheader(f"New positions ({len(diff['new_positions']):,})")
        new_df = pd.DataFrame(diff["new_positions"]).sort_values(
            ["value_usd", "issuer_name"],
            ascending=[False, True],
            na_position="last",
        )
        new_value_multiplier = _infer_positions_value_multiplier(new_df)
        new_df["Shares"] = new_df["shares"].apply(fmt_quantity)
        new_df["Value"] = (new_df["value_usd"] * new_value_multiplier).apply(fmt_value_dollars)
        display_df = add_instrument_type_column(add_ticker_column(pd.DataFrame({
            "Issuer": new_df["issuer_name"],
            "CUSIP": new_df["cusip"],
            "Class": new_df["share_class"],
            "Put/Call": new_df["put_call"],
            "Shares": new_df["Shares"],
            "Value": new_df["Value"],
        })))
        display_df["Type"] = "Purchase"
        st.caption(
            "Displayed values are auto-scaled from stored units using implied per-share prices "
            f"(multiplier x{new_value_multiplier})."
        )
        st.download_button(
            "Download new positions",
            dataframe_to_csv_bytes(display_df),
            file_name="f8_13f_new_positions.csv",
            mime="text/csv",
            key=f"diff_new_positions_download_{id(diff)}",
        )
        render_dataframe(style_instrument_type_column(display_df), column_config=holdings_column_config(), height=height)

    if diff["closed_positions"]:
        st.subheader(f"Closed positions ({len(diff['closed_positions']):,})")
        closed_df = pd.DataFrame(diff["closed_positions"]).sort_values(
            ["value_usd", "issuer_name"],
            ascending=[False, True],
            na_position="last",
        )
        closed_value_multiplier = _infer_positions_value_multiplier(closed_df)
        closed_df["Previous Shares"] = closed_df["shares"].apply(fmt_quantity)
        closed_df["Previous Value"] = (closed_df["value_usd"] * closed_value_multiplier).apply(fmt_value_dollars)
        display_df = add_instrument_type_column(add_ticker_column(pd.DataFrame({
            "Issuer": closed_df["issuer_name"],
            "CUSIP": closed_df["cusip"],
            "Class": closed_df["share_class"],
            "Put/Call": closed_df["put_call"],
            "Previous Shares": closed_df["Previous Shares"],
            "Previous Value": closed_df["Previous Value"],
        })))
        display_df["Type"] = "Sell"
        st.caption(
            "Displayed values are auto-scaled from stored units using implied per-share prices "
            f"(multiplier x{closed_value_multiplier})."
        )
        st.download_button(
            "Download closed positions",
            dataframe_to_csv_bytes(display_df),
            file_name="f8_13f_closed_positions.csv",
            mime="text/csv",
            key=f"diff_closed_positions_download_{id(diff)}",
        )
        render_dataframe(style_instrument_type_column(display_df), column_config=holdings_column_config(), height=height)

    changes = diff["increased"] + diff["decreased"]
    if changes:
        st.subheader(f"All share changes ({len(changes):,})")
        st.caption("Sorted by absolute percentage move. Green rows are increases; red rows are decreases.")
        changes_display_df, value_multiplier = _build_changes_table(changes)
        st.caption(
            "Value columns are auto-scaled from stored units using implied per-share prices "
            f"(multiplier x{value_multiplier})."
        )
        st.download_button(
            "Download share changes",
            dataframe_to_csv_bytes(changes_display_df),
            file_name="f8_13f_share_changes.csv",
            mime="text/csv",
            key=f"diff_share_changes_download_{id(diff)}",
        )
        st.dataframe(
            changes_display_df.style.apply(_style_changes_table, axis=1),
            use_container_width=True,
            hide_index=True,
            height=height,
            column_config=diff_column_config(),
        )

    if not any([diff["new_positions"], diff["closed_positions"], changes]):
        st.success("No changes between the two quarters.")