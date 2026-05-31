"""Streamlit renderers for instrument history views."""

from collections.abc import Callable

import pandas as pd
import plotly.express as px
import streamlit as st

from src.web.formatting import (
    fmt_quantity,
    fmt_signed_pct,
    fmt_signed_quantity,
    fmt_value,
)
from src.web.instrument_transforms import (
    build_instrument_option_summary,
    build_instrument_timeseries,
)


def render_instrument_history_explorer(
    history_df: pd.DataFrame,
    instrument_history_df: pd.DataFrame,
    fund: str,
    require_selection: Callable[[str | None, str], str],
):
    if history_df.empty or instrument_history_df.empty:
        return

    option_summary_df = build_instrument_option_summary(instrument_history_df)
    if option_summary_df.empty:
        return

    st.subheader("Single Position History")
    st.caption(
        "Select one normalized position from the fund. Equity, CALL, and PUT on the same underlying "
        "remain separate, so you can clearly see whether the fund is increasing or reducing shares "
        "for that specific exposure."
    )

    option_labels = option_summary_df.set_index("Position Key")["Instrument Label"].to_dict()
    selected_position_key = require_selection(
        st.selectbox(
            "Select position",
            option_summary_df["Position Key"].tolist(),
            format_func=lambda key: option_labels[key],
            key="fund_analysis_instrument",
        ),
        "Select a position to view share history.",
    )

    timeseries_df = build_instrument_timeseries(history_df, instrument_history_df, selected_position_key)
    if timeseries_df.empty:
        st.info("No historical series available for the selected position.")
        return

    selected_label = option_labels[selected_position_key]
    latest_row = timeseries_df.iloc[-1]
    previous_row = timeseries_df.iloc[-2] if len(timeseries_df) > 1 else None
    visible_rows = timeseries_df.loc[timeseries_df["Present"]]
    first_seen = visible_rows["Filing Date"].iloc[0] if not visible_rows.empty else "-"
    last_seen = visible_rows["Filing Date"].iloc[-1] if not visible_rows.empty else "-"

    st.caption(
        "Latest filing status: present."
        if bool(latest_row["Present"])
        else "Latest filing status: missing. The series shows a gap when the instrument is not present in the filing."
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Shares in latest filing", fmt_quantity(latest_row["Shares Filled"]))
    c2.metric(
        "Shares in previous filing",
        fmt_quantity(previous_row["Shares Filled"]) if previous_row is not None else "-",
    )
    c3.metric("Δ Shares in latest filing", fmt_signed_quantity(latest_row["Δ Shares"]))
    c4.metric("Δ % in latest filing", fmt_signed_pct(latest_row["Δ %"]))
    c5.metric("First appearance", first_seen)
    c6.metric("Last appearance", last_seen)

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        shares_fig = px.line(
            timeseries_df,
            x="Filing Date Dt",
            y="Shares",
            markers=True,
            hover_name="Instrument Label",
            hover_data={
                "Filing Date": True,
                "Accession": True,
                "Position Status": True,
                "Shares": True,
                "Value ($000s)": True,
                "Class": True,
                "Put/Call": True,
                "Instrument Type": True,
                "Filing Date Dt": False,
                "Label": False,
                "Shares Filled": False,
                "Previous Shares": False,
                "Previous Filing": False,
                "Δ Shares": False,
                "Δ %": False,
                "Issuer": False,
                "CUSIP": False,
                "Instrument Label": False,
            },
            title=f"Shares over time — {selected_label}",
        )
        shares_fig.update_traces(connectgaps=False)
        shares_fig.update_xaxes(title="Filing date")
        shares_fig.update_yaxes(title="Shares")
        st.plotly_chart(shares_fig, use_container_width=True)

    with chart_col2:
        delta_df = timeseries_df.loc[timeseries_df["Previous Filing"].notna()].copy()
        delta_df["Transition"] = delta_df["Previous Filing"] + " → " + delta_df["Filing Date"]
        delta_df["Direction"] = delta_df["Δ Shares"].apply(
            lambda value: "Increase" if value > 0 else "Decrease" if value < 0 else "Unchanged"
        )
        delta_fig = px.bar(
            delta_df,
            x="Transition",
            y="Δ Shares",
            color="Direction",
            hover_name="Instrument Label",
            hover_data={
                "Filing Date": True,
                "Accession": True,
                "Shares Filled": True,
                "Previous Shares": True,
                "Δ %": True,
                "Transition": False,
                "Instrument Label": False,
            },
            title=f"Δ shares quarter over quarter — {selected_label}",
        )
        delta_fig.update_layout(xaxis_tickangle=-30)
        delta_fig.update_xaxes(title="Transition")
        delta_fig.update_yaxes(title="Δ Shares")
        st.plotly_chart(delta_fig, use_container_width=True)

    detail_df = timeseries_df.copy()
    detail_df["Shares"] = detail_df["Shares"].apply(fmt_quantity)
    detail_df["Value ($000s)"] = detail_df["Value ($000s)"].apply(fmt_value)
    detail_df["Δ Shares"] = detail_df["Δ Shares"].apply(fmt_signed_quantity)
    detail_df["Δ %"] = detail_df["Δ %"].apply(fmt_signed_pct)
    st.dataframe(
        detail_df[
            [
                "Filing Date",
                "Accession",
                "Position Status",
                "Shares",
                "Δ Shares",
                "Δ %",
                "Value ($000s)",
                "Class",
                "Put/Call",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )