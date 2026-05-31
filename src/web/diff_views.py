"""Streamlit renderers for portfolio diff views."""

import pandas as pd
import streamlit as st

from src.web.formatting import (
    fmt_quantity,
    fmt_signed_pct,
    fmt_signed_quantity,
    fmt_signed_value,
    fmt_value,
)


def render_detailed_diff_sections(diff: dict):
    if diff["new_positions"]:
        st.subheader("New positions")
        new_df = pd.DataFrame(diff["new_positions"]).sort_values(
            ["value_usd", "issuer_name"],
            ascending=[False, True],
            na_position="last",
        )
        new_df["Shares"] = new_df["shares"].apply(fmt_quantity)
        new_df["Value"] = new_df["value_usd"].apply(fmt_value)
        st.dataframe(
            pd.DataFrame({
                "Issuer": new_df["issuer_name"],
                "CUSIP": new_df["cusip"],
                "Class": new_df["share_class"],
                "Put/Call": new_df["put_call"],
                "Shares": new_df["Shares"],
                "Value": new_df["Value"],
            }),
            use_container_width=True,
            hide_index=True,
        )

    if diff["closed_positions"]:
        st.subheader("Closed positions")
        closed_df = pd.DataFrame(diff["closed_positions"]).sort_values(
            ["value_usd", "issuer_name"],
            ascending=[False, True],
            na_position="last",
        )
        closed_df["Previous Shares"] = closed_df["shares"].apply(fmt_quantity)
        closed_df["Previous Value"] = closed_df["value_usd"].apply(fmt_value)
        st.dataframe(
            pd.DataFrame({
                "Issuer": closed_df["issuer_name"],
                "CUSIP": closed_df["cusip"],
                "Class": closed_df["share_class"],
                "Put/Call": closed_df["put_call"],
                "Previous Shares": closed_df["Previous Shares"],
                "Previous Value": closed_df["Previous Value"],
            }),
            use_container_width=True,
            hide_index=True,
        )

    changes = diff["increased"] + diff["decreased"]
    if changes:
        st.subheader("Significant changes (≥10%)")
        changes_df = pd.DataFrame(changes).sort_values("pct_change", ascending=False)
        changes_df["Shares Before"] = changes_df["old_shares"].apply(fmt_quantity)
        changes_df["Shares After"] = changes_df["new_shares"].apply(fmt_quantity)
        changes_df["Δ Shares"] = changes_df["share_change"].apply(fmt_signed_quantity)
        changes_df["Δ %"] = changes_df["pct_change"].apply(fmt_signed_pct)
        changes_df["Value Before"] = changes_df["old_value_usd"].apply(fmt_value)
        changes_df["Value After"] = changes_df["new_value_usd"].apply(fmt_value)
        changes_df["Δ Value"] = changes_df["value_change"].apply(fmt_signed_value)
        changes_df["Δ Value %"] = changes_df["value_pct_change"].apply(fmt_signed_pct)
        st.dataframe(
            pd.DataFrame({
                "Issuer": changes_df["issuer_name"],
                "CUSIP": changes_df["cusip"],
                "Class": changes_df["share_class"],
                "Put/Call": changes_df["put_call"],
                "Shares Before": changes_df["Shares Before"],
                "Shares After": changes_df["Shares After"],
                "Δ Shares": changes_df["Δ Shares"],
                "Δ %": changes_df["Δ %"],
                "Value Before": changes_df["Value Before"],
                "Value After": changes_df["Value After"],
                "Δ Value": changes_df["Δ Value"],
                "Δ Value %": changes_df["Δ Value %"],
            }),
            use_container_width=True,
            hide_index=True,
        )

    if not any([diff["new_positions"], diff["closed_positions"], changes]):
        st.success("No significant changes between the two quarters.")