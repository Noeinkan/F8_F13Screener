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
    st.error(f"Database dashboard non leggibile: {DB_PATH}")
    if integrity_result:
        st.caption(f"PRAGMA integrity_check: {integrity_result}")
    if error is not None:
        st.caption(f"Dettaglio errore: {error}")

    st.info("""
Per ripristinare in locale:
1) Verifica integrita del DB.
2) Ricostruisci il database dashboard con `--save-db`.
3) Riavvia Streamlit.
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
        raise FileNotFoundError(f"Database non trovato: {db_path}")

    storage = DashboardStorage(db_path)
    health = storage.get_health_snapshot()
    if health["total_rows"] > 0 and health["only_all_fund"]:
        raise RuntimeError(
            "Dataset degenerato: contiene solo fund_name=ALL. "
            "Ricostruisci il DB dashboard dalla pipeline storica."
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
        WHEN TRIM(COALESCE(cusip, '')) <> '' THEN TRIM(cusip)
        ELSE TRIM(COALESCE(issuer_name, '')) || '|' ||
             TRIM(COALESCE(share_class, '')) || '|' ||
             TRIM(COALESCE(put_call, ''))
    END
"""


RAW_ACCESSION_HOLDINGS_SQL = """
    SELECT
        issuer_name AS "Issuer",
        TRIM(COALESCE(cusip, '')) AS "CUSIP",
        share_class AS "Classe",
        shares AS "Azioni",
        value_usd AS "Valore ($000s)",
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
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(share_class), '')) AS "Classe",
        SUM(shares) AS "Azioni",
        SUM(value_usd) AS "Valore ($000s)",
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
        qt.quarters_tracked AS "Trimestri",
        ls.filing_date AS "Ultimo Filing",
        ls.raw_lines AS "Raw 13F Lines",
        ls.normalized_positions AS "Posizioni normalizzate",
        ls.cusips AS "CUSIP distinti",
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
        normalized_positions AS "Posizioni normalizzate",
        cusips AS "CUSIP distinti"
    FROM filing_stats
    ORDER BY filing_date DESC, raw_lines DESC, fund_name
    LIMIT 20
"""


FILINGS_TIMELINE_SQL = """
    SELECT
        substr(filing_date, 1, 7) AS "Mese",
        COUNT(DISTINCT accession_number) AS "Filing",
        COUNT(DISTINCT fund_name) AS "Fondi"
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
        COUNT(*) AS "Fondi che la detengono"
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
            "Posizioni normalizzate": len(group),
            "Raw 13F Lines": int(group["raw_lines"].fillna(0).sum()),
            "Valore portfolio ($000s)": portfolio_value,
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


def build_transition_summary_df(transitions: list[dict]) -> pd.DataFrame:
    if not transitions:
        return pd.DataFrame()

    summary_df = pd.DataFrame([
        {
            "Transition": f"{item['from_filing_date']} → {item['to_filing_date']}",
            "Order": index,
            "To Filing Date": item["to_filing_date"],
            "Nuove": item["new_count"],
            "Chiuse": item["closed_count"],
            "Aumentate": item["increased_count"],
            "Diminuite": item["decreased_count"],
        }
        for index, item in enumerate(transitions)
    ])
    summary_df["To Filing Date Dt"] = pd.to_datetime(summary_df["To Filing Date"])
    summary_df["Posizioni modificate"] = summary_df[
        ["Nuove", "Chiuse", "Aumentate", "Diminuite"]
    ].sum(axis=1)
    return summary_df


def render_portfolio_timeline_charts(history_df: pd.DataFrame, fund: str):
    has_portfolio_values = history_df["Valore portfolio ($000s)"].notna().any()

    charts_col1, charts_col2 = st.columns(2)
    with charts_col1:
        positions_fig = px.line(
            history_df,
            x="Filing Date Dt",
            y="Posizioni normalizzate",
            markers=True,
            hover_name="Label",
            title=f"Posizioni normalizzate per trimestre — {fund}",
        )
        positions_fig.update_xaxes(title="Filing date")
        positions_fig.update_yaxes(title="Posizioni normalizzate")
        st.plotly_chart(positions_fig, use_container_width=True)

    with charts_col2:
        if has_portfolio_values:
            value_fig = px.line(
                history_df,
                x="Filing Date Dt",
                y="Valore portfolio ($000s)",
                markers=True,
                hover_name="Label",
                title=f"Valore portfolio per trimestre — {fund}",
            )
            value_fig.update_xaxes(title="Filing date")
            value_fig.update_yaxes(title="Valore ($000s)")
            st.plotly_chart(value_fig, use_container_width=True)
        else:
            st.info("Valori di portafoglio non disponibili per questo fondo nel DB corrente.")


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
        value_vars=["Nuove", "Chiuse", "Aumentate", "Diminuite"],
        var_name="Categoria",
        value_name="Posizioni",
    )
    melted_counts = melted_counts.sort_values(["Order", "Categoria"])
    transition_fig = px.bar(
        melted_counts,
        x="Transition",
        y="Posizioni",
        color="Categoria",
        barmode="group",
        title=title or f"Cambiamenti tra trimestri — {fund}",
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
        st.subheader("Nuove posizioni")
        new_df = pd.DataFrame(diff["new_positions"]).sort_values(
            ["value_usd", "issuer_name"],
            ascending=[False, True],
            na_position="last",
        )
        new_df["Azioni"] = new_df["shares"].apply(fmt_quantity)
        new_df["Valore"] = new_df["value_usd"].apply(fmt_value)
        st.dataframe(
            pd.DataFrame({
                "Issuer": new_df["issuer_name"],
                "CUSIP": new_df["cusip"],
                "Classe": new_df["share_class"],
                "Put/Call": new_df["put_call"],
                "Azioni": new_df["Azioni"],
                "Valore": new_df["Valore"],
            }),
            use_container_width=True,
            hide_index=True,
        )

    if diff["closed_positions"]:
        st.subheader("Posizioni chiuse")
        closed_df = pd.DataFrame(diff["closed_positions"]).sort_values(
            ["value_usd", "issuer_name"],
            ascending=[False, True],
            na_position="last",
        )
        closed_df["Azioni precedenti"] = closed_df["shares"].apply(fmt_quantity)
        closed_df["Valore precedente"] = closed_df["value_usd"].apply(fmt_value)
        st.dataframe(
            pd.DataFrame({
                "Issuer": closed_df["issuer_name"],
                "CUSIP": closed_df["cusip"],
                "Classe": closed_df["share_class"],
                "Put/Call": closed_df["put_call"],
                "Azioni precedenti": closed_df["Azioni precedenti"],
                "Valore precedente": closed_df["Valore precedente"],
            }),
            use_container_width=True,
            hide_index=True,
        )

    changes = diff["increased"] + diff["decreased"]
    if changes:
        st.subheader("Variazioni significative (≥10%)")
        changes_df = pd.DataFrame(changes).sort_values("pct_change", ascending=False)
        changes_df["Azioni prima"] = changes_df["old_shares"].apply(fmt_quantity)
        changes_df["Azioni dopo"] = changes_df["new_shares"].apply(fmt_quantity)
        changes_df["Δ Azioni"] = changes_df["share_change"].apply(fmt_signed_quantity)
        changes_df["Δ %"] = changes_df["pct_change"].apply(fmt_signed_pct)
        changes_df["Valore prima"] = changes_df["old_value_usd"].apply(fmt_value)
        changes_df["Valore dopo"] = changes_df["new_value_usd"].apply(fmt_value)
        changes_df["Δ Valore"] = changes_df["value_change"].apply(fmt_signed_value)
        changes_df["Δ Valore %"] = changes_df["value_pct_change"].apply(fmt_signed_pct)
        st.dataframe(
            pd.DataFrame({
                "Issuer": changes_df["issuer_name"],
                "CUSIP": changes_df["cusip"],
                "Classe": changes_df["share_class"],
                "Put/Call": changes_df["put_call"],
                "Azioni prima": changes_df["Azioni prima"],
                "Azioni dopo": changes_df["Azioni dopo"],
                "Δ Azioni": changes_df["Δ Azioni"],
                "Δ %": changes_df["Δ %"],
                "Valore prima": changes_df["Valore prima"],
                "Valore dopo": changes_df["Valore dopo"],
                "Δ Valore": changes_df["Δ Valore"],
                "Δ Valore %": changes_df["Δ Valore %"],
            }),
            use_container_width=True,
            hide_index=True,
        )

    if not any([diff["new_positions"], diff["closed_positions"], changes]):
        st.success("Nessuna variazione significativa tra i due trimestri.")


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.title("📊 F8 13F Screener")
page = st.sidebar.radio(
    "Sezione",
    ["Overview", "Fund Detail", "Fund History", "Portfolio Diff", "Holdings Search"],
)
st.sidebar.markdown("---")
st.sidebar.caption(f"DB live: `{DB_PATH}`")
st.sidebar.caption(f"Lettura: `{DASHBOARD_READER_PATH}`")
if DASHBOARD_SNAPSHOT_WARNING:
    st.sidebar.warning(DASHBOARD_SNAPSHOT_WARNING)
if st.sidebar.button("🔄 Aggiorna dati"):
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()


# ---------------------------------------------------------------------------
# Page 1 — Overview
# ---------------------------------------------------------------------------
if page == "Overview":
    st.title("Overview — Stato del database 13F")

    dataset = query(OVERVIEW_SUMMARY_SQL)
    recent_activity = query(OVERVIEW_RECENT_ACTIVITY_SQL)
    has_portfolio_values = False

    if not dataset.empty:
        d = dataset.iloc[0]
        recent = recent_activity.iloc[0] if not recent_activity.empty else None
        has_portfolio_values = int(d["value_rows"] or 0) > 0
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Righe holdings", f"{int(d['positions']):,}")
        c2.metric("Filing 13F", f"{int(d['filings']):,}")
        c3.metric("Fondi coperti", f"{int(d['funds']):,}")
        c4.metric("Ultimo filing", d["latest_filing_date"] or "-")
        c5.metric(
            "Filing ultimi ~120gg",
            f"{int(recent['recent_filings']):,}" if recent is not None else "-",
        )

        if recent is not None:
            st.caption(
                f"Fondi con almeno un filing negli ultimi ~120 giorni: "
                f"{int(recent['recent_funds']):,}"
            )

        if not has_portfolio_values:
            st.warning(
                "Nel database corrente i valori di portafoglio non sono presenti "
                "(`value_usd` / `value_x1000` sono vuoti). "
                "Questa overview mostra quindi segnali utili basati su filing, "
                "copertura e posizioni normalizzate, che sono i dati realmente disponibili."
            )
        else:
            st.success(
                "I valori di portafoglio sono disponibili: classifica fondi e grafici ora usano l'ultimo filing valorizzato."
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

    st.subheader("Ultimo filing per fondo")
    st.caption(
        "Per ogni fondo mostriamo solo l'ultimo filing disponibile, con conteggio raw e "
        "conteggio normalizzato per CUSIP."
    )
    df = query(LATEST_FUND_OVERVIEW_SQL)

    if df.empty:
        st.info("Nessun dato nel database ancora.")
    else:
        full_export = query(FULL_HOLDINGS_EXPORT_SQL)
        latest_snapshot = query(LATEST_SNAPSHOT_EXPORT_SQL)
        recent_filings = query(RECENT_FILINGS_OVERVIEW_SQL)
        timeline_df = query(FILINGS_TIMELINE_SQL)
        common_holdings = query(TOP_HELD_SECURITIES_SQL)

        d1, d2 = st.columns(2)
        d1.download_button(
            "Scarica CSV completo holdings",
            dataframe_to_csv_bytes(full_export),
            file_name="f8_13f_all_holdings.csv",
            mime="text/csv",
            use_container_width=True,
        )
        d2.download_button(
            "Scarica ultimo snapshot per fondo",
            dataframe_to_csv_bytes(latest_snapshot),
            file_name="f8_13f_latest_snapshot.csv",
            mime="text/csv",
            use_container_width=True,
        )

        filter_text = st.text_input(
            "Filtra fondo",
            placeholder="es. AQR, Berkshire, Appaloosa",
        )
        filtered_df = df.copy()
        if filter_text:
            filtered_df = filtered_df[
                filtered_df["Fund"].str.contains(filter_text, case=False, na=False)
            ].copy()

        if has_portfolio_values:
            filtered_df["Valore portfolio"] = filtered_df["value_sum"].apply(fmt_value)

        display_columns = [
            "Fund",
            "Trimestri",
            "Ultimo Filing",
            "Raw 13F Lines",
            "Posizioni normalizzate",
            "CUSIP distinti",
        ]
        if has_portfolio_values:
            display_columns.append("Valore portfolio")
        st.dataframe(
            filtered_df[display_columns],
            use_container_width=True,
            hide_index=True,
        )

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            if has_portfolio_values:
                fig = px.bar(
                    df.sort_values("value_sum", ascending=False).head(20),
                    x="Fund",
                    y="value_sum",
                    labels={"value_sum": "Valore ($000s)", "Fund": ""},
                    title="Top 20 fondi per valore ultimo filing",
                )
            else:
                fig = px.bar(
                    df.head(20),
                    x="Fund",
                    y="Posizioni normalizzate",
                    labels={"Posizioni normalizzate": "Posizioni", "Fund": ""},
                    title="Top 20 fondi per posizioni normalizzate",
                )
            fig.update_layout(xaxis_tickangle=-40)
            st.plotly_chart(fig, use_container_width=True)

        with chart_col2:
            if not timeline_df.empty:
                fig = px.line(
                    timeline_df.tail(24),
                    x="Mese",
                    y="Filing",
                    markers=True,
                    title="Filing archiviati per mese",
                )
                st.plotly_chart(fig, use_container_width=True)

        insights_col1, insights_col2 = st.columns(2)
        with insights_col1:
            st.subheader("Filing piu recenti")
            st.dataframe(recent_filings, use_container_width=True, hide_index=True)

        with insights_col2:
            st.subheader("Titoli piu diffusi oggi")
            st.dataframe(common_holdings, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page 2 — Fund Detail
# ---------------------------------------------------------------------------
elif page == "Fund Detail":
    st.title("Fund Detail")

    funds = get_fund_options()
    if not funds:
        st.info("Nessun dato nel database ancora.")
        st.stop()

    fund = require_selection(
        st.selectbox("Seleziona fondo", funds),
        "Seleziona un fondo per continuare.",
    )

    if not fund_has_db_holdings(fund):
        st.warning(
            "Questo fondo è selezionabile dalla configurazione, ma il DB holdings non contiene ancora "
            "righe per questo fondo. La lista trimestri arriva dalla cache locale."
        )

    accessions = load_accessions_for_fund(fund)
    if accessions.empty:
        st.info("Nessun trimestre disponibile per questo fondo.")
        st.stop()

    label_map = {
        row["accession_number"]: f"{row['filing_date']}  ({row['accession_number']})"
        for _, row in accessions.iterrows()
    }
    selected_acc = require_selection(
        st.selectbox(
            "Trimestre (accession)",
            list(label_map.keys()),
            format_func=lambda k: label_map[k],
        ),
        "Seleziona un trimestre per continuare.",
    )

    raw_df = query(RAW_ACCESSION_HOLDINGS_SQL, (fund, selected_acc))
    normalized_df = query(NORMALIZED_ACCESSION_HOLDINGS_SQL, (fund, selected_acc))

    if raw_df.empty:
        st.info("Nessuna holding trovata per questo trimestre.")
        st.stop()

    c1, c2, c3 = st.columns(3)
    c1.metric("Raw 13F lines", f"{len(raw_df):,}")
    c2.metric("Posizioni normalizzate", f"{len(normalized_df):,}")
    compression_ratio = 1 - (len(normalized_df) / len(raw_df))
    c3.metric("Compressione", f"{compression_ratio:.1%}")

    view_mode = st.radio(
        "Vista holdings",
        ["Normalizzata per CUSIP", "Raw 13F lines"],
        horizontal=True,
    )
    st.caption(
        "La vista normalizzata aggrega le righe 13F con lo stesso CUSIP, "
        "sommando azioni e valore. E' la vista corretta per fondi come AQR."
    )

    display_df = normalized_df.copy() if view_mode == "Normalizzata per CUSIP" else raw_df.copy()

    st.subheader(f"Top 10 holdings — {fund}")
    top10 = display_df.head(10)
    fig = px.bar(
        top10,
        x="Issuer",
        y="Valore ($000s)",
        title=f"Top 10 per valore — {fund}",
    )
    fig.update_layout(xaxis_tickangle=-30)
    st.plotly_chart(fig, use_container_width=True)

    view_label = "posizioni normalizzate" if view_mode == "Normalizzata per CUSIP" else "righe raw 13F"
    st.subheader(f"Tutte le {view_label} ({len(display_df):,})")
    search = st.text_input("Filtra per nome o CUSIP")
    filtered_df = display_df.copy()
    if search:
        mask = (
            filtered_df["Issuer"].str.contains(search, case=False, na=False)
            | filtered_df["CUSIP"].str.contains(search, case=False, na=False)
        )
        filtered_df = filtered_df.loc[mask].copy()

    st.download_button(
        "Scarica CSV del trimestre selezionato",
        dataframe_to_csv_bytes(filtered_df),
        file_name=(
            f"f8_13f_{selected_acc}_normalized.csv"
            if view_mode == "Normalizzata per CUSIP"
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
        st.info("Nessun dato nel database ancora.")
        st.stop()

    fund = require_selection(
        st.selectbox("Seleziona fondo", funds, key="fund_history_fund"),
        "Seleziona un fondo per visualizzare la history.",
    )

    if not fund_has_db_holdings(fund):
        st.warning(
            "Questo fondo è selezionabile dalla configurazione, ma il DB holdings non contiene ancora "
            "righe per questo fondo."
        )

    history_df, transitions = load_fund_history(fund)

    if history_df.empty:
        st.info("Nessuna history disponibile per questo fondo.")
        st.stop()

    latest_snapshot = history_df.iloc[-1]
    has_portfolio_values = history_df["Valore portfolio ($000s)"].notna().any()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Trimestri disponibili", f"{len(history_df):,}")
    c2.metric("Ultimo filing", latest_snapshot["Filing Date"])
    c3.metric("Posizioni attuali", f"{int(latest_snapshot['Posizioni normalizzate']):,}")
    c4.metric(
        "Valore ultimo filing",
        fmt_value(latest_snapshot["Valore portfolio ($000s)"]) if has_portfolio_values else "-",
    )

    st.caption(
        "Le categorie opened/closed/improved/decreased usano la variazione delle azioni. "
        "I valori di portafoglio sono mostrati come contesto aggiuntivo quando presenti nel DB."
    )

    summary_export = history_df.copy()
    if has_portfolio_values:
        summary_export["Valore portfolio"] = summary_export["Valore portfolio ($000s)"].apply(fmt_value)

    st.subheader("Timeline trimestri")
    st.download_button(
        "Scarica timeline fondo",
        dataframe_to_csv_bytes(summary_export.drop(columns=["Filing Date Dt"])),
        file_name=f"f8_13f_{fund}_history.csv".replace(" ", "_"),
        mime="text/csv",
    )

    display_columns = [
        "Filing Date",
        "Accession",
        "Posizioni normalizzate",
        "Raw 13F Lines",
    ]
    if has_portfolio_values:
        display_columns.append("Valore portfolio")
    st.dataframe(summary_export[display_columns], use_container_width=True, hide_index=True)

    render_portfolio_timeline_charts(history_df, fund)

    if not transitions:
        st.info("Serve almeno un altro trimestre per calcolare i cambiamenti quarter over quarter.")
        st.stop()

    render_transition_counts_chart(transitions, fund)

    latest_first_transitions = list(reversed(transitions))
    selected_transition_index = st.selectbox(
        "Drill-down transizione",
        options=list(range(len(latest_first_transitions))),
        index=0,
        format_func=lambda index: transition_label(latest_first_transitions[index]),
    )
    selected_transition = latest_first_transitions[selected_transition_index]

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Nuove posizioni", selected_transition["new_count"])
    d2.metric("Posizioni chiuse", selected_transition["closed_count"])
    d3.metric("Aumentate", selected_transition["increased_count"])
    d4.metric("Diminuite", selected_transition["decreased_count"])

    st.subheader(
        f"Dettaglio transizione: {selected_transition['from_filing_date']} → {selected_transition['to_filing_date']}"
    )
    render_detailed_diff_sections(selected_transition)


# ---------------------------------------------------------------------------
# Page 4 — Portfolio Diff
# ---------------------------------------------------------------------------
elif page == "Portfolio Diff":
    st.title("Portfolio Diff — Quarter over Quarter")

    funds = get_fund_options()
    if not funds:
        st.info("Nessun dato nel database ancora.")
        st.stop()

    fund = require_selection(
        st.selectbox("Seleziona fondo", funds, key="portfolio_diff_fund"),
        "Seleziona un fondo per calcolare il diff.",
    )

    if not fund_has_db_holdings(fund):
        st.warning(
            "Questo fondo è selezionabile dalla configurazione, ma il DB holdings non contiene ancora "
            "righe per questo fondo."
        )

    accessions = load_accessions_for_fund(fund)
    if len(accessions) < 2:
        st.warning("Servono almeno 2 trimestri per calcolare il diff.")
        st.stop()

    label_map = {
        row["accession_number"]: f"{row['filing_date']}  ({row['accession_number']})"
        for _, row in accessions.iterrows()
    }
    acc_list = list(label_map.keys())

    col1, col2 = st.columns(2)
    with col1:
        acc_new = require_selection(
            st.selectbox("Trimestre NUOVO", acc_list, format_func=lambda k: label_map[k], index=0),
            "Seleziona il trimestre nuovo.",
        )
    with col2:
        acc_old = require_selection(
            st.selectbox("Trimestre PRECEDENTE", acc_list, format_func=lambda k: label_map[k], index=1),
            "Seleziona il trimestre precedente.",
        )

    if acc_new == acc_old:
        st.warning("Seleziona due trimestri diversi.")
        st.stop()

    old_map = load_normalized_positions_map(fund, acc_old)
    new_map = load_normalized_positions_map(fund, acc_new)
    diff = compute_detailed_portfolio_diff(old_map, new_map)
    history_df, transitions = load_fund_history(fund)

    st.caption(
        "Confronto normalizzato per posizione. Anche i titoli senza CUSIP vengono confrontati "
        "tramite chiave fallback issuer/class/put-call."
    )

    if not history_df.empty:
        st.subheader("Trend storico del fondo")
        st.caption(
            "Queste grafiche usano tutti i filing disponibili nel DB per il fondo selezionato, "
            "cosi il confronto tra i due trimestri resta leggibile nel contesto storico."
        )
        render_portfolio_timeline_charts(history_df, fund)
        if transitions:
            render_transition_counts_chart(
                transitions,
                fund,
                title=f"Variazioni dei portafogli nel tempo — {fund}",
            )

    # Summary metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Nuove posizioni", len(diff["new_positions"]))
    c2.metric("Posizioni chiuse", len(diff["closed_positions"]))
    c3.metric("Aumentate", len(diff["increased"]))
    c4.metric("Diminuite", len(diff["decreased"]))
    render_detailed_diff_sections(diff)


# ---------------------------------------------------------------------------
# Page 5 — Holdings Search
# ---------------------------------------------------------------------------
elif page == "Holdings Search":
    st.title("Holdings Search")

    query_text = st.text_input("Cerca per nome issuer o CUSIP", placeholder="es. Apple, 037833100")

    if not query_text:
        st.info("Inserisci un termine di ricerca per iniziare.")
        st.stop()

    df = query("""
        SELECT
            issuer_name AS "Issuer",
            cusip       AS "CUSIP",
            fund_name   AS "Fund",
            filing_date AS "Filing Date",
            shares      AS "Azioni",
            value_usd   AS "Valore ($000s)",
            accession_number AS "Accession"
        FROM holdings
        WHERE issuer_name LIKE ? OR cusip LIKE ?
        ORDER BY filing_date DESC, value_usd DESC NULLS LAST
    """, (f"%{query_text}%", f"%{query_text}%"))

    if df.empty:
        st.warning(f"Nessun risultato per '{query_text}'")
        st.stop()

    st.success(f"{len(df)} risultati trovati")
    df["Valore"] = df["Valore ($000s)"].apply(fmt_value)
    df["Azioni"] = df["Azioni"].apply(lambda x: f"{int(x):,}" if pd.notna(x) and x else "-")

    st.download_button(
        "Scarica risultati CSV",
        dataframe_to_csv_bytes(df),
        file_name="f8_13f_search_results.csv",
        mime="text/csv",
    )
    st.dataframe(
        df[["Issuer", "CUSIP", "Fund", "Filing Date", "Azioni", "Valore"]],
        use_container_width=True,
        hide_index=True,
    )

    # Show which funds currently hold this asset (latest filing per fund)
    st.subheader("Chi la detiene oggi (ultimo filing per fondo)")
    latest = query("""
        SELECT h.fund_name AS "Fund", h.filing_date AS "Filing Date",
               h.shares AS "Azioni", h.value_usd AS "Valore ($000s)"
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
        latest["Valore"] = latest["Valore ($000s)"].apply(fmt_value)
        latest["Azioni"] = latest["Azioni"].apply(lambda x: f"{int(x):,}" if pd.notna(x) and x else "-")
        st.dataframe(latest[["Fund", "Filing Date", "Azioni", "Valore"]],
                     use_container_width=True, hide_index=True)
