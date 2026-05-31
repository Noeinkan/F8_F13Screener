"""Streamlit renderers for portfolio diff views."""

import pandas as pd
import streamlit as st

from src.web.formatting import (
    dataframe_to_csv_bytes,
    fmt_quantity,
    fmt_signed_pct,
    fmt_signed_quantity,
    fmt_signed_value,
    fmt_value,
)
from src.web.table_config import DEFAULT_TABLE_HEIGHT, LARGE_TABLE_HEIGHT, diff_column_config, holdings_column_config
from src.web.ui_components import render_dataframe


def _change_direction(pct_change: float) -> str:
    return "Increase" if pct_change > 0 else "Decrease"


def _build_changes_table(changes: list[dict]) -> pd.DataFrame:
    changes_df = pd.DataFrame(changes).copy()
    changes_df["Direction"] = changes_df["pct_change"].apply(_change_direction)
    changes_df["Magnitude"] = changes_df["pct_change"].abs()
    changes_df = changes_df.sort_values(["Magnitude", "issuer_name"], ascending=[False, True])
    changes_df["Shares Before"] = changes_df["old_shares"].apply(fmt_quantity)
    changes_df["Shares After"] = changes_df["new_shares"].apply(fmt_quantity)
    changes_df["Delta Shares"] = changes_df["share_change"].apply(fmt_signed_quantity)
    changes_df["Delta %"] = changes_df["pct_change"].apply(fmt_signed_pct)
    changes_df["Value Before"] = changes_df["old_value_usd"].apply(fmt_value)
    changes_df["Value After"] = changes_df["new_value_usd"].apply(fmt_value)
    changes_df["Delta Value"] = changes_df["value_change"].apply(fmt_signed_value)
    changes_df["Delta Value %"] = changes_df["value_pct_change"].apply(fmt_signed_pct)
    return pd.DataFrame({
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


def _style_changes_table(row: pd.Series) -> list[str]:
    base_color = "rgba(46, 160, 67, 0.18)" if row["Direction"] == "Increase" else "rgba(248, 81, 73, 0.18)"
    accent_color = "rgba(46, 160, 67, 0.34)" if row["Direction"] == "Increase" else "rgba(248, 81, 73, 0.34)"
    accent_columns = {"Direction", "Delta %", "Delta Shares", "Delta Value %", "Delta Value"}
    return [
        f"background-color: {accent_color}; font-weight: 600" if column in accent_columns else f"background-color: {base_color}"
        for column in row.index
    ]


def render_detailed_diff_sections(diff: dict, *, dense: bool = False, table_height: int | None = None):
    height = table_height or (DEFAULT_TABLE_HEIGHT if dense else LARGE_TABLE_HEIGHT)

    if diff["new_positions"]:
        st.subheader(f"New positions ({len(diff['new_positions']):,})")
        new_df = pd.DataFrame(diff["new_positions"]).sort_values(
            ["value_usd", "issuer_name"],
            ascending=[False, True],
            na_position="last",
        )
        new_df["Shares"] = new_df["shares"].apply(fmt_quantity)
        new_df["Value"] = new_df["value_usd"].apply(fmt_value)
        display_df = pd.DataFrame({
            "Issuer": new_df["issuer_name"],
            "CUSIP": new_df["cusip"],
            "Class": new_df["share_class"],
            "Put/Call": new_df["put_call"],
            "Shares": new_df["Shares"],
            "Value": new_df["Value"],
        })
        st.download_button(
            "Download new positions",
            dataframe_to_csv_bytes(display_df),
            file_name="f8_13f_new_positions.csv",
            mime="text/csv",
            key=f"diff_new_positions_download_{id(diff)}",
        )
        render_dataframe(display_df, column_config=holdings_column_config(), height=height)

    if diff["closed_positions"]:
        st.subheader(f"Closed positions ({len(diff['closed_positions']):,})")
        closed_df = pd.DataFrame(diff["closed_positions"]).sort_values(
            ["value_usd", "issuer_name"],
            ascending=[False, True],
            na_position="last",
        )
        closed_df["Previous Shares"] = closed_df["shares"].apply(fmt_quantity)
        closed_df["Previous Value"] = closed_df["value_usd"].apply(fmt_value)
        display_df = pd.DataFrame({
            "Issuer": closed_df["issuer_name"],
            "CUSIP": closed_df["cusip"],
            "Class": closed_df["share_class"],
            "Put/Call": closed_df["put_call"],
            "Previous Shares": closed_df["Previous Shares"],
            "Previous Value": closed_df["Previous Value"],
        })
        st.download_button(
            "Download closed positions",
            dataframe_to_csv_bytes(display_df),
            file_name="f8_13f_closed_positions.csv",
            mime="text/csv",
            key=f"diff_closed_positions_download_{id(diff)}",
        )
        render_dataframe(display_df, column_config=holdings_column_config(), height=height)

    changes = diff["increased"] + diff["decreased"]
    if changes:
        st.subheader(f"All share changes ({len(changes):,})")
        st.caption("Sorted by absolute percentage move. Green rows are increases; red rows are decreases.")
        changes_display_df = _build_changes_table(changes)
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