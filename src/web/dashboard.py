"""
F8 F13 Screener — Streamlit Dashboard
Run locally:  streamlit run src/web/dashboard.py
"""
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import TypeVar

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

# Ensure `src.*` imports work whether Streamlit is launched from repo root or src/web.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.diff import (
    build_position_key,
    compute_detailed_portfolio_diff,
    compute_quarterly_history_transitions,
)
from src.core.dashboard_snapshot import resolve_dashboard_snapshot
from src.core.dashboard_storage import DashboardStorage
from src.core.hedge_funds_config import HEDGE_FUNDS_CIK
from src.core.paths import DASHBOARD_DB_FILE

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_PATH = DASHBOARD_DB_FILE

st.set_page_config(
    page_title="F8 13F Screener",
    page_icon="📊",
    layout="wide",
)


SelectionT = TypeVar("SelectionT")
TRACKED_FUND_NAMES = sorted(HEDGE_FUNDS_CIK.values())
FUND_NAME_TO_CIK = {name: cik for cik, name in HEDGE_FUNDS_CIK.items()}
CACHE_DIR = PROJECT_ROOT / "cache"
DASHBOARD_SNAPSHOT_PATH = (
    CACHE_DIR / "dashboard" / f"13f_dashboard.{os.getpid()}.snapshot.duckdb"
)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
def show_db_recovery_help(error: Exception | None = None, integrity_result: str | None = None):
    """Render actionable recovery steps when the dashboard DB is unreadable."""
    st.error(f"Dashboard database is unreadable: {DB_PATH}")
    if integrity_result:
        st.caption(f"PRAGMA integrity_check: {integrity_result}")
    if error is not None:
        st.caption(f"Error details: {error}")

    st.info("""
To recover locally:
1) Verify DB integrity.
2) Rebuild the dashboard database with `--save-db`.
3) Restart Streamlit.
""")

    db_path_raw = str(DB_PATH)
    recovery_cmds = textwrap.dedent(
        f"""
        rtk python -c "import duckdb; c=duckdb.connect(r'{db_path_raw}'); print(c.execute('SELECT COUNT(*) FROM holdings').fetchone()[0])"
        rtk python -m src.cli.process_historical_13f full --yes --save-db
        rtk python -m streamlit run src/web/dashboard.py
        """
    ).strip()
    st.code(recovery_cmds, language="bash")


def require_selection(value: SelectionT | None, empty_message: str) -> SelectionT:
    if value is None:
        st.info(empty_message)
        st.stop()
    return value


@st.cache_data(ttl=2, show_spinner=False)
def get_dashboard_db_state() -> tuple[str, int, str | None]:
    resolved_path, warning = resolve_dashboard_snapshot(DB_PATH, DASHBOARD_SNAPSHOT_PATH)
    return str(resolved_path), resolved_path.stat().st_mtime_ns, warning


@st.cache_resource(show_spinner=False)
def get_storage(db_path_raw: str, _snapshot_version: int) -> DashboardStorage:
    db_path = Path(db_path_raw)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    storage = DashboardStorage(db_path)
    health = storage.get_health_snapshot()
    if health["total_rows"] > 0 and health["only_all_fund"]:
        raise RuntimeError(
            "Degenerate dataset: contains only fund_name=ALL. "
            "Rebuild the dashboard DB from the historical pipeline."
        )
    return storage


def initialize_dashboard_storage() -> tuple[DashboardStorage, Path, str | None]:
    try:
        db_path_raw, snapshot_version, warning = get_dashboard_db_state()
        storage = get_storage(db_path_raw, snapshot_version)
        return storage, Path(db_path_raw), warning
    except (duckdb.Error, OSError, RuntimeError) as exc:
        show_db_recovery_help(error=exc)
        st.stop()
    raise RuntimeError("Dashboard storage initialization interrupted")


def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    try:
        return DASHBOARD_STORAGE.query_df(sql, params)
    except (duckdb.Error, pd.errors.DatabaseError) as exc:
        show_db_recovery_help(error=exc)
        st.stop()
    raise RuntimeError("Dashboard query interrupted")


def get_fund_options() -> list[str]:
    db_funds = query("SELECT DISTINCT fund_name FROM holdings ORDER BY fund_name")
    db_names = []
    if not db_funds.empty and "fund_name" in db_funds.columns:
        db_names = [str(name) for name in db_funds["fund_name"].dropna().tolist()]
    return sorted(set(db_names).union(TRACKED_FUND_NAMES))


def load_cached_accessions_for_fund(fund: str) -> pd.DataFrame:
    cik = FUND_NAME_TO_CIK.get(fund)
    if not cik:
        return pd.DataFrame(columns=["accession_number", "filing_date"])

    cache_file = CACHE_DIR / f"{cik}.json"
    if not cache_file.exists():
        return pd.DataFrame(columns=["accession_number", "filing_date"])

    try:
        with cache_file.open("r", encoding="utf-8") as f:
            cached_data = json.load(f)
    except Exception:
        return pd.DataFrame(columns=["accession_number", "filing_date"])

    rows = []
    for filing in cached_data.get("filings", []):
        accession_number = filing.get("accession_number")
        filing_date = filing.get("filing_date")
        if accession_number and filing_date:
            rows.append({"accession_number": accession_number, "filing_date": filing_date})

    if not rows:
        return pd.DataFrame(columns=["accession_number", "filing_date"])

    return pd.DataFrame(rows).drop_duplicates().sort_values(
        ["filing_date", "accession_number"], ascending=[False, False]
    )


def fund_has_db_holdings(fund: str) -> bool:
    return not query(
        """
            SELECT 1
            FROM holdings
            WHERE fund_name = ?
            LIMIT 1
        """,
        (fund,),
    ).empty


def table_exists(table_name: str) -> bool:
        result = query(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                    AND table_name = ?
                LIMIT 1
                """,
                (table_name,),
        )
        return not result.empty


def dataframe_to_csv_bytes(df: pd.DataFrame | pd.Series) -> bytes:
    frame = df.to_frame() if isinstance(df, pd.Series) else df
    return frame.to_csv(index=False).encode("utf-8")


def fmt_value(val_thousands):
    """Format thousands-of-USD into readable string."""
    if pd.isna(val_thousands) or val_thousands == 0:
        return "-"
    v = float(val_thousands) * 1000
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}k"
    return f"${v:,.0f}"


def fmt_quantity(value):
    """Format share quantities while tolerating nulls and floats."""
    if pd.isna(value):
        return "-"
    numeric = float(value)
    if numeric.is_integer():
        return f"{int(numeric):,}"
    return f"{numeric:,.2f}"


def fmt_signed_quantity(value):
    if pd.isna(value):
        return "-"
    numeric = float(value)
    sign = "+" if numeric > 0 else ""
    if numeric.is_integer():
        return f"{sign}{int(numeric):,}"
    return f"{sign}{numeric:,.2f}"


def fmt_signed_pct(value):
    if value is None or pd.isna(value):
        return "-"
    return f"{value:+.1f}%"


def fmt_signed_value(value_thousands):
    if value_thousands is None or pd.isna(value_thousands):
        return "-"
    if value_thousands == 0:
        return "$0"
    sign = "+" if value_thousands > 0 else "-"
    absolute_value = fmt_value(abs(value_thousands))
    if absolute_value == "-":
        absolute_value = "$0"
    return f"{sign}{absolute_value}"


DASHBOARD_STORAGE, DASHBOARD_READER_PATH, DASHBOARD_SNAPSHOT_WARNING = initialize_dashboard_storage()


FULL_HOLDINGS_EXPORT_SQL = """
    SELECT
        filing_date AS "Filing Date",
        fund_name AS "Fund Name",
        fund_cik AS "Fund CIK",
        accession_number AS "Accession Number",
        filing_url AS "Filing URL",
        issuer_name AS "Name of Issuer",
        share_class AS "Title of Class",
        cusip AS "CUSIP",
        figi AS "FIGI",
        value_x1000 AS "Value Raw ($000s)",
        value_usd AS "Value ($000s)",
        shares_raw AS "Shares/Principal Amount Raw",
        shares AS "Shares/Principal Amount",
        sh_prn AS "SH/PRN",
        put_call AS "Put/Call",
        investment_discretion AS "Investment Discretion",
        other_manager AS "Other Manager",
        other_managers_raw AS "Other Managers (raw)",
        all_columns_raw AS "All Columns (raw)",
        voting_authority_sole AS "Voting Authority - Sole",
        voting_authority_shared AS "Voting Authority - Shared",
        voting_authority_none AS "Voting Authority - None"
    FROM holdings
    ORDER BY filing_date DESC, fund_name, issuer_name
"""


LATEST_SNAPSHOT_EXPORT_SQL = """
    WITH latest_filing AS (
        SELECT fund_name, MAX(filing_date) AS filing_date
        FROM holdings
        GROUP BY fund_name
    )
    SELECT
        h.fund_name AS "Fund Name",
        h.filing_date AS "Filing Date",
        h.accession_number AS "Accession Number",
        h.issuer_name AS "Name of Issuer",
        h.share_class AS "Title of Class",
        h.cusip AS "CUSIP",
        h.value_usd AS "Value ($000s)",
        h.shares AS "Shares/Principal Amount",
        h.put_call AS "Put/Call"
    FROM holdings h
    INNER JOIN latest_filing lf
        ON h.fund_name = lf.fund_name
       AND h.filing_date = lf.filing_date
    ORDER BY h.fund_name, h.value_usd DESC NULLS LAST, h.issuer_name
"""


POSITION_KEY_SQL = """
    CASE
        WHEN TRIM(COALESCE(cusip, '')) <> '' THEN
             TRIM(COALESCE(cusip, '')) || '|' ||
             TRIM(COALESCE(share_class, '')) || '|' ||
             TRIM(COALESCE(put_call, ''))
        ELSE TRIM(COALESCE(issuer_name, '')) || '|' ||
             TRIM(COALESCE(share_class, '')) || '|' ||
             TRIM(COALESCE(put_call, ''))
    END
"""


RAW_ACCESSION_HOLDINGS_SQL = """
    SELECT
        issuer_name AS "Issuer",
        TRIM(COALESCE(cusip, '')) AS "CUSIP",
        share_class AS "Class",
        shares AS "Shares",
        value_usd AS "Value ($000s)",
        put_call AS "Put/Call",
        investment_discretion AS "Investment Discretion",
        other_manager AS "Other Manager"
    FROM holdings
    WHERE fund_name = ? AND accession_number = ?
    ORDER BY value_usd DESC NULLS LAST, issuer_name
"""


NORMALIZED_ACCESSION_HOLDINGS_SQL = f"""
    SELECT
        MIN(issuer_name) AS "Issuer",
        MAX(TRIM(COALESCE(cusip, ''))) AS "CUSIP",
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(share_class), '')) AS "Class",
        SUM(shares) AS "Shares",
        SUM(value_usd) AS "Value ($000s)",
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(put_call), '')) AS "Put/Call",
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(investment_discretion), '')) AS "Investment Discretion",
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(other_manager), '')) AS "Other Manager",
        COUNT(*) AS "Raw 13F Lines"
    FROM holdings
    WHERE fund_name = ? AND accession_number = ?
    GROUP BY {POSITION_KEY_SQL}
    ORDER BY SUM(value_usd) DESC NULLS LAST, MIN(issuer_name)
"""


NORMALIZED_DIFF_SQL = f"""
    SELECT
        MAX(TRIM(COALESCE(cusip, ''))) AS cusip,
        MIN(issuer_name) AS issuer_name,
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(share_class), '')) AS share_class,
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(put_call), '')) AS put_call,
        SUM(shares) AS shares,
        SUM(value_usd) AS value_usd
    FROM holdings
    WHERE fund_name = ? AND accession_number = ?
    GROUP BY {POSITION_KEY_SQL}
    ORDER BY SUM(value_usd) DESC NULLS LAST, MIN(issuer_name)
