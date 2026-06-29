"""DuckDB repository for the dashboard API (no Streamlit)."""

from __future__ import annotations

import json
import logging
import os
import threading
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd

from src.api.exceptions import DashboardDbError
from src.core.dashboard_snapshot import resolve_dashboard_snapshot
from src.core.dashboard_storage import DashboardStorage
from src.core.diff import build_position_key, compute_quarterly_history_transitions
from src.core.hedge_funds_config import HEDGE_FUNDS_CIK
from src.core.paths import DASHBOARD_DB_FILE
from src.web.instrument_transforms import build_fund_instrument_history
from src.web.sql_queries import FUND_HISTORY_POSITIONS_SQL, NORMALIZED_DIFF_SQL
from src.web.value_units import infer_value_multiplier_from_frame

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = DASHBOARD_DB_FILE
TRACKED_FUND_NAMES = sorted(HEDGE_FUNDS_CIK.values())
FUND_NAME_TO_CIK = {name: cik for cik, name in HEDGE_FUNDS_CIK.items()}
CACHE_DIR = PROJECT_ROOT / "cache"
DASHBOARD_SNAPSHOT_PATH = CACHE_DIR / "dashboard" / f"13f_dashboard.{os.getpid()}.snapshot.duckdb"

logger = logging.getLogger(__name__)

# Cache the resolved snapshot path keyed by the live DB's mtime so we only
# re-copy the (potentially large) DuckDB file when the source actually changes.
# Without this, every API request copied the whole DB and defeated the
# `_get_storage_cached` lru_cache because the snapshot's mtime_ns changed on
# every copy. Concurrent requests share this cache under a single lock.
_snapshot_lock = threading.Lock()
_snapshot_cache: dict[str, tuple[int, str, str | None]] = {}


def _resolve_snapshot_cached() -> tuple[Path, int, str | None]:
    source_path = DB_PATH
    if not source_path.exists():
        raise DashboardDbError(f"Database not found: {source_path}")
    source_mtime = source_path.stat().st_mtime_ns
    cache_key = str(source_path)

    with _snapshot_lock:
        cached = _snapshot_cache.get(cache_key)
        if cached and cached[0] == source_mtime:
            _, resolved_path_str, warning = cached
            return Path(resolved_path_str), source_mtime, warning

    resolved_path, warning = resolve_dashboard_snapshot(source_path, DASHBOARD_SNAPSHOT_PATH)
    with _snapshot_lock:
        _snapshot_cache[cache_key] = (
            source_mtime,
            str(resolved_path),
            warning,
        )
    return resolved_path, source_mtime, warning


def get_dashboard_db_state() -> tuple[str, int, str | None]:
    resolved_path, snapshot_version, warning = _resolve_snapshot_cached()
    snapshot_version = resolved_path.stat().st_mtime_ns
    return str(resolved_path), snapshot_version, warning


@lru_cache(maxsize=4)
def _get_storage_cached(db_path_raw: str, snapshot_version: int) -> DashboardStorage:
    db_path = Path(db_path_raw)
    if not db_path.exists():
        raise DashboardDbError(f"Database not found: {db_path}")

    storage = DashboardStorage(db_path)
    health = storage.get_health_snapshot()
    if health["total_rows"] > 0 and health["only_all_fund"]:
        raise DashboardDbError(
            "Degenerate dataset: contains only fund_name=ALL. "
            "Rebuild the dashboard DB from the historical pipeline."
        )
    return storage


def initialize_dashboard_storage() -> tuple[DashboardStorage, Path, str | None]:
    try:
        db_path_raw, snapshot_version, warning = get_dashboard_db_state()
        storage = _get_storage_cached(db_path_raw, snapshot_version)
        return storage, Path(db_path_raw), warning
    except (duckdb.Error, OSError, RuntimeError, DashboardDbError) as exc:
        if isinstance(exc, DashboardDbError):
            raise
        raise DashboardDbError(str(exc)) from exc


def clear_repository_cache() -> None:
    _get_storage_cached.cache_clear()
    with _snapshot_lock:
        _snapshot_cache.clear()


def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    try:
        storage, _, _ = initialize_dashboard_storage()
        return storage.query_df(sql, params)
    except (duckdb.Error, pd.errors.DatabaseError) as exc:
        preview = " ".join(sql.split())[:240]
        raise DashboardDbError(f"{exc} | Query: {preview}") from exc


def get_fund_options() -> list[str]:
    db_funds = query("SELECT DISTINCT fund_name FROM holdings ORDER BY fund_name")
    db_names: list[str] = []
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
        with cache_file.open("r", encoding="utf-8") as handle:
            cached_data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read filing cache %s: %s", cache_file, exc)
        return pd.DataFrame(columns=["accession_number", "filing_date"])

    if not isinstance(cached_data, dict):
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
        value_multiplier = infer_value_multiplier_from_frame(
            group,
            value_col="value_usd",
            shares_col="shares",
        )
        portfolio_value_usd = None if portfolio_value is None else float(portfolio_value) * value_multiplier
        label = f"{filing_date} ({accession_number})"
        summary_rows.append({
            "Filing Date": filing_date,
            "Accession": accession_number,
            "Label": label,
            "Normalized Positions": len(group),
            "Raw 13F Lines": int(group["raw_lines"].fillna(0).sum()),
            "Portfolio Value ($000s)": portfolio_value,
            "Portfolio Value (USD)": portfolio_value_usd,
            "Value Multiplier": value_multiplier,
        })
        snapshots.append({
            "filing_date": filing_date,
            "accession_number": accession_number,
            "label": label,
            "positions": positions,
        })

    summary_df = pd.DataFrame(summary_rows).sort_values("Filing Date").reset_index(drop=True)
    summary_df["Filing Date Dt"] = pd.to_datetime(summary_df["Filing Date"])
    transitions = compute_quarterly_history_transitions(snapshots, min_change_pct=0)
    return summary_df, transitions


def load_fund_instrument_history(fund: str) -> pd.DataFrame:
    rows = query(FUND_HISTORY_POSITIONS_SQL, (fund,))
    return build_fund_instrument_history(rows)
