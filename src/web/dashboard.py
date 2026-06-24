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
        "Overview": "5.25rem",
        "Fund Analysis": "6.5rem",
        "Consensus Trends": "8rem",
        "Holdings Search": "7.6rem",
    }.get(page_title, "6rem")
    st.markdown(
        f"""
        <style>
            .block-container {{
                padding-top: {top_padding};
            }}
            [data-testid="stSidebar"] > div:first-child {{
                padding-top: {top_padding};
            }}
            [class*="st-key-f8_top_bar_"] {{
                display: none;
            }}
            .{top_bar_class} {{
                display: block;
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                z-index: 999999;
                padding: 0.48rem 1.4rem 0.58rem;
                border-bottom: 1px solid rgba(250, 250, 250, 0.12);
                background: rgba(14, 17, 23, 0.97);
                backdrop-filter: blur(10px);
                box-shadow: 0 8px 22px rgba(0, 0, 0, 0.32);
            }}
            .{top_bar_class} [data-testid="stVerticalBlock"] {{
                gap: 0.22rem;
            }}
            .{top_bar_class} [data-testid="element-container"]:has(.f8-top-bar__title-row) {{
                flex: 0 0 auto;
                height: 1.45rem;
                margin: 0 0 0.14rem;
            }}
            .{top_bar_class} [data-testid="stHorizontalBlock"] {{
                align-items: end;
                flex-wrap: nowrap;
                gap: 0.9rem;
            }}
            .{top_bar_class} [data-testid="column"],
            .{top_bar_class} [data-testid="stColumn"] {{
                min-width: 0;
                padding-top: 0 !important;
            }}
            .{top_bar_class} [data-testid="stMarkdownContainer"] p,
            .{top_bar_class} [data-testid="stCaptionContainer"] p {{
                margin: 0;
            }}
            .{top_bar_class} .f8-top-bar__title-row {{
                align-items: baseline;
                display: flex;
                gap: 0.8rem;
                height: 1.45rem;
                margin: 0;
                min-height: 1.42rem;
                min-width: 0;
            }}
            .f8-top-bar__eyebrow {{
                color: rgba(250, 250, 250, 0.62);
                font-size: 0.64rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                line-height: 1;
                text-transform: uppercase;
                white-space: nowrap;
            }}
            .f8-top-bar__title {{
                color: rgb(250, 250, 250);
                font-size: 1.12rem;
                font-weight: 700;
                line-height: 1.2;
                min-width: 0;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .{top_bar_class} [data-testid="stCaptionContainer"] p,
            .{top_bar_class} label p {{
                font-size: 0.72rem;
                line-height: 1.15;
                margin: 0;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .{top_bar_class} label {{
                min-height: 0.95rem;
                padding-bottom: 0.12rem;
            }}
            .{top_bar_class} [data-baseweb="select"] > div,
            .{top_bar_class} [data-baseweb="input"] {{
                min-height: 2.05rem;
            }}
            .{top_bar_class} [data-baseweb="select"] > div {{
                border-radius: 0.46rem;
            }}
            .{top_bar_class} [data-baseweb="select"] span,
            .{top_bar_class} [data-baseweb="input"] input {{
                font-size: 0.86rem;
                line-height: 1.15;
            }}
            .{top_bar_class} .f8-top-bar-note {{
                color: rgba(250, 250, 250, 0.64);
                font-size: 0.72rem;
                font-weight: 650;
                line-height: 1.25;
                min-width: 0;
            }}
            .{top_bar_class} [class*="st-key-f8_toolbar_row_"] {{
                margin-top: 1.55rem;
                min-width: 0;
            }}
            .{top_bar_class} [class*="st-key-f8_toolbar_row_"] [data-testid="stHorizontalBlock"] {{
                align-items: end;
                column-gap: 1rem;
                row-gap: 0.4rem;
            }}
            .{top_bar_class} .st-key-f8_toolbar_row_holdings [data-testid="stHorizontalBlock"] {{
                display: grid;
                grid-template-columns: minmax(22rem, 2.7fr) minmax(18rem, 1fr);
            }}
            .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-testid="stHorizontalBlock"] {{
                display: grid;
                grid-template-columns: minmax(9rem, 0.8fr) minmax(8rem, 0.72fr) minmax(8rem, 0.72fr) minmax(18rem, 2.7fr) minmax(16rem, 1.7fr);
            }}
            .{top_bar_class} .st-key-f8_toolbar_row_holdings [data-testid="column"],
            .{top_bar_class} .st-key-f8_toolbar_row_holdings [data-testid="stColumn"],
            .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-testid="column"],
            .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-testid="stColumn"] {{
                flex: unset !important;
                min-width: 0 !important;
                width: 100% !important;
            }}
            .{top_bar_class} .st-key-f8_toolbar_row_holdings [data-baseweb="select"],
            .{top_bar_class} .st-key-f8_toolbar_row_holdings [data-baseweb="input"],
            .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-baseweb="select"],
            .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-baseweb="input"] {{
                width: 100%;
            }}
            .{top_bar_class} .f8-compact-stats {{
                display: grid;
                gap: 0.9rem;
                grid-template-columns: repeat(var(--f8-stat-count, 4), minmax(0, 1fr));
            }}
            .{top_bar_class} .f8-compact-stat {{
                min-width: 0;
            }}
            .{top_bar_class} .f8-compact-stat__label {{
                color: rgba(250, 250, 250, 0.66);
                font-size: 0.68rem;
                font-weight: 700;
                line-height: 1.1;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .{top_bar_class} .f8-compact-stat__value {{
                color: rgb(250, 250, 250);
                font-size: 1.08rem;
                font-weight: 750;
                line-height: 1.18;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .{top_bar_class} .f8-top-bar-message {{
                border-radius: 0.4rem;
                font-size: 0.72rem;
                font-weight: 650;
                line-height: 1.15;
                padding: 0.24rem 0.6rem;
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
                font-size: 0.72rem;
                line-height: 1.2;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: normal;
            }}
            .{top_bar_class} .f8-top-bar-links a {{
                color: rgb(96, 165, 250);
                display: inline-block;
                margin-left: 0.45rem;
                text-decoration: none;
                white-space: nowrap;
            }}
            .{top_bar_class} .f8-top-bar-spacer {{
                display: none;
            }}
            @media (max-width: 1200px) {{
                .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-testid="stHorizontalBlock"] {{
                    grid-template-columns: repeat(3, minmax(8rem, 1fr)) minmax(18rem, 2fr);
                }}
                .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-testid="column"]:last-child,
                .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-testid="stColumn"]:last-child {{
                    grid-column: 1 / -1;
                }}
            }}
            @media (max-width: 640px) {{
                .block-container {{
                    padding-top: calc({top_padding} + 4.6rem);
                }}
                .{top_bar_class} {{
                    padding-left: 1rem;
                    padding-right: 1rem;
                }}
                .{top_bar_class} [data-testid="stHorizontalBlock"] {{
                    flex-wrap: wrap;
                }}
                .{top_bar_class} .st-key-f8_toolbar_row_holdings [data-testid="stHorizontalBlock"],
                .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-testid="stHorizontalBlock"] {{
                    grid-template-columns: 1fr;
                }}
                .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-testid="stHorizontalBlock"] {{
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }}
                .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-testid="column"]:nth-child(4),
                .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-testid="column"]:nth-child(5),
                .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-testid="stColumn"]:nth-child(4),
                .{top_bar_class} .st-key-f8_toolbar_row_consensus [data-testid="stColumn"]:nth-child(5) {{
                    grid-column: 1 / -1;
                }}
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    top_bar = st.container(key=top_bar_key)
    top_bar.empty()
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