"""


FUND_HISTORY_POSITIONS_SQL = f"""
    SELECT
        accession_number AS accession_number,
        filing_date AS filing_date,
        MAX(TRIM(COALESCE(cusip, ''))) AS cusip,
        MIN(issuer_name) AS issuer_name,
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(share_class), '')) AS share_class,
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(put_call), '')) AS put_call,
        SUM(shares) AS shares,
        SUM(value_usd) AS value_usd,
        COUNT(*) AS raw_lines
    FROM holdings
    WHERE fund_name = ?
      AND TRIM(COALESCE(accession_number, '')) <> ''
    GROUP BY accession_number, filing_date, {POSITION_KEY_SQL}
    ORDER BY filing_date DESC, SUM(value_usd) DESC NULLS LAST, MIN(issuer_name)
"""


OVERVIEW_SUMMARY_SQL = """
    SELECT
        COUNT(*) AS positions,
        COUNT(DISTINCT accession_number) AS filings,
        COUNT(DISTINCT fund_name) AS funds,
        MAX(filing_date) AS latest_filing_date,
        SUM(CASE WHEN value_usd IS NOT NULL THEN 1 ELSE 0 END) AS value_rows
    FROM holdings
"""


OVERVIEW_RECENT_ACTIVITY_SQL = """
    WITH anchor AS (
        SELECT MAX(filing_date) AS latest_filing_date
        FROM holdings
    )
    SELECT
        COUNT(DISTINCT accession_number) AS recent_filings,
        COUNT(DISTINCT fund_name) AS recent_funds
    FROM holdings, anchor
    WHERE CAST(filing_date AS DATE) >= CAST(anchor.latest_filing_date AS DATE) - INTERVAL 120 DAY
"""


LATEST_FUND_OVERVIEW_SQL = f"""
    WITH latest_filing AS (
        SELECT fund_name, MAX(filing_date) AS filing_date
        FROM holdings
        GROUP BY fund_name
    ),
    latest_accession AS (
        SELECT
            h.fund_name,
            lf.filing_date,
            MAX(h.accession_number) AS accession_number
        FROM holdings h
        INNER JOIN latest_filing lf
            ON h.fund_name = lf.fund_name
           AND h.filing_date = lf.filing_date
        GROUP BY h.fund_name, lf.filing_date
    ),
    quarters_tracked AS (
        SELECT
            fund_name,
            COUNT(DISTINCT accession_number) AS quarters_tracked
        FROM holdings
        GROUP BY fund_name
    ),
    latest_stats AS (
        SELECT
            h.fund_name,
            la.filing_date,
            la.accession_number,
            COUNT(*) AS raw_lines,
            COUNT(DISTINCT NULLIF(TRIM(cusip), '')) AS cusips,
            COUNT(DISTINCT {POSITION_KEY_SQL}) AS normalized_positions,
            SUM(value_usd) AS value_sum
        FROM holdings h
        INNER JOIN latest_accession la
            ON h.fund_name = la.fund_name
           AND h.accession_number = la.accession_number
        GROUP BY h.fund_name, la.filing_date, la.accession_number
    )
    SELECT
        ls.fund_name AS "Fund",
        qt.quarters_tracked AS "Quarters",
        ls.filing_date AS "Latest Filing",
        ls.raw_lines AS "Raw 13F Lines",
        ls.normalized_positions AS "Normalized Positions",
        ls.cusips AS "Distinct CUSIPs",
        ls.value_sum AS value_sum,
        ls.accession_number AS accession_number
    FROM latest_stats ls
    INNER JOIN quarters_tracked qt
        ON qt.fund_name = ls.fund_name
    ORDER BY ls.filing_date DESC, ls.raw_lines DESC, ls.fund_name
"""


RECENT_FILINGS_OVERVIEW_SQL = f"""
    WITH filing_stats AS (
        SELECT
            accession_number,
            fund_name,
            filing_date,
            COUNT(*) AS raw_lines,
            COUNT(DISTINCT NULLIF(TRIM(cusip), '')) AS cusips,
            COUNT(DISTINCT {POSITION_KEY_SQL}) AS normalized_positions
        FROM holdings
        WHERE TRIM(COALESCE(accession_number, '')) <> ''
        GROUP BY accession_number, fund_name, filing_date
    )
    SELECT
        fund_name AS "Fund",
        filing_date AS "Filing Date",
        accession_number AS "Accession",
        raw_lines AS "Raw 13F Lines",
        normalized_positions AS "Normalized Positions",
        cusips AS "Distinct CUSIPs"
    FROM filing_stats
    ORDER BY filing_date DESC, raw_lines DESC, fund_name
    LIMIT 20
"""


FILINGS_TIMELINE_SQL = """
    SELECT
        substr(filing_date, 1, 7) AS "Month",
        COUNT(DISTINCT accession_number) AS "Filings",
        COUNT(DISTINCT fund_name) AS "Funds"
    FROM holdings
    GROUP BY substr(filing_date, 1, 7)
    ORDER BY substr(filing_date, 1, 7)
"""


TOP_HELD_SECURITIES_SQL = f"""
    WITH latest_filing AS (
        SELECT fund_name, MAX(filing_date) AS filing_date
        FROM holdings
        GROUP BY fund_name
    ),
    latest_accession AS (
        SELECT
            h.fund_name,
            lf.filing_date,
            MAX(h.accession_number) AS accession_number
        FROM holdings h
        INNER JOIN latest_filing lf
            ON h.fund_name = lf.fund_name
           AND h.filing_date = lf.filing_date
        GROUP BY h.fund_name, lf.filing_date
    ),
    latest_positions AS (
        SELECT
            h.fund_name,
            {POSITION_KEY_SQL} AS position_key,
            MAX(TRIM(COALESCE(h.cusip, ''))) AS cusip,
            MIN(h.issuer_name) AS issuer_name
        FROM holdings h
        INNER JOIN latest_accession la
            ON h.fund_name = la.fund_name
           AND h.accession_number = la.accession_number
        GROUP BY h.fund_name, {POSITION_KEY_SQL}
    )
    SELECT
        MIN(issuer_name) AS "Issuer",
        NULLIF(MAX(cusip), '') AS "CUSIP",
        COUNT(*) AS "Funds Holding It"
    FROM latest_positions
    GROUP BY position_key
    ORDER BY COUNT(*) DESC, MIN(issuer_name)
    LIMIT 15
