"""Streamlit chart renderers for dashboard pages."""

import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.web.formatting import fmt_quantity, fmt_signed_quantity, fmt_signed_value_dollars
from src.web.value_units import infer_value_multiplier_from_frame


BUY_NODE = "Bought shares"
SELL_NODE = "Sold shares"
DEFAULT_SHARES_FLOW_TOP_N = 20
SHARES_FLOW_SCALE_MODES = ("linear", "sqrt", "log")
MOVEMENT_STYLE = {
    "New position": {
        "legend": "New positions",
        "marker_color": "#38bdf8",
        "marker_symbol": "diamond",
        "line_color": "rgba(56, 189, 248, 0.48)",
        "line_dash": "solid",
    },
    "Closed position": {
        "legend": "Closed positions",
        "marker_color": "#ef4444",
        "marker_symbol": "x",
        "line_color": "rgba(239, 68, 68, 0.50)",
        "line_dash": "dash",
    },
    "Increased": {
        "legend": "Increased",
        "marker_color": "#22c55e",
        "marker_symbol": "circle",
        "line_color": "rgba(34, 197, 94, 0.44)",
        "line_dash": "solid",
    },
    "Decreased": {
        "legend": "Decreased",
        "marker_color": "#f59e0b",
        "marker_symbol": "triangle-down",
        "line_color": "rgba(245, 158, 11, 0.48)",
        "line_dash": "dot",
    },
}


