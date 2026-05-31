"""Streamlit chart renderers for dashboard pages."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.web.formatting import fmt_quantity, fmt_signed_quantity


BUY_NODE = "Bought shares"
SELL_NODE = "Sold shares"
DEFAULT_SHARES_FLOW_TOP_N = 20


def _numeric_or_zero(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return float(value)


def _position_label(entry: dict) -> str:
    issuer_name = entry.get("issuer_name") or entry.get("position_key") or "Unknown position"
    put_call = entry.get("put_call")
    share_class = entry.get("share_class")
    suffix_parts = [part for part in (share_class, put_call) if part]
    if suffix_parts:
        return f"{issuer_name} ({' '.join(suffix_parts)})"
    return issuer_name


def _position_identifier(entry: dict) -> str:
    return entry.get("cusip") or entry.get("position_key") or "-"


def build_shares_flow_sankey_data(diff: dict, top_n: int = DEFAULT_SHARES_FLOW_TOP_N) -> dict:
    """Build Plotly Sankey data for shares bought/sold between two quarters."""
    movements: list[dict] = []

    for entry in diff.get("increased", []):
        delta_shares = _numeric_or_zero(entry.get("share_change"))
        if delta_shares <= 0:
            continue
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
            "link_color": "rgba(44, 160, 44, 0.45)",
        })

    for entry in diff.get("decreased", []):
        delta_shares = _numeric_or_zero(entry.get("share_change"))
        if delta_shares >= 0:
            continue
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
            "link_color": "rgba(214, 39, 40, 0.45)",
        })

    for entry in diff.get("new_positions", []):
        shares = _numeric_or_zero(entry.get("shares"))
        if shares <= 0:
            continue
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
            "link_color": "rgba(44, 160, 44, 0.38)",
        })

    for entry in diff.get("closed_positions", []):
        shares = _numeric_or_zero(entry.get("shares"))
        if shares <= 0:
            continue
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
            "link_color": "rgba(214, 39, 40, 0.38)",
        })

    movements = sorted(
        movements,
        key=lambda item: (abs(item["delta_shares"]), item["label"]),
        reverse=True,
    )[:top_n]

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
    for movement in movements:
        sources.append(node_index(movement["source_label"]))
        targets.append(node_index(movement["target_label"]))
        values.append(movement["value"])
        colors.append(movement["link_color"])
        customdata.append([
            movement["movement"],
            movement["identifier"],
            fmt_quantity(movement["old_shares"]),
            fmt_quantity(movement["new_shares"]),
            fmt_signed_quantity(movement["delta_shares"]),
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
    }


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


def render_portfolio_timeline_charts(history_df: pd.DataFrame, fund: str):
    has_portfolio_values = history_df["Portfolio Value ($000s)"].notna().any()

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
        st.plotly_chart(positions_fig, use_container_width=True)

    with charts_col2:
        if has_portfolio_values:
            value_fig = px.line(
                history_df,
                x="Filing Date Dt",
                y="Portfolio Value ($000s)",
                markers=True,
                hover_name="Label",
                title=f"Portfolio value by quarter — {fund}",
            )
            value_fig.update_xaxes(title="Filing date")
            value_fig.update_yaxes(title="Value ($000s)")
            st.plotly_chart(value_fig, use_container_width=True)
        else:
            st.info("Portfolio values are not available for this fund in the current DB.")


def render_transition_counts_chart(
    transitions: list[dict],
    fund: str,
    *,
    title: str | None = None,
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
    st.plotly_chart(transition_fig, use_container_width=True)


def render_shares_flow_sankey(
    diff: dict,
    fund: str,
    *,
    top_n: int = DEFAULT_SHARES_FLOW_TOP_N,
):
    sankey_data = build_shares_flow_sankey_data(diff, top_n=top_n)
    if not sankey_data["movements"]:
        st.info("No non-zero share movements are available for the selected quarters.")
        return

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
                    "value": sankey_data["link"]["value"],
                    "color": sankey_data["link"]["color"],
                    "customdata": sankey_data["link"]["customdata"],
                    "hovertemplate": (
                        "Movement: %{customdata[0]}<br>"
                        "Identifier: %{customdata[1]}<br>"
                        "Old shares: %{customdata[2]}<br>"
                        "New shares: %{customdata[3]}<br>"
                        "Delta shares: %{customdata[4]}<br>"
                        "Flow width: %{value:,.0f} shares<extra></extra>"
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
    st.plotly_chart(sankey_fig, use_container_width=True)