"""
F8 F13 Screener — Streamlit Dashboard
Run locally:  streamlit run src/web/dashboard.py
"""
import sys
from pathlib import Path
from typing import TypeVar

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
from src.web.pages.fund_detail import render_fund_detail_page
from src.web.pages.fund_history import render_fund_history_page
from src.web.pages.holdings_search import render_holdings_search_page
from src.web.pages.overview import render_overview_page
from src.web.pages.portfolio_diff import render_portfolio_diff_page

st.set_page_config(
    page_title="F8 13F Screener",
    page_icon="📊",
    layout="wide",
)


SelectionT = TypeVar("SelectionT")


def require_selection(value: SelectionT | None, empty_message: str) -> SelectionT:
    if value is None:
        st.info(empty_message)
        st.stop()
    return value


def render_overview():
    render_overview_page(query, table_exists)


def render_fund_detail():
    render_fund_detail_page(
        get_fund_options,
        require_selection,
        fund_has_db_holdings,
        load_accessions_for_fund,
        query,
    )


def render_fund_history():
    render_fund_history_page(
        get_fund_options,
        require_selection,
        fund_has_db_holdings,
        load_fund_history,
    )


def render_portfolio_diff():
    render_portfolio_diff_page(
        get_fund_options,
        require_selection,
        fund_has_db_holdings,
        load_accessions_for_fund,
        load_normalized_positions_map,
        load_fund_history,
        load_fund_instrument_history,
    )


def render_holdings_search():
    render_holdings_search_page(query)


PAGE_RENDERERS = {
    "Overview": render_overview,
    "Fund Detail": render_fund_detail,
    "Fund History": render_fund_history,
    "Portfolio Diff": render_portfolio_diff,
    "Holdings Search": render_holdings_search,
}


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.title("📊 F8 13F Screener")
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

PAGE_RENDERERS[page]()
