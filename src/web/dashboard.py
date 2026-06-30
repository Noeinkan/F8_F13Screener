"""
F8 F13 Screener — Streamlit Dashboard
Run locally:  streamlit run src/web/dashboard.py
"""
import sys
from html import escape
from pathlib import Path
import re
from typing import Any, TypeVar

SelectionT = TypeVar("SelectionT")

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


def inject_global_theme() -> None:
    st.markdown(
        """
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            :root {
                --f8-bg: #f7f2e8;
                --f8-surface: #ffffff;
                --f8-ink: #1a1f2e;
                --f8-muted: #5b6478;
                --f8-accent: #1e3a8a;
                --f8-accent-2: #2d64d2;
                --f8-border: rgba(0, 0, 0, 0.08);
                --f8-header-height: 3.25rem;
                --f8-sidebar-width: 21rem;
            }
            html, body, [data-testid="stAppViewContainer"] {
                color: var(--f8-ink);
                font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
            }
            [data-testid="stAppViewContainer"] > .main {
                background: linear-gradient(180deg, #f7f2e8 0%, #f2eadf 48%, #ede3d3 100%);
            }
            [data-testid="stHeader"] {
                background: transparent;
            }
            [data-testid="stSidebar"] {
                background-color: var(--f8-bg) !important;
                border-right: 1px solid var(--f8-border);
                z-index: 1000000;
            }
            [data-testid="stSidebar"] > div:first-child {
                padding-top: 1rem;
            }
            .f8-app-header {
                align-items: center;
                background: var(--f8-accent);
                border-bottom: 1px solid rgba(255, 255, 255, 0.12);
                box-shadow: 0 2px 10px rgba(30, 58, 138, 0.18);
                box-sizing: border-box;
                display: flex;
                height: var(--f8-header-height);
                left: var(--f8-sidebar-width);
                padding: 0 1.4rem;
                position: fixed;
                right: 0;
                top: 0;
                z-index: 999999;
            }
            [data-testid="stSidebar"][aria-expanded="false"] ~ [data-testid="stAppViewContainer"] .f8-app-header {
                left: 0;
            }
            .f8-app-header .f8-top-bar__header-row {
                align-items: baseline;
                display: flex;
                gap: 0.75rem;
                margin: 0;
                min-width: 0;
            }
            .f8-app-header .f8-top-bar__brand {
                color: #ffffff;
                font-size: 1.05rem;
                font-weight: 700;
                line-height: 1.2;
                white-space: nowrap;
            }
            .f8-app-header .f8-top-bar__page-label {
                color: rgba(255, 255, 255, 0.72);
                font-size: 0.78rem;
                font-weight: 600;
                line-height: 1.2;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
                margin-bottom: 0.35rem;
            }
            .f8-sidebar-section {
                color: var(--f8-muted);
                font-size: 0.7rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                margin: 0 0 0.55rem;
                text-transform: uppercase;
            }
            .f8-sidebar-meta {
                color: var(--f8-muted);
                font-size: 0.72rem;
                line-height: 1.35;
                margin: 0.2rem 0;
                word-break: break-all;
            }
            .f8-sidebar-footer {
                color: var(--f8-muted);
                font-size: 0.72rem;
                line-height: 1.3;
                margin: 1.25rem 0 0;
            }
            [data-testid="stSidebar"] .stButton > button {
                background: var(--f8-accent);
                border: 1px solid var(--f8-accent);
                border-radius: 0.5rem;
                color: #ffffff;
                font-weight: 600;
                width: 100%;
            }
            [data-testid="stSidebar"] .stButton > button:hover {
                background: #182f6e;
                border-color: #182f6e;
                color: #ffffff;
            }
            [data-testid="stSidebar"] [data-testid="stRadio"] label p {
                color: var(--f8-ink);
                font-size: 0.92rem;
            }
            [data-testid="stSidebar"] [data-testid="stRadio"] label[data-checked="true"] p {
                color: var(--f8-accent);
                font-weight: 700;
            }
            .block-container {
                padding-top: var(--f8-header-height);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_top_bar(page_title: str) -> Any:
    safe_title = escape(page_title)
    top_bar_key = f"f8_top_bar_{re.sub(r'[^0-9a-z]+', '_', page_title.lower()).strip('_')}"
    top_bar_class = f"st-key-{top_bar_key}"
    st.markdown(
        f"""
        <div class="f8-app-header">
            <div class="f8-top-bar__header-row">
                <span class="f8-top-bar__brand">F8 13F Screener</span>
                <span class="f8-top-bar__page-label">{safe_title}</span>
            </div>
        </div>
        <style>
            [class*="st-key-f8_top_bar_"] {{
                display: none;
            }}
            .{top_bar_class} {{
                background: var(--f8-accent);
                border-bottom: 1px solid rgba(255, 255, 255, 0.12);
                display: block;
                margin: 0 -1rem 0.75rem;
                padding: 0.55rem 1.4rem 0.65rem;
                position: relative;
                width: calc(100% + 2rem);
            }}
            .{top_bar_class} [data-testid="stVerticalBlock"] {{
                gap: 0.35rem;
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
            .{top_bar_class} [data-testid="stCaptionContainer"] p,
            .{top_bar_class} label p {{
                color: rgba(255, 255, 255, 0.82);
                font-size: 0.72rem;
                line-height: 1.15;
                margin: 0;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .{top_bar_class} label {{
                color: rgba(255, 255, 255, 0.82);
                min-height: 0.95rem;
                padding-bottom: 0.12rem;
            }}
            .{top_bar_class} [data-baseweb="select"] > div,
            .{top_bar_class} [data-baseweb="input"] {{
                background: rgba(255, 255, 255, 0.96);
                min-height: 2.05rem;
            }}
            .{top_bar_class} [data-baseweb="select"] > div {{
                border-radius: 0.46rem;
            }}
            .{top_bar_class} [data-baseweb="select"] span,
            .{top_bar_class} [data-baseweb="input"] input {{
                color: var(--f8-ink);
                font-size: 0.86rem;
                line-height: 1.15;
            }}
            .{top_bar_class} .f8-top-bar-note {{
                color: rgba(255, 255, 255, 0.78);
                font-size: 0.72rem;
                font-weight: 650;
                line-height: 1.25;
                min-width: 0;
            }}
            .{top_bar_class} [class*="st-key-f8_toolbar_row_"] {{
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
                color: rgba(255, 255, 255, 0.72);
                font-size: 0.68rem;
                font-weight: 700;
                line-height: 1.1;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}
            .{top_bar_class} .f8-compact-stat__value {{
                color: #ffffff;
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
                background: rgba(34, 197, 94, 0.22);
                color: #bbf7d0;
            }}
            .{top_bar_class} .f8-top-bar-message--warning {{
                background: rgba(250, 204, 21, 0.22);
                color: #fef08a;
            }}
            .{top_bar_class} .f8-top-bar-links {{
                color: rgba(255, 255, 255, 0.78);
                font-size: 0.72rem;
                line-height: 1.2;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: normal;
            }}
            .{top_bar_class} .f8-top-bar-links a {{
                color: #bfdbfe;
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
                .{top_bar_class} {{
                    margin-left: -1rem;
                    margin-right: -1rem;
                    padding-left: 1rem;
                    padding-right: 1rem;
                    width: calc(100% + 2rem);
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
    return st.container(key=top_bar_key)


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


inject_global_theme()

# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.markdown('<p class="f8-sidebar-section">Pages</p>', unsafe_allow_html=True)
page = st.sidebar.radio(
    "Section",
    list(PAGE_RENDERERS),
    key="sidebar_page",
    label_visibility="collapsed",
)
st.sidebar.markdown("---")
st.sidebar.markdown('<p class="f8-sidebar-section">Admin</p>', unsafe_allow_html=True)
_, dashboard_reader_path, dashboard_snapshot_warning = initialize_dashboard_storage()
if st.sidebar.button("Refresh data"):
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()
st.sidebar.markdown(
    f'<p class="f8-sidebar-meta">DB live: {escape(str(DB_PATH))}</p>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<p class="f8-sidebar-meta">Read path: {escape(str(dashboard_reader_path))}</p>',
    unsafe_allow_html=True,
)
if dashboard_snapshot_warning:
    st.sidebar.warning(dashboard_snapshot_warning)
st.sidebar.markdown(
    '<p class="f8-sidebar-footer">F8 13F Screener — hedge fund 13F tracker</p>',
    unsafe_allow_html=True,
)

top_bar = render_top_bar(page)
PAGE_RENDERERS[page](top_bar)