def _numeric_or_zero(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return float(value)


def _label_part(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _position_label(entry: dict) -> str:
    issuer_name = entry.get("issuer_name") or entry.get("position_key") or "Unknown position"
    put_call = _label_part(entry.get("put_call"))
    share_class = _label_part(entry.get("share_class"))
    suffix_parts = [part for part in (share_class, put_call) if part]
    if suffix_parts:
        return f"{issuer_name} ({' '.join(suffix_parts)})"
    return issuer_name


def _position_identifier(entry: dict) -> str:
    return entry.get("cusip") or entry.get("position_key") or "-"


def _movement_style(movement: str) -> dict[str, str]:
    return MOVEMENT_STYLE.get(movement, MOVEMENT_STYLE["Increased"])


def _is_option_entry(entry: dict) -> bool:
    """Return True when the diff entry represents a PUT/CALL option position."""
    put_call = entry.get("put_call")
    if put_call is None or pd.isna(put_call):
        return False
    return bool(str(put_call).strip())


def _limit_movements_by_side(
    movements: list[dict],
    *,
    top_n_buys: int,
    top_n_sells: int,
) -> list[dict]:
    buys = [movement for movement in movements if movement["side"] == "buy"]
    sells = [movement for movement in movements if movement["side"] == "sell"]

    def sort_key(item: dict) -> tuple[float, str]:
        return (abs(item["delta_shares"]), item["label"])

    return (
        sorted(buys, key=sort_key, reverse=True)[:top_n_buys]
        + sorted(sells, key=sort_key, reverse=True)[:top_n_sells]
    )


def scale_shares_flow_values(
    values: list[float],
    *,
    scale_mode: str = "linear",
    min_visible_pct: float = 0.0,
) -> list[float]:
    """Return display-only Sankey link weights; raw share values stay in hover data."""
    normalized_mode = scale_mode.lower()
    if normalized_mode not in SHARES_FLOW_SCALE_MODES:
        normalized_mode = "linear"

    if normalized_mode == "sqrt":
        scaled_values = [math.sqrt(value) for value in values]
    elif normalized_mode == "log":
        scaled_values = [math.log1p(value) for value in values]
    else:
        scaled_values = list(values)

    if not scaled_values or min_visible_pct <= 0:
        return scaled_values

    max_value = max(scaled_values)
    if max_value <= 0:
        return scaled_values

    floor_value = max_value * (min_visible_pct / 100)
    return [max(value, floor_value) if value > 0 else value for value in scaled_values]


def build_shares_flow_sankey_data(
    diff: dict,
    top_n: int = DEFAULT_SHARES_FLOW_TOP_N,
    *,
    top_n_buys: int | None = None,
    top_n_sells: int | None = None,
    include_options: bool = False,
) -> dict:
    """Build Plotly Sankey data for shares bought/sold between two quarters.

    Options (PUT/CALL) positions are excluded by default since their share counts
    represent contracts, not underlying shares, and would distort the linear
    thickness scaling. Set ``include_options=True`` to include them.
    """
    movements: list[dict] = []
    multiplier_probe_rows: list[dict] = []
    buy_limit = top_n if top_n_buys is None else top_n_buys
    sell_limit = top_n if top_n_sells is None else top_n_sells

    for entry in diff.get("increased", []):
        if not include_options and _is_option_entry(entry):
            continue
        delta_shares = _numeric_or_zero(entry.get("share_change"))
        if delta_shares <= 0:
            continue
        multiplier_probe_rows.append({"shares": entry.get("old_shares"), "value": entry.get("old_value_usd")})
        multiplier_probe_rows.append({"shares": entry.get("new_shares"), "value": entry.get("new_value_usd")})
        movements.append({
            "label": _position_label(entry),
            "identifier": _position_identifier(entry),
            "movement": "Increased",
            "source_label": BUY_NODE,
            "target_label": _position_label(entry),
            "value": delta_shares,
            "delta_shares": delta_shares,
            "old_shares": entry.get("old_shares"),
            "new_shares": entry.get("new_shares"),
            "value_change": entry.get("value_change"),
            "side": "buy",
            "link_color": "rgba(44, 160, 44, 0.45)",
        })

    for entry in diff.get("decreased", []):
        if not include_options and _is_option_entry(entry):
            continue
        delta_shares = _numeric_or_zero(entry.get("share_change"))
        if delta_shares >= 0:
            continue
        multiplier_probe_rows.append({"shares": entry.get("old_shares"), "value": entry.get("old_value_usd")})
        multiplier_probe_rows.append({"shares": entry.get("new_shares"), "value": entry.get("new_value_usd")})
        movements.append({
            "label": _position_label(entry),
            "identifier": _position_identifier(entry),
            "movement": "Decreased",
            "source_label": _position_label(entry),
            "target_label": SELL_NODE,
            "value": abs(delta_shares),
            "delta_shares": delta_shares,
            "old_shares": entry.get("old_shares"),
            "new_shares": entry.get("new_shares"),
            "value_change": entry.get("value_change"),
            "side": "sell",
            "link_color": "rgba(214, 39, 40, 0.45)",
        })

    for entry in diff.get("new_positions", []):
        if not include_options and _is_option_entry(entry):
            continue
        shares = _numeric_or_zero(entry.get("shares"))
        if shares <= 0:
            continue
        multiplier_probe_rows.append({"shares": entry.get("shares"), "value": entry.get("value_usd")})
        movements.append({
            "label": _position_label(entry),
            "identifier": _position_identifier(entry),
            "movement": "New position",
            "source_label": BUY_NODE,
            "target_label": _position_label(entry),
            "value": shares,
            "delta_shares": shares,
            "old_shares": 0,
            "new_shares": shares,
            "value_change": entry.get("value_usd"),
            "side": "buy",
            "link_color": "rgba(44, 160, 44, 0.38)",
        })

    for entry in diff.get("closed_positions", []):
        if not include_options and _is_option_entry(entry):
            continue
        shares = _numeric_or_zero(entry.get("shares"))
        if shares <= 0:
            continue
        multiplier_probe_rows.append({"shares": entry.get("shares"), "value": entry.get("value_usd")})
        movements.append({
            "label": _position_label(entry),
            "identifier": _position_identifier(entry),
            "movement": "Closed position",
            "source_label": _position_label(entry),
            "target_label": SELL_NODE,
            "value": shares,
            "delta_shares": -shares,
            "old_shares": shares,
            "new_shares": 0,
            "value_change": -_numeric_or_zero(entry.get("value_usd")) if entry.get("value_usd") is not None else None,
            "side": "sell",
            "link_color": "rgba(214, 39, 40, 0.38)",
        })

    movements = _limit_movements_by_side(
        movements,
        top_n_buys=buy_limit,
        top_n_sells=sell_limit,
    )

    node_labels: list[str] = []
    node_indexes: dict[str, int] = {}

    def node_index(label: str) -> int:
        if label not in node_indexes:
            node_indexes[label] = len(node_labels)
            node_labels.append(label)
        return node_indexes[label]

    node_index(BUY_NODE)
    node_index(SELL_NODE)

    sources = []
    targets = []
    values = []
    colors = []
    customdata = []
    multiplier_probe_df = pd.DataFrame(multiplier_probe_rows)
    value_multiplier = infer_value_multiplier_from_frame(
        multiplier_probe_df,
        value_col="value",
        shares_col="shares",
    )
    for movement in movements:
        sources.append(node_index(movement["source_label"]))
        targets.append(node_index(movement["target_label"]))
        values.append(movement["value"])
        colors.append(movement["link_color"])
        value_change = movement.get("value_change")
        customdata.append([
            movement["movement"],
            movement["identifier"],
            fmt_quantity(movement["old_shares"]),
            fmt_quantity(movement["new_shares"]),
            fmt_signed_quantity(movement["delta_shares"]),
            fmt_signed_value_dollars(None if value_change is None else _numeric_or_zero(value_change) * value_multiplier),
        ])

    node_colors = [
        "rgba(44, 160, 44, 0.85)" if label == BUY_NODE else
        "rgba(214, 39, 40, 0.85)" if label == SELL_NODE else
        "rgba(120, 130, 145, 0.55)"
        for label in node_labels
    ]

    return {
        "node": {"label": node_labels, "color": node_colors},
        "link": {
            "source": sources,
            "target": targets,
            "value": values,
            "color": colors,
            "customdata": customdata,
        },
        "movements": movements,
        "value_multiplier": value_multiplier if movements else 1,
    }


def build_shares_change_lane_data(
    diff: dict,
    top_n: int = DEFAULT_SHARES_FLOW_TOP_N,
    *,
    top_n_buys: int | None = None,
    top_n_sells: int | None = None,
    include_options: bool = False,
) -> pd.DataFrame:
    sankey_data = build_shares_flow_sankey_data(
        diff,
        top_n=top_n,
        top_n_buys=top_n_buys,
        top_n_sells=top_n_sells,
        include_options=include_options,
    )
    rows = [
        {
            "Position": movement["label"],
            "Movement": movement["movement"],
            "Movement Label": _movement_style(movement["movement"])["legend"],
            "Marker Color": _movement_style(movement["movement"])["marker_color"],
            "Marker Symbol": _movement_style(movement["movement"])["marker_symbol"],
            "Line Color": _movement_style(movement["movement"])["line_color"],
            "Line Dash": _movement_style(movement["movement"])["line_dash"],
            "Previous Shares": _numeric_or_zero(movement.get("old_shares")),
            "New Shares": _numeric_or_zero(movement.get("new_shares")),
            "Delta Shares": movement["delta_shares"],
            "Sort Value": abs(movement["delta_shares"]),
        }
        for movement in sankey_data["movements"]
    ]
    return pd.DataFrame(rows)


def build_transition_summary_df(transitions: list[dict]) -> pd.DataFrame:
    if not transitions:
        return pd.DataFrame()

    summary_df = pd.DataFrame([
        {
            "Transition": f"{item['from_filing_date']} → {item['to_filing_date']}",
            "Order": index,
            "To Filing Date": item["to_filing_date"],
            "New": item["new_count"],
            "Closed": item["closed_count"],
            "Increased": item["increased_count"],
            "Decreased": item["decreased_count"],
        }
        for index, item in enumerate(transitions)
    ])
    summary_df["To Filing Date Dt"] = pd.to_datetime(summary_df["To Filing Date"])
    summary_df["Changed Positions"] = summary_df[
        ["New", "Closed", "Increased", "Decreased"]
    ].sum(axis=1)
    return summary_df


def render_portfolio_timeline_charts(
    history_df: pd.DataFrame,
    fund: str,
    *,
    key_prefix: str = "portfolio_timeline",
):
    value_col = "Portfolio Value (USD)" if "Portfolio Value (USD)" in history_df.columns else "Portfolio Value ($000s)"
    has_portfolio_values = history_df[value_col].notna().any()

    charts_col1, charts_col2 = st.columns(2)
    with charts_col1:
        positions_fig = px.line(
            history_df,
            x="Filing Date Dt",
            y="Normalized Positions",
            markers=True,
            hover_name="Label",
            title=f"Normalized positions by quarter — {fund}",
        )
        positions_fig.update_xaxes(title="Filing date")
        positions_fig.update_yaxes(title="Normalized positions")
        st.plotly_chart(
            positions_fig,
            use_container_width=True,
            key=f"{key_prefix}_positions",
        )

    with charts_col2:
        if has_portfolio_values:
            value_fig = px.line(
                history_df,
                x="Filing Date Dt",
                y=value_col,
                markers=True,
                hover_name="Label",
                title=f"Portfolio value by quarter — {fund}",
            )
            value_fig.update_xaxes(title="Filing date")
            value_fig.update_yaxes(title="Value (USD)")
            st.plotly_chart(
                value_fig,
                use_container_width=True,
                key=f"{key_prefix}_value",
            )
        else:
            st.info("Portfolio values are not available for this fund in the current DB.")


def render_transition_counts_chart(
    transitions: list[dict],
    fund: str,
    *,
    title: str | None = None,
    key: str = "transition_counts",
):
    transition_counts_df = build_transition_summary_df(transitions)
    if transition_counts_df.empty:
        return

    melted_counts = transition_counts_df.melt(
        id_vars=["Transition", "Order"],
        value_vars=["New", "Closed", "Increased", "Decreased"],
        var_name="Category",
        value_name="Positions",
    )
    melted_counts = melted_counts.sort_values(["Order", "Category"])
    transition_fig = px.bar(
        melted_counts,
        x="Transition",
        y="Positions",
        color="Category",
        barmode="group",
        title=title or f"Quarter-over-quarter changes — {fund}",
    )
    transition_fig.update_layout(xaxis_tickangle=-30)
    st.plotly_chart(transition_fig, use_container_width=True, key=key)


def render_shares_flow_sankey(
    diff: dict,
    fund: str,
    *,
    top_n: int = DEFAULT_SHARES_FLOW_TOP_N,
    top_n_buys: int | None = None,
    top_n_sells: int | None = None,
    scale_mode: str = "linear",
    min_visible_pct: float = 0.0,
):
    sankey_data = build_shares_flow_sankey_data(
        diff,
        top_n=top_n,
        top_n_buys=top_n_buys,
        top_n_sells=top_n_sells,
    )
    if not sankey_data["movements"]:
        st.info("No non-zero share movements are available for the selected quarters.")
        return

    display_values = scale_shares_flow_values(
        sankey_data["link"]["value"],
        scale_mode=scale_mode,
        min_visible_pct=min_visible_pct,
    )
    normalized_scale_mode = scale_mode.lower()
    if normalized_scale_mode not in SHARES_FLOW_SCALE_MODES:
        normalized_scale_mode = "linear"

    st.caption(
        f"Line thickness uses {normalized_scale_mode} display scaling"
        f" with a {min_visible_pct:g}% visibility floor. "
        "Hover labels show raw share deltas and auto-normalized delta values "
        f"(value multiplier x{sankey_data['value_multiplier']})."
    )

    sankey_fig = go.Figure(
        data=[
            go.Sankey(
                arrangement="snap",
                node={
                    "pad": 18,
                    "thickness": 16,
                    "line": {"color": "rgba(60, 65, 75, 0.35)", "width": 0.5},
                    "label": sankey_data["node"]["label"],
                    "color": sankey_data["node"]["color"],
                },
                link={
                    "source": sankey_data["link"]["source"],
                    "target": sankey_data["link"]["target"],
                    "value": display_values,
                    "color": sankey_data["link"]["color"],
                    "customdata": sankey_data["link"]["customdata"],
                    "hovertemplate": (
                        "Movement: %{customdata[0]}<br>"
                        "Identifier: %{customdata[1]}<br>"
                        "Old shares: %{customdata[2]}<br>"
                        "New shares: %{customdata[3]}<br>"
                        "Delta shares: %{customdata[4]}<br>"
                        "Delta value: %{customdata[5]}<br>"
                        "Displayed thickness: %{value:,.2f}<extra></extra>"
                    ),
                },
            )
        ]
    )
    sankey_fig.update_layout(
        title=f"Shares bought/sold by position — {fund}",
        font={"size": 12},
        height=620,
        margin={"l": 8, "r": 8, "t": 56, "b": 8},
    )
    sankey_key = (
        f"shares_flow_sankey_{fund}_{top_n_buys}_{top_n_sells}_"
        f"{normalized_scale_mode}_{min_visible_pct:g}_{len(display_values)}_"
        f"{sum(display_values):.6g}"
    )
    st.plotly_chart(sankey_fig, use_container_width=True, key=sankey_key)


def render_shares_change_lanes(
    diff: dict,
    fund: str,
    *,
    top_n: int = DEFAULT_SHARES_FLOW_TOP_N,
    top_n_buys: int | None = None,
    top_n_sells: int | None = None,
):
    lanes_df = build_shares_change_lane_data(
        diff,
        top_n=top_n,
        top_n_buys=top_n_buys,
        top_n_sells=top_n_sells,
    )
    if lanes_df.empty:
        return

    lanes_df = lanes_df.sort_values(["Sort Value", "Position"], ascending=[True, False])
    fig = go.Figure()
    for _, row in lanes_df.iterrows():
        fig.add_trace(
            go.Scatter(
                x=[row["Previous Shares"], row["New Shares"]],
                y=[row["Position"], row["Position"]],
                mode="lines",
                line={"color": row["Line Color"], "width": 5, "dash": row["Line Dash"]},
                hoverinfo="skip",
                showlegend=False,
            )
        )

    fig.add_trace(
        go.Scatter(
            name="Previous quarter",
            y=lanes_df["Position"],
            x=lanes_df["Previous Shares"],
            mode="markers",
            marker={
                "color": "rgba(14, 18, 26, 0.85)",
                "line": {"color": "rgba(155, 165, 180, 0.95)", "width": 2},
                "size": 11,
                "symbol": "circle-open",
            },
            customdata=lanes_df[["Movement", "Delta Shares", "New Shares"]],
            hovertemplate=(
                "Position: %{y}<br>"
                "Movement: %{customdata[0]}<br>"
                "Previous shares: %{x:,.0f}<br>"
                "New shares: %{customdata[2]:,.0f}<br>"
                "Delta shares: %{customdata[1]:+,.0f}<extra></extra>"
            ),
        )
    )
    for movement, style in MOVEMENT_STYLE.items():
        movement_df = lanes_df[lanes_df["Movement"] == movement]
        if movement_df.empty:
            continue
        fig.add_trace(
            go.Scatter(
                name=style["legend"],
                y=movement_df["Position"],
                x=movement_df["New Shares"],
                mode="markers+text",
                marker={
                    "color": style["marker_color"],
                    "size": 13,
                    "symbol": style["marker_symbol"],
                    "line": {"color": "rgba(255, 255, 255, 0.55)", "width": 1},
                },
                text=[fmt_signed_quantity(delta) for delta in movement_df["Delta Shares"]],
                textposition="middle right",
                textfont={"size": 10, "color": "rgba(220, 225, 232, 0.92)"},
                customdata=movement_df[["Movement", "Delta Shares", "Previous Shares"]],
                hovertemplate=(
                    "Position: %{y}<br>"
                    "Movement: %{customdata[0]}<br>"
                    "Previous shares: %{customdata[2]:,.0f}<br>"
                    "New shares: %{x:,.0f}<br>"
                    "Delta shares: %{customdata[1]:+,.0f}<extra></extra>"
                ),
            )
        )
    fig.update_layout(
        title=f"Previous to new shares by position - {fund}",
        font={"size": 12},
        height=max(460, min(980, 150 + len(lanes_df) * 28)),
        margin={"l": 8, "r": 96, "t": 64, "b": 42},
        xaxis_title="Shares",
        yaxis_title="",
        hovermode="closest",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    fig.update_xaxes(
        rangemode="tozero",
        gridcolor="rgba(130, 140, 155, 0.18)",
        zeroline=True,
        zerolinecolor="rgba(180, 190, 205, 0.45)",
    )
    fig.update_yaxes(
        categoryorder="array",
        categoryarray=lanes_df["Position"].tolist(),
        gridcolor="rgba(130, 140, 155, 0.10)",
    )
    st.caption(
        "Dumbbell view: open grey dots are previous-quarter shares; current-quarter markers distinguish "
        "new positions, closed positions, increases, and decreases. Labels show raw share delta."
    )
    lanes_key = (
        f"shares_change_lanes_{fund}_{top_n_buys}_{top_n_sells}_"
        f"{len(lanes_df)}_{lanes_df['Sort Value'].sum():.6g}"
    )
    st.plotly_chart(fig, use_container_width=True, key=lanes_key)