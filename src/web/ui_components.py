"""Small Streamlit UI primitives for dense dashboard pages."""

from __future__ import annotations

from html import escape
import re
from typing import Any

import pandas as pd
import streamlit as st

from src.web.table_config import DEFAULT_TABLE_HEIGHT


def slugify_label(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug or "section"


def render_section(title: str, description: str | None = None) -> None:
    st.markdown(f'<a id="{slugify_label(title)}"></a>', unsafe_allow_html=True)
    st.header(title)
    if description:
        st.caption(description)


def render_page_index(items: list[tuple[str, str]]) -> None:
    links = " &nbsp; ".join(f"[{label}](#{slugify_label(anchor)})" for label, anchor in items)
    st.caption(f"On this page: {links}")


def render_compact_page_index(items: list[tuple[str, str]]) -> None:
    links = "".join(
        f'<a href="#{slugify_label(anchor)}">{escape(label)}</a>'
        for label, anchor in items
    )
    st.markdown(f'<div class="f8-top-bar-links">On this page:{links}</div>', unsafe_allow_html=True)


def render_compact_stats(items: list[tuple[str, str]], *, columns: int | None = None) -> None:
    stat_count = columns or len(items)
    cards = "".join(
        "<div class=\"f8-compact-stat\">"
        f"<div class=\"f8-compact-stat__label\">{escape(label)}</div>"
        f"<div class=\"f8-compact-stat__value\" title=\"{escape(value)}\">{escape(value)}</div>"
        "</div>"
        for label, value in items
    )
    st.markdown(
        f'<div class="f8-compact-stats" style="--f8-stat-count: {stat_count};">{cards}</div>',
        unsafe_allow_html=True,
    )


def render_top_bar_message(message: str, *, level: str = "success") -> None:
    safe_level = "warning" if level == "warning" else "success"
    st.markdown(
        f'<div class="f8-top-bar-message f8-top-bar-message--{safe_level}">{escape(message)}</div>',
        unsafe_allow_html=True,
    )


def render_dataframe(
    df: pd.DataFrame | Any,
    *,
    height: int = DEFAULT_TABLE_HEIGHT,
    column_config: dict | None = None,
    column_order: list[str] | None = None,
):
    return st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=height,
        column_config=column_config,
        column_order=column_order,
    )


def safe_file_token(value: str) -> str:
    token = re.sub(r"[^0-9A-Za-z._-]+", "_", value.strip())
    return token.strip("_") or "export"