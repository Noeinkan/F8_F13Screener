"""Reusable Streamlit table display settings for dashboard pages."""

from __future__ import annotations

import streamlit as st


DEFAULT_TABLE_HEIGHT = 420
COMPACT_TABLE_HEIGHT = 260
LARGE_TABLE_HEIGHT = 520


def holdings_column_config() -> dict:
    return {
        "Issuer": st.column_config.TextColumn("Issuer", width="large"),
        "CUSIP": st.column_config.TextColumn("CUSIP", width="small"),
        "Class": st.column_config.TextColumn("Class", width="small"),
        "Put/Call": st.column_config.TextColumn("Put/Call", width="small"),
        "Shares": st.column_config.TextColumn("Shares", width="small"),
        "Value": st.column_config.TextColumn("Value", width="small"),
        "Value ($000s)": st.column_config.NumberColumn("Value ($000s)", width="small", format="%d"),
        "Accession": st.column_config.TextColumn("Accession", width="medium"),
        "Filing Date": st.column_config.TextColumn("Filing Date", width="small"),
        "Fund": st.column_config.TextColumn("Fund", width="large"),
    }


def timeline_column_config() -> dict:
    return {
        "Filing Date": st.column_config.TextColumn("Filing Date", width="small"),
        "Accession": st.column_config.TextColumn("Accession", width="medium"),
        "Normalized Positions": st.column_config.NumberColumn("Positions", width="small", format="%d"),
        "Raw 13F Lines": st.column_config.NumberColumn("Raw lines", width="small", format="%d"),
        "Portfolio Value": st.column_config.TextColumn("Portfolio Value", width="small"),
    }


def diff_column_config() -> dict:
    return {
        "Issuer": st.column_config.TextColumn("Issuer", width="large"),
        "Direction": st.column_config.TextColumn("Direction", width="small"),
        "Delta %": st.column_config.TextColumn("Delta %", width="small"),
        "Delta Shares": st.column_config.TextColumn("Delta Shares", width="small"),
        "Delta Value %": st.column_config.TextColumn("Delta Value %", width="small"),
        "Delta Value": st.column_config.TextColumn("Delta Value", width="small"),
        "Shares Before": st.column_config.TextColumn("Shares Before", width="small"),
        "Shares After": st.column_config.TextColumn("Shares After", width="small"),
        "Value Before": st.column_config.TextColumn("Value Before", width="small"),
        "Value After": st.column_config.TextColumn("Value After", width="small"),
        "CUSIP": st.column_config.TextColumn("CUSIP", width="small"),
        "Class": st.column_config.TextColumn("Class", width="small"),
        "Put/Call": st.column_config.TextColumn("Put/Call", width="small"),
    }


def fund_overview_column_config() -> dict:
    return {
        "Fund": st.column_config.TextColumn("Fund", width="large"),
        "Quarters": st.column_config.NumberColumn("Quarters", width="small", format="%d"),
        "Latest Filing": st.column_config.TextColumn("Latest Filing", width="small"),
        "Raw 13F Lines": st.column_config.NumberColumn("Raw lines", width="small", format="%d"),
        "Normalized Positions": st.column_config.NumberColumn("Positions", width="small", format="%d"),
        "Distinct CUSIPs": st.column_config.NumberColumn("CUSIPs", width="small", format="%d"),
        "Portfolio Value": st.column_config.TextColumn("Portfolio Value", width="small"),
    }


def recent_filings_column_config() -> dict:
    return {
        "Fund": st.column_config.TextColumn("Fund", width="large"),
        "Filing Date": st.column_config.TextColumn("Filing Date", width="small"),
        "Accession": st.column_config.TextColumn("Accession", width="medium"),
        "Normalized Positions": st.column_config.NumberColumn("Positions", width="small", format="%d"),
        "Raw 13F Lines": st.column_config.NumberColumn("Raw lines", width="small", format="%d"),
    }


def common_holdings_column_config() -> dict:
    return {
        "Issuer": st.column_config.TextColumn("Issuer", width="large"),
        "CUSIP": st.column_config.TextColumn("CUSIP", width="small"),
        "Funds": st.column_config.NumberColumn("Funds", width="small", format="%d"),
        "Total Shares": st.column_config.NumberColumn("Total Shares", width="small", format="%d"),
        "Total Value ($000s)": st.column_config.NumberColumn("Total Value ($000s)", width="small", format="%d"),
    }