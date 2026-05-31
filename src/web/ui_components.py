"""Small Streamlit UI primitives for dense dashboard pages."""

from __future__ import annotations

import re

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


def render_dataframe(
    df: pd.DataFrame,
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