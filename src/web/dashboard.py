"""
F8 F13 Screener — Streamlit Dashboard
Run locally:  streamlit run src/web/dashboard.py
"""
import sys
from html import escape
from pathlib import Path
import re
from typing import Any, TypeVar

import streamlit as st

# Ensure `src.*` imports work whether Streamlit is launched from repo root or src/web.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.web.data_service import (
    DB_PATH,
    fund_has_db_holdings,
    get_fund_options,
    initialize_dashboard_storage,
    load_accessions_for_fund,
    load_fund_history,
    load_fund_instrument_history,
    load_normalized_positions_map,
    query,
    table_exists,
)
from src.web.pages.consensus_trends import render_consensus_trends_page
from src.web.pages.fund_analysis import render_fund_analysis_page
from src.web.pages.holdings_search import render_holdings_search_page
from src.web.pages.overview import render_overview_page

st.set_page_config(
    page_title="F8 13F Screener",
    page_icon="📊",
    layout="wide",
)


SelectionT = TypeVar("SelectionT")


def render_top_bar(page_title: str) -> Any:
    safe_title = escape(page_title)
    top_bar_key = f"f8_top_bar_{re.sub(r'[^0-9a-z]+', '_', page_title.lower()).strip('_')}"
    top_bar_class = f"st-key-{top_bar_key}"
    top_padding = {
        "Overview": "9rem",
        "Fund Analysis": "10rem",
        "Consensus Trends": "10rem",
        "Holdings Search": "6.5rem",
    }.get(page_title, "5.2rem")
    st.markdown(
        f"""
        <style>
            .block-container {{
                padding-top: {top_padding};
            }}
            .{top_bar_class} {{
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                z-index: 999999;
                overflow: visible;
                padding: 0.38rem 1.5rem 0.42rem;
                border-bottom: 1px solid rgba(250, 250, 250, 0.12);
                background: rgba(14, 17, 23, 0.97);
                backdrop-filter: blur(10px);
                box-shadow: 0 8px 22px rgba(0, 0, 0, 0.32);
            }}
            .{top_bar_class} .f8-top-bar__title-row {{
                align-items: baseline;
                display: flex;
                gap: 0.75rem;
                margin-bottom: 0.05rem;
            }}
            .{top_bar_class} .f8-top-bar__eyebrow {{
                color: rgba(250, 250, 250, 0.62);
                font-size: 0.6rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                line-height: 1;
                text-transform: uppercase;
            }}
            .{top_bar_class} .f8-top-bar__title {{
                color: rgb(250, 250, 250);
                font-size: 0.98rem;
                font-weight: 700;
                line-height: 1.2;
            }}
            .{top_bar_class} [data-testid="stVerticalBlock"] {{
                gap: 0.18rem;
            }}
            .{top_bar_class} [data-testid="stHorizontalBlock"] {{
                flex-wrap: nowrap !important;
                gap: 0.75rem;
            }}
            .{top_bar_class} [data-testid="column"] {{
                flex: 1 1 0 !important;
                min-width: 0 !important;
                padding-top: 0 !important;
            }}
            .{top_bar_class} [data-testid="stMetric"] {{
                background: transparent;
                border: 0;
                padding: 0;
            }}
            .{top_bar_class} [data-testid="stMetric"] > div {{
                gap: 0.05rem;
            }}
            .{top_bar_class} [data-testid="stMetricLabel"] p,
            .{top_bar_class} [data-testid="stCaptionContainer"] p,
            .{top_bar_class} label p {{
                font-size: 0.64rem;
                line-height: 1.15;
            }}
            .{top_bar_class} [data-testid="stMetricValue"] {{
                font-size: 1rem;
                line-height: 1.05;
            }}
            .{top_bar_class} [data-testid="stMetricValue"] > div {{
                font-size: 1rem;
                line-height: 1.05;
            }}
            .{top_bar_class} .f8-compact-stats {{
                display: grid;
                gap: 0.7rem;
                grid-template-columns: repeat(var(--f8-stat-count, 4), minmax(0, 1fr));
                margin-top: 0.12rem;
            }}
            .{top_bar_class} .f8-compact-stat {{
                min-width: 0;
            }}
            .{top_bar_class} .f8-compact-stat__label {{
                color: rgba(250, 250, 250, 0.68);
                font-size: 0.66rem;
                font-weight: 600;
                line-height: 1.1;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .{top_bar_class} .f8-compact-stat__value {{
                color: rgb(250, 250, 250);
                font-size: 1.05rem;
                font-weight: 700;
                line-height: 1.16;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .{top_bar_class} .f8-top-bar-message {{
                border-radius: 0.35rem;
                font-size: 0.72rem;
                font-weight: 600;
                line-height: 1.2;
                margin-top: 0.18rem;
                padding: 0.24rem 0.55rem;
            }}
            .{top_bar_class} .f8-top-bar-message--success {{
                background: rgba(34, 197, 94, 0.18);
                color: rgb(86, 255, 144);
            }}
            .{top_bar_class} .f8-top-bar-message--warning {{
                background: rgba(250, 204, 21, 0.18);
                color: rgb(253, 224, 71);
            }}
            .{top_bar_class} .f8-top-bar-links {{
                color: rgba(250, 250, 250, 0.62);
                font-size: 0.66rem;
                line-height: 1.15;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .{top_bar_class} .f8-top-bar-links a {{
                color: rgb(96, 165, 250);
                margin-left: 0.35rem;
                text-decoration: none;
            }}
            .{top_bar_class} [data-testid="stAlert"] {{
                margin-top: 0.15rem;
                min-height: 0;
                padding: 0.25rem 0.65rem;
            }}
            .{top_bar_class} [data-testid="stAlert"] p {{
                font-size: 0.68rem;
                line-height: 1.15;
            }}
            .{top_bar_class} .stSelectbox,
            .{top_bar_class} .stMultiSelect,
            .{top_bar_class} .stSlider,
            .{top_bar_class} .stTextInput {{
                margin-bottom: 0;
            }}
            .{top_bar_class} [data-baseweb="select"] > div,
            .{top_bar_class} [data-baseweb="input"] {{
                min-height: 2rem;
            }}
            .{top_bar_class} [data-testid="stSlider"] {{
                padding-top: 0;
            }}
            .{top_bar_class} [data-testid="stSlider"] > div {{
                padding-top: 0.05rem;
            }}
            @media (max-width: 640px) {{
                .block-container {{
                    padding-top: calc({top_padding} + 2rem);
                }}
                .{top_bar_class} {{
                    padding-left: 1rem;
                    padding-right: 1rem;
                }}
                .{top_bar_class} .f8-top-bar__title-row {{
                    display: block;
                }}
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    top_bar = st.container(key=top_bar_key)
    with top_bar:
        st.markdown(
            f"""
            <div class="f8-top-bar__title-row">
                <span class="f8-top-bar__eyebrow">F8 13F Screener</span>
                <span class="f8-top-bar__title">{safe_title}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    return top_bar


def require_selection(value: SelectionT | None, empty_message: str) -> SelectionT:
    if value is None:
        st.info(empty_message)
        st.stop()
    return value


def render_overview(top_bar):
    render_overview_page(query, table_exists, top_bar=top_bar)


def render_fund_analysis(top_bar):
    render_fund_analysis_page(
        get_fund_options,
        require_selection,
        fund_has_db_holdings,
        load_accessions_for_fund,
        load_fund_history,
        load_normalized_positions_map,
        load_fund_instrument_history,
        query,
        top_bar=top_bar,
    )


def render_consensus_trends(top_bar):
    render_consensus_trends_page(query, get_fund_options, top_bar=top_bar)


def render_holdings_search(top_bar):
    render_holdings_search_page(query, top_bar=top_bar)


PAGE_RENDERERS = {
    "Overview": render_overview,
    "Fund Analysis": render_fund_analysis,
    "Consensus Trends": render_consensus_trends,
    "Holdings Search": render_holdings_search,
}


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.title("📊 F8 13F Screener")
pending_page = st.session_state.pop("pending_sidebar_page", None)
if pending_page in PAGE_RENDERERS:
    st.session_state["sidebar_page"] = pending_page
page = st.sidebar.radio(
    "Section",
    list(PAGE_RENDERERS),
    key="sidebar_page",
)
st.sidebar.markdown("---")
_, dashboard_reader_path, dashboard_snapshot_warning = initialize_dashboard_storage()
st.sidebar.caption(f"DB live: `{DB_PATH}`")
st.sidebar.caption(f"Read path: `{dashboard_reader_path}`")
if dashboard_snapshot_warning:
    st.sidebar.warning(dashboard_snapshot_warning)
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()

top_bar = render_top_bar(page)
PAGE_RENDERERS[page](top_bar)