"""


def load_accessions_for_fund(fund: str) -> pd.DataFrame:
    accessions = query(
        """
            SELECT DISTINCT accession_number, filing_date
            FROM holdings
            WHERE fund_name = ?
              AND TRIM(COALESCE(accession_number, '')) <> ''
            ORDER BY filing_date DESC, accession_number DESC
        """,
        (fund,),
    )
    if not accessions.empty:
        return accessions

    return load_cached_accessions_for_fund(fund)


def load_normalized_positions_map(fund: str, accession_number: str) -> dict:
    rows = query(NORMALIZED_DIFF_SQL, (fund, accession_number))
    positions = {}
    for row in rows.to_dict("records"):
        position_key = build_position_key(
            row.get("cusip"),
            row.get("issuer_name"),
            row.get("share_class"),
            row.get("put_call"),
        )
        positions[position_key] = {
            "cusip": row.get("cusip") or "",
            "issuer_name": row.get("issuer_name"),
            "share_class": row.get("share_class"),
            "put_call": row.get("put_call"),
            "shares": row.get("shares"),
            "value_usd": row.get("value_usd"),
        }
    return positions


def load_fund_history(fund: str) -> tuple[pd.DataFrame, list[dict]]:
    rows = query(FUND_HISTORY_POSITIONS_SQL, (fund,))
    if rows.empty:
        return pd.DataFrame(), []

    summary_rows = []
    snapshots = []
    for group_key, group in rows.groupby(["filing_date", "accession_number"], sort=False):
        if not isinstance(group_key, tuple) or len(group_key) != 2:
            continue
        filing_date, accession_number = group_key
        positions = {}
        for row in group.to_dict("records"):
            position_key = build_position_key(
                row.get("cusip"),
                row.get("issuer_name"),
                row.get("share_class"),
                row.get("put_call"),
            )
            positions[position_key] = {
                "cusip": row.get("cusip") or "",
                "issuer_name": row.get("issuer_name"),
                "share_class": row.get("share_class"),
                "put_call": row.get("put_call"),
                "shares": row.get("shares"),
                "value_usd": row.get("value_usd"),
            }

        portfolio_value = (
            group["value_usd"].fillna(0).sum()
            if group["value_usd"].notna().any()
            else None
        )
        label = f"{filing_date} ({accession_number})"
        summary_rows.append({
            "Filing Date": filing_date,
            "Accession": accession_number,
            "Label": label,
            "Normalized Positions": len(group),
            "Raw 13F Lines": int(group["raw_lines"].fillna(0).sum()),
            "Portfolio Value ($000s)": portfolio_value,
        })
        snapshots.append({
            "filing_date": filing_date,
            "accession_number": accession_number,
            "label": label,
            "positions": positions,
        })

    summary_df = pd.DataFrame(summary_rows).sort_values("Filing Date").reset_index(drop=True)
    summary_df["Filing Date Dt"] = pd.to_datetime(summary_df["Filing Date"])
    transitions = compute_quarterly_history_transitions(snapshots)
    return summary_df, transitions


def normalize_text_cell(value: object) -> str:
    if value is None or pd.isna(value):
        return ""

    normalized = str(value).strip()
    return "" if normalized.lower() == "nan" else normalized


def instrument_type_label(put_call: str | None) -> str:
    normalized = normalize_text_cell(put_call).upper()
    return normalized or "Equity"


def instrument_share_class_label(share_class: str | None) -> str:
    normalized = normalize_text_cell(share_class)
    return normalized or "-"


def build_instrument_label(
    issuer_name: str | None,
    share_class: str | None,
    put_call: str | None,
    cusip: str | None,
) -> str:
    parts = [
        normalize_text_cell(issuer_name) or "Unknown issuer",
        instrument_share_class_label(share_class),
        instrument_type_label(put_call),
    ]
    normalized_cusip = normalize_text_cell(cusip)
    if normalized_cusip:
        parts.append(normalized_cusip)
    return " | ".join(parts)


def load_fund_instrument_history(fund: str) -> pd.DataFrame:
    rows = query(FUND_HISTORY_POSITIONS_SQL, (fund,))
    if rows.empty:
        return pd.DataFrame()

    instrument_df = rows.rename(columns={
        "accession_number": "Accession",
        "filing_date": "Filing Date",
        "cusip": "CUSIP",
        "issuer_name": "Issuer",
        "share_class": "Class",
        "put_call": "Put/Call",
        "shares": "Shares",
        "value_usd": "Value ($000s)",
        "raw_lines": "Raw 13F Lines",
    }).copy()
    instrument_df["Filing Date Dt"] = pd.to_datetime(instrument_df["Filing Date"])
    instrument_df["Position Key"] = instrument_df.apply(
        lambda row: build_position_key(
            row.get("CUSIP"),
            row.get("Issuer"),
            row.get("Class"),
            row.get("Put/Call"),
        ),
        axis=1,
    )
    instrument_df["Instrument Type"] = instrument_df["Put/Call"].apply(instrument_type_label)
    instrument_df["Instrument Label"] = instrument_df.apply(
        lambda row: build_instrument_label(
            row.get("Issuer"),
            row.get("Class"),
            row.get("Put/Call"),
            row.get("CUSIP"),
        ),
        axis=1,
    )
    instrument_df["Label"] = instrument_df.apply(
        lambda row: f"{row['Filing Date']} ({row['Accession']})",
        axis=1,
    )
    return instrument_df.sort_values(["Filing Date Dt", "Instrument Label"]).reset_index(drop=True)


def build_instrument_option_summary(instrument_history_df: pd.DataFrame) -> pd.DataFrame:
    if instrument_history_df.empty:
        return pd.DataFrame()

    latest_filing_dt = instrument_history_df["Filing Date Dt"].max()
    option_summary_df = (
        instrument_history_df
        .sort_values(
            ["Filing Date Dt", "Value ($000s)", "Shares", "Instrument Label"],
            ascending=[False, False, False, True],
            na_position="last",
        )
        .groupby("Position Key", as_index=False)
        .first()
    )
    option_summary_df["Present In Latest Filing"] = option_summary_df["Filing Date Dt"].eq(latest_filing_dt)
    return option_summary_df.sort_values(
        ["Present In Latest Filing", "Value ($000s)", "Shares", "Instrument Label"],
        ascending=[False, False, False, True],
        na_position="last",
    ).reset_index(drop=True)


def build_instrument_timeseries(
    history_df: pd.DataFrame,
    instrument_history_df: pd.DataFrame,
    position_key: str,
) -> pd.DataFrame:
    selected_rows = instrument_history_df.loc[
        instrument_history_df["Position Key"] == position_key
    ].copy()
    if selected_rows.empty:
        return pd.DataFrame()

    base_df = history_df[["Filing Date", "Filing Date Dt", "Accession", "Label"]].copy()
    selected_metadata = selected_rows.sort_values("Filing Date Dt").iloc[-1]
    selected_rows = selected_rows[
        [
            "Filing Date",
            "Accession",
            "Issuer",
            "CUSIP",
            "Class",
            "Put/Call",
            "Instrument Type",
            "Instrument Label",
            "Shares",
            "Value ($000s)",
        ]
    ]

    timeseries_df = base_df.merge(
        selected_rows,
        on=["Filing Date", "Accession"],
        how="left",
    )
    for column in ["Issuer", "CUSIP", "Class", "Put/Call", "Instrument Type", "Instrument Label"]:
        timeseries_df[column] = timeseries_df[column].fillna(selected_metadata[column])

    timeseries_df["Present"] = timeseries_df["Shares"].notna()
    timeseries_df["Position Status"] = timeseries_df["Present"].map({True: "Present", False: "Missing"})
    timeseries_df["Shares Filled"] = timeseries_df["Shares"].fillna(0)
    timeseries_df["Previous Shares"] = timeseries_df["Shares Filled"].shift(1)
    timeseries_df["Previous Filing"] = timeseries_df["Filing Date"].shift(1)
    timeseries_df["Δ Shares"] = timeseries_df["Shares Filled"].diff()
    timeseries_df["Δ %"] = timeseries_df.apply(
        lambda row: (
            None
            if pd.isna(row["Previous Shares"]) or row["Previous Shares"] == 0
            else (row["Δ Shares"] / row["Previous Shares"]) * 100
        ),
        axis=1,
    )
    return timeseries_df


def render_instrument_history_explorer(
    history_df: pd.DataFrame,
    instrument_history_df: pd.DataFrame,
    fund: str,
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
            key="portfolio_diff_instrument",
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


def transition_label(transition: dict) -> str:
    return (
        f"{transition['from_filing_date']} → {transition['to_filing_date']}  "
        f"({transition['from_accession_number']} → {transition['to_accession_number']})"
    )


def render_detailed_diff_sections(diff: dict):
    if diff["new_positions"]:
        st.subheader("New positions")
        new_df = pd.DataFrame(diff["new_positions"]).sort_values(
            ["value_usd", "issuer_name"],
            ascending=[False, True],
            na_position="last",
        )
        new_df["Shares"] = new_df["shares"].apply(fmt_quantity)
        new_df["Value"] = new_df["value_usd"].apply(fmt_value)
        st.dataframe(
            pd.DataFrame({
                "Issuer": new_df["issuer_name"],
                "CUSIP": new_df["cusip"],
                "Class": new_df["share_class"],
                "Put/Call": new_df["put_call"],
                "Shares": new_df["Shares"],
                "Value": new_df["Value"],
            }),
            use_container_width=True,
            hide_index=True,
        )

    if diff["closed_positions"]:
        st.subheader("Closed positions")
        closed_df = pd.DataFrame(diff["closed_positions"]).sort_values(
            ["value_usd", "issuer_name"],
            ascending=[False, True],
            na_position="last",
        )
        closed_df["Previous Shares"] = closed_df["shares"].apply(fmt_quantity)
        closed_df["Previous Value"] = closed_df["value_usd"].apply(fmt_value)
        st.dataframe(
            pd.DataFrame({
                "Issuer": closed_df["issuer_name"],
                "CUSIP": closed_df["cusip"],
                "Class": closed_df["share_class"],
                "Put/Call": closed_df["put_call"],
                "Previous Shares": closed_df["Previous Shares"],
                "Previous Value": closed_df["Previous Value"],
            }),
            use_container_width=True,
            hide_index=True,
        )

    changes = diff["increased"] + diff["decreased"]
    if changes:
        st.subheader("Significant changes (≥10%)")
        changes_df = pd.DataFrame(changes).sort_values("pct_change", ascending=False)
        changes_df["Shares Before"] = changes_df["old_shares"].apply(fmt_quantity)
        changes_df["Shares After"] = changes_df["new_shares"].apply(fmt_quantity)
        changes_df["Δ Shares"] = changes_df["share_change"].apply(fmt_signed_quantity)
        changes_df["Δ %"] = changes_df["pct_change"].apply(fmt_signed_pct)
        changes_df["Value Before"] = changes_df["old_value_usd"].apply(fmt_value)
        changes_df["Value After"] = changes_df["new_value_usd"].apply(fmt_value)
        changes_df["Δ Value"] = changes_df["value_change"].apply(fmt_signed_value)
        changes_df["Δ Value %"] = changes_df["value_pct_change"].apply(fmt_signed_pct)
        st.dataframe(
            pd.DataFrame({
                "Issuer": changes_df["issuer_name"],
                "CUSIP": changes_df["cusip"],
                "Class": changes_df["share_class"],
                "Put/Call": changes_df["put_call"],
                "Shares Before": changes_df["Shares Before"],
                "Shares After": changes_df["Shares After"],
                "Δ Shares": changes_df["Δ Shares"],
                "Δ %": changes_df["Δ %"],
                "Value Before": changes_df["Value Before"],
                "Value After": changes_df["Value After"],
                "Δ Value": changes_df["Δ Value"],
                "Δ Value %": changes_df["Δ Value %"],
            }),
            use_container_width=True,
            hide_index=True,
        )

    if not any([diff["new_positions"], diff["closed_positions"], changes]):
        st.success("No significant changes between the two quarters.")


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.title("📊 F8 13F Screener")
page = st.sidebar.radio(
    "Section",
    ["Overview", "Fund Detail", "Fund History", "Portfolio Diff", "Holdings Search"],
    key="sidebar_page",
)
st.sidebar.markdown("---")
st.sidebar.caption(f"DB live: `{DB_PATH}`")
st.sidebar.caption(f"Read path: `{DASHBOARD_READER_PATH}`")
if DASHBOARD_SNAPSHOT_WARNING:
    st.sidebar.warning(DASHBOARD_SNAPSHOT_WARNING)
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()


# ---------------------------------------------------------------------------
# Page 1 — Overview
# ---------------------------------------------------------------------------
if page == "Overview":
    st.title("Overview — 13F database status")

    dataset = query(OVERVIEW_SUMMARY_SQL)
    recent_activity = query(OVERVIEW_RECENT_ACTIVITY_SQL)
    has_portfolio_values = False

    if not dataset.empty:
        d = dataset.iloc[0]
        recent = recent_activity.iloc[0] if not recent_activity.empty else None
        has_portfolio_values = int(d["value_rows"] or 0) > 0
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Holding rows", f"{int(d['positions']):,}")
        c2.metric("13F filings", f"{int(d['filings']):,}")
        c3.metric("Covered funds", f"{int(d['funds']):,}")
        c4.metric("Latest filing", d["latest_filing_date"] or "-")
        c5.metric(
            "Filings in last ~120 days",
            f"{int(recent['recent_filings']):,}" if recent is not None else "-",
        )

        if recent is not None:
            st.caption(
                f"Funds with at least one filing in the last ~120 days: "
                f"{int(recent['recent_funds']):,}"
            )

        if not has_portfolio_values:
            st.warning(
                "Portfolio values are not available in the current database "
                "(`value_usd` / `value_x1000` are empty). "
                "This overview therefore shows useful signals based on filings, "
                "coverage, and normalized positions, which are the available data."
            )
        else:
            st.success(
                "Portfolio values are available: fund rankings and charts now use the latest valued filing."
            )

    if table_exists("statistics"):
        stats = query("SELECT * FROM statistics WHERE id = 1")
        if not stats.empty:
            s = stats.iloc[0]
            if any(int(s[col]) for col in ("total_checked", "matched", "filtered")):
                st.caption(
                    "Feed monitor stats: "
                    f"checked {int(s['total_checked']):,} | "
                    f"matched {int(s['matched']):,} | "
                    f"filtered {int(s['filtered']):,}"
                )

    st.subheader("Latest filing per fund")
    st.caption(
        "For each fund, we show only the latest available filing, with raw row count and "
        "CUSIP-normalized count."
    )
    df = query(LATEST_FUND_OVERVIEW_SQL)

    if df.empty:
        st.info("No data in the database yet.")
    else:
        full_export = query(FULL_HOLDINGS_EXPORT_SQL)
        latest_snapshot = query(LATEST_SNAPSHOT_EXPORT_SQL)
        recent_filings = query(RECENT_FILINGS_OVERVIEW_SQL)
        timeline_df = query(FILINGS_TIMELINE_SQL)
        common_holdings = query(TOP_HELD_SECURITIES_SQL)

        d1, d2 = st.columns(2)
        d1.download_button(
            "Download full holdings CSV",
            dataframe_to_csv_bytes(full_export),
            file_name="f8_13f_all_holdings.csv",
            mime="text/csv",
            use_container_width=True,
        )
        d2.download_button(
            "Download latest snapshot per fund",
            dataframe_to_csv_bytes(latest_snapshot),
            file_name="f8_13f_latest_snapshot.csv",
            mime="text/csv",
            use_container_width=True,
        )

        filter_text = st.text_input(
            "Filter fund",
            placeholder="es. AQR, Berkshire, Appaloosa",
        )
        filtered_df = df.copy()
        if filter_text:
            filtered_df = filtered_df[
                filtered_df["Fund"].str.contains(filter_text, case=False, na=False)
            ].copy()

        if has_portfolio_values:
            filtered_df["Portfolio Value"] = filtered_df["value_sum"].apply(fmt_value)

        display_columns = [
            "Fund",
            "Quarters",
            "Latest Filing",
            "Raw 13F Lines",
            "Normalized Positions",
            "Distinct CUSIPs",
        ]
        if has_portfolio_values:
            display_columns.append("Portfolio Value")
        selection_event = st.dataframe(
            filtered_df[display_columns],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
        )
        selected_rows = selection_event.get("selection", {}).get("rows", []) if selection_event else []
        if selected_rows:
            selected_idx = selected_rows[0]
            if selected_idx < len(filtered_df):
                selected_fund = filtered_df.iloc[selected_idx]["Fund"]
                st.session_state["fund_detail_selected_fund"] = selected_fund
                st.session_state["sidebar_page"] = "Fund Detail"
                st.rerun()

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            if has_portfolio_values:
                fig = px.bar(
                    df.sort_values("value_sum", ascending=False).head(20),
                    x="Fund",
                    y="value_sum",
                    labels={"value_sum": "Value ($000s)", "Fund": ""},
                    title="Top 20 funds by latest filing value",
                )
            else:
                fig = px.bar(
                    df.head(20),
                    x="Fund",
                    y="Normalized Positions",
                    labels={"Normalized Positions": "Positions", "Fund": ""},
                    title="Top 20 funds by normalized positions",
                )
            fig.update_layout(xaxis_tickangle=-40)
            st.plotly_chart(fig, use_container_width=True)

        with chart_col2:
            if not timeline_df.empty:
                fig = px.line(
                    timeline_df.tail(24),
                    x="Month",
                    y="Filings",
                    markers=True,
                    title="Filings stored per month",
                )
                st.plotly_chart(fig, use_container_width=True)

        insights_col1, insights_col2 = st.columns(2)
        with insights_col1:
            st.subheader("Most recent filings")
            st.dataframe(recent_filings, use_container_width=True, hide_index=True)

        with insights_col2:
            st.subheader("Most common holdings today")
            st.dataframe(common_holdings, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page 2 — Fund Detail
# ---------------------------------------------------------------------------
elif page == "Fund Detail":
    st.title("Fund Detail")

    funds = get_fund_options()
    if not funds:
        st.info("No data in the database yet.")
        st.stop()

    if st.session_state.get("fund_detail_selected_fund") not in funds:
        st.session_state["fund_detail_selected_fund"] = funds[0]

    fund = require_selection(
        st.selectbox("Select fund", funds, key="fund_detail_selected_fund"),
        "Select a fund to continue.",
    )

    if not fund_has_db_holdings(fund):
        st.warning(
            "This fund is selectable from configuration, but the holdings DB does not contain rows "
            "for this fund yet. The quarter list comes from local cache."
        )

    accessions = load_accessions_for_fund(fund)
    if accessions.empty:
        st.info("No quarter available for this fund.")
        st.stop()

    label_map = {
        row["accession_number"]: f"{row['filing_date']}  ({row['accession_number']})"
        for _, row in accessions.iterrows()
    }
    selected_acc = require_selection(
        st.selectbox(
            "Quarter (accession)",
            list(label_map.keys()),
            format_func=lambda k: label_map[k],
        ),
        "Select a quarter to continue.",
    )

    raw_df = query(RAW_ACCESSION_HOLDINGS_SQL, (fund, selected_acc))
    normalized_df = query(NORMALIZED_ACCESSION_HOLDINGS_SQL, (fund, selected_acc))

    if raw_df.empty:
        st.info("No holdings found for this quarter.")
        st.stop()

    c1, c2, c3 = st.columns(3)
    c1.metric("Raw 13F lines", f"{len(raw_df):,}")
    c2.metric("Normalized positions", f"{len(normalized_df):,}")
    compression_ratio = 1 - (len(normalized_df) / len(raw_df))
    c3.metric("Compression", f"{compression_ratio:.1%}")

    view_mode = st.radio(
        "Holdings view",
        ["Normalized by CUSIP", "Raw 13F lines"],
        horizontal=True,
    )
    st.caption(
        "The normalized view aggregates 13F rows with the same CUSIP, "
        "summing shares and value. This is the correct view for funds like AQR."
    )

    display_df = normalized_df.copy() if view_mode == "Normalized by CUSIP" else raw_df.copy()

    st.subheader(f"Top 10 holdings — {fund}")
    top10 = display_df.head(10)
    fig = px.bar(
        top10,
        x="Issuer",
        y="Value ($000s)",
        title=f"Top 10 by value — {fund}",
    )
    fig.update_layout(xaxis_tickangle=-30)
    st.plotly_chart(fig, use_container_width=True)

    view_label = "normalized positions" if view_mode == "Normalized by CUSIP" else "raw 13F lines"
    st.subheader(f"All {view_label} ({len(display_df):,})")
    search = st.text_input("Filter by name or CUSIP")
    filtered_df = display_df.copy()
    if search:
        mask = (
            filtered_df["Issuer"].str.contains(search, case=False, na=False)
            | filtered_df["CUSIP"].str.contains(search, case=False, na=False)
        )
        filtered_df = filtered_df.loc[mask].copy()

    st.download_button(
        "Download CSV for selected quarter",
        dataframe_to_csv_bytes(filtered_df),
        file_name=(
            f"f8_13f_{selected_acc}_normalized.csv"
            if view_mode == "Normalized by CUSIP"
            else f"f8_13f_{selected_acc}_raw.csv"
        ),
        mime="text/csv",
    )
    st.dataframe(filtered_df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page 3 — Fund History
# ---------------------------------------------------------------------------
elif page == "Fund History":
    st.title("Fund History — Quarter over Quarter")

    funds = get_fund_options()
    if not funds:
        st.info("No data in the database yet.")
        st.stop()

    fund = require_selection(
        st.selectbox("Select fund", funds, key="fund_history_fund"),
        "Select a fund to view history.",
    )

    if not fund_has_db_holdings(fund):
        st.warning(
            "This fund is selectable from configuration, but the holdings DB does not contain rows "
            "for this fund yet."
        )

    history_df, transitions = load_fund_history(fund)

    if history_df.empty:
        st.info("No history available for this fund.")
        st.stop()

    latest_snapshot = history_df.iloc[-1]
    has_portfolio_values = history_df["Portfolio Value ($000s)"].notna().any()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Available quarters", f"{len(history_df):,}")
    c2.metric("Latest filing", latest_snapshot["Filing Date"])
    c3.metric("Current positions", f"{int(latest_snapshot['Normalized Positions']):,}")
    c4.metric(
        "Latest filing value",
        fmt_value(latest_snapshot["Portfolio Value ($000s)"]) if has_portfolio_values else "-",
    )

    st.caption(
        "The opened/closed/improved/decreased categories use share changes. "
        "Portfolio values are shown as additional context when present in the DB."
    )

    summary_export = history_df.copy()
    if has_portfolio_values:
        summary_export["Portfolio Value"] = summary_export["Portfolio Value ($000s)"].apply(fmt_value)

    st.subheader("Quarter timeline")
    st.download_button(
        "Download fund timeline",
        dataframe_to_csv_bytes(summary_export.drop(columns=["Filing Date Dt"])),
        file_name=f"f8_13f_{fund}_history.csv".replace(" ", "_"),
        mime="text/csv",
    )

    display_columns = [
        "Filing Date",
        "Accession",
        "Normalized Positions",
        "Raw 13F Lines",
    ]
    if has_portfolio_values:
        display_columns.append("Portfolio Value")
    st.dataframe(summary_export[display_columns], use_container_width=True, hide_index=True)

    render_portfolio_timeline_charts(history_df, fund)

    if not transitions:
        st.info("At least one more quarter is needed to calculate quarter-over-quarter changes.")
        st.stop()

    render_transition_counts_chart(transitions, fund)

    latest_first_transitions = list(reversed(transitions))
    selected_transition_index = st.selectbox(
        "Transition drill-down",
        options=list(range(len(latest_first_transitions))),
        index=0,
        format_func=lambda index: transition_label(latest_first_transitions[index]),
    )
    selected_transition = latest_first_transitions[selected_transition_index]

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("New positions", selected_transition["new_count"])
    d2.metric("Closed positions", selected_transition["closed_count"])
    d3.metric("Increased", selected_transition["increased_count"])
    d4.metric("Decreased", selected_transition["decreased_count"])

    st.subheader(
        f"Transition details: {selected_transition['from_filing_date']} → {selected_transition['to_filing_date']}"
    )
    render_detailed_diff_sections(selected_transition)


# ---------------------------------------------------------------------------
# Page 4 — Portfolio Diff
# ---------------------------------------------------------------------------
elif page == "Portfolio Diff":
    st.title("Portfolio Diff — Quarter over Quarter")

    funds = get_fund_options()
    if not funds:
        st.info("No data in the database yet.")
        st.stop()

    fund = require_selection(
        st.selectbox("Select fund", funds, key="portfolio_diff_fund"),
        "Select a fund to calculate the diff.",
    )

    if not fund_has_db_holdings(fund):
        st.warning(
            "This fund is selectable from configuration, but the holdings DB does not contain rows "
            "for this fund yet."
        )

    accessions = load_accessions_for_fund(fund)
    if len(accessions) < 2:
        st.warning("At least 2 quarters are required to compute the diff.")
        st.stop()

    label_map = {
        row["accession_number"]: f"{row['filing_date']}  ({row['accession_number']})"
        for _, row in accessions.iterrows()
    }
    acc_list = list(label_map.keys())

    col1, col2 = st.columns(2)
    with col1:
        acc_new = require_selection(
            st.selectbox("NEW quarter", acc_list, format_func=lambda k: label_map[k], index=0),
            "Select the new quarter.",
        )
    with col2:
        acc_old = require_selection(
            st.selectbox("PREVIOUS quarter", acc_list, format_func=lambda k: label_map[k], index=1),
            "Select the previous quarter.",
        )

    if acc_new == acc_old:
        st.warning("Select two different quarters.")
        st.stop()

    old_map = load_normalized_positions_map(fund, acc_old)
    new_map = load_normalized_positions_map(fund, acc_new)
    diff = compute_detailed_portfolio_diff(old_map, new_map)
    history_df, transitions = load_fund_history(fund)
    instrument_history_df = load_fund_instrument_history(fund)

    st.caption(
        "Normalized comparison by position. Common shares, CALLs, and PUTs remain separate "
        "even when they share the same underlying CUSIP; positions without CUSIP use the fallback "
        "issuer/class/put-call."
    )

    if not history_df.empty:
        st.subheader("Fund historical trend")
        st.caption(
            "These charts use all filings available in the DB for the selected fund, "
            "so the comparison between the two quarters remains readable in historical context."
        )
        render_portfolio_timeline_charts(history_df, fund)
        if transitions:
            render_transition_counts_chart(
                transitions,
                fund,
                title=f"Portfolio changes over time — {fund}",
            )
        render_instrument_history_explorer(history_df, instrument_history_df, fund)

    # Summary metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("New positions", len(diff["new_positions"]))
    c2.metric("Closed positions", len(diff["closed_positions"]))
    c3.metric("Increased", len(diff["increased"]))
    c4.metric("Decreased", len(diff["decreased"]))
    render_detailed_diff_sections(diff)


# ---------------------------------------------------------------------------
# Page 5 — Holdings Search
# ---------------------------------------------------------------------------
elif page == "Holdings Search":
    st.title("Holdings Search")

    query_text = st.text_input("Search by issuer name or CUSIP", placeholder="e.g. Apple, 037833100")

    if not query_text:
        st.info("Enter a search term to begin.")
        st.stop()

    df = query("""
        SELECT
            issuer_name AS "Issuer",
            cusip       AS "CUSIP",
            fund_name   AS "Fund",
            filing_date AS "Filing Date",
            shares      AS "Shares",
            value_usd   AS "Value ($000s)",
            accession_number AS "Accession"
        FROM holdings
        WHERE issuer_name LIKE ? OR cusip LIKE ?
        ORDER BY filing_date DESC, value_usd DESC NULLS LAST
    """, (f"%{query_text}%", f"%{query_text}%"))

    if df.empty:
        st.warning(f"No results for '{query_text}'")
        st.stop()

    st.success(f"{len(df)} results found")
    df["Value"] = df["Value ($000s)"].apply(fmt_value)
    df["Shares"] = df["Shares"].apply(lambda x: f"{int(x):,}" if pd.notna(x) and x else "-")

    st.download_button(
        "Download CSV results",
        dataframe_to_csv_bytes(df),
        file_name="f8_13f_search_results.csv",
        mime="text/csv",
    )
    st.dataframe(
        df[["Issuer", "CUSIP", "Fund", "Filing Date", "Shares", "Value"]],
        use_container_width=True,
        hide_index=True,
    )

    # Show which funds currently hold this asset (latest filing per fund)
    st.subheader("Who holds it today (latest filing per fund)")
    latest = query("""
        SELECT h.fund_name AS "Fund", h.filing_date AS "Filing Date",
               h.shares AS "Shares", h.value_usd AS "Value ($000s)"
        FROM holdings h
        INNER JOIN (
            SELECT fund_name, MAX(filing_date) AS max_date
            FROM holdings
            WHERE issuer_name LIKE ? OR cusip LIKE ?
            GROUP BY fund_name
        ) latest ON h.fund_name = latest.fund_name AND h.filing_date = latest.max_date
        WHERE h.issuer_name LIKE ? OR h.cusip LIKE ?
        ORDER BY h.value_usd DESC NULLS LAST
    """, (f"%{query_text}%", f"%{query_text}%", f"%{query_text}%", f"%{query_text}%"))

    if not latest.empty:
        latest["Value"] = latest["Value ($000s)"].apply(fmt_value)
        latest["Shares"] = latest["Shares"].apply(lambda x: f"{int(x):,}" if pd.notna(x) and x else "-")
        st.dataframe(latest[["Fund", "Filing Date", "Shares", "Value"]],
                     use_container_width=True, hide_index=True)
