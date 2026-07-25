"""Holdings-derived ticker→CUSIP index for dashboard search.

The dashboard's ``holdings`` table stores CUSIPs and 13F issuer names but no
ticker symbol. To make the search box accept tickers like ``ORAN`` or ``AAPL``,
we build a one-time index mapping ``ticker → {CUSIP, ...}`` by running the
existing ticker resolver (``src.web.tickers``) over each distinct
``(cusip, issuer_name)`` group in the holdings table.

The index is persisted to disk so we don't pay the resolution cost on every
API request, and is regenerated automatically when:

- the cache file is missing, or
- the source DuckDB ``mtime`` differs from the cache's recorded ``mtime``.

If the holdings DB or the SEC ticker reference is unreachable, the index
loader returns an empty mapping and the rest of the app still works (search
just falls back to issuer/CUSIP substring matching).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Iterable

from src.core.paths import DASHBOARD_DB_FILE
from src.web.tickers import get_ticker_lookup

logger = logging.getLogger(__name__)

CACHE_FILE = Path(DASHBOARD_DB_FILE).parent / "holdings_ticker_index.json"
# Anything that looks like a ticker search term: 1-5 letters, optional . - or
# digits. We intentionally reject CUSIP-shaped tokens (6+ digits) here so
# numeric searches don't accidentally trigger ticker lookup.
_TICKER_LIKE_RE = __import__("re").compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,4}$")
# NYSE/NASDAQ tickers are 1-5 chars and always start with a letter. We allow a
# small set of suffix characters (BRK.A, RDS-A, BF.B) commonly seen on US
# exchanges. We still validate the term has at least one alpha character so we
# don't treat pure-digit tokens as tickers.

# User-typed ticker aliases that the holdings index doesn't surface directly.
# These cover common cases where the SEC reference uses a different ticker
# than the one investors actually search for (sponsored vs. unsponsored
# ADRs, dual listings, etc.). The mapping points from user-typed → the
# canonical ticker key the index uses.
#
# The Orange SA entry is no longer needed: ``684060106 → ORAN`` lives in
# ``CUSIP_TICKER_OVERRIDES`` so the holdings index resolves ORAN directly.
# This table is kept as a documented extension point for future cases that
# can't be expressed as a CUSIP override (e.g. CIK-only resolutions).
TICKER_ALIASES: dict[str, str] = {}


def is_ticker_like(term: str) -> bool:
    """Return True if ``term`` looks like a stock ticker (e.g. ``AAPL``, ``BRK.B``)."""
    if not term:
        return False
    if len(term) > 5:
        return False
    if not _TICKER_LIKE_RE.match(term):
        return False
    return any(ch.isalpha() for ch in term)


def _index_path() -> Path:
    return CACHE_FILE


def _safe_source_mtime() -> int | None:
    """mtime of the DuckDB source (ns) or ``None`` if unavailable."""
    try:
        return DASHBOARD_DB_FILE.stat().st_mtime_ns
    except OSError:
        return None


def _read_cache(source_mtime: int) -> dict[str, list[str]] | None:
    path = _index_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read holdings ticker index cache %s: %s", path, exc)
        return None
    if not isinstance(payload, dict):
        return None
    cached_mtime = payload.get("source_mtime_ns")
    if cached_mtime != source_mtime:
        return None
    mapping = payload.get("ticker_to_cusips")
    if not isinstance(mapping, dict):
        return None
    return {str(k): [str(c) for c in v if c] for k, v in mapping.items() if v}


def _write_cache(source_mtime: int, mapping: dict[str, list[str]]) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_mtime_ns": source_mtime,
        "ticker_to_cusips": {k: sorted(set(v)) for k, v in mapping.items()},
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _build_from_holdings(source_mtime: int | None, read_db_path: Path) -> dict[str, list[str]]:
    """Build ticker→CUSIP index from the holdings DuckDB. Returns ``{}`` on any failure.

    The SELECT runs against ``read_db_path``. On the API that is the process's
    read-only snapshot, never the live writer DB, so building the index never
    contends with the poller/refresh for the DuckDB lock.
    """
    if source_mtime is None:
        return {}
    read_db_path = Path(read_db_path)
    if not read_db_path.exists():
        return {}

    try:
        import duckdb  # local import to keep this module light

        conn = duckdb.connect(str(read_db_path), read_only=True)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not open dashboard DB for ticker index: %s", exc)
        return {}

    try:
        df = conn.execute(
            """
            SELECT cusip, issuer_name
            FROM holdings
            WHERE cusip IS NOT NULL
              AND LENGTH(TRIM(cusip)) > 0
              AND issuer_name IS NOT NULL
              AND LENGTH(TRIM(issuer_name)) > 0
            """
        ).fetchdf()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not read holdings for ticker index: %s", exc)
        conn.close()
        return {}
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover - defensive
            pass

    if df.empty:
        return {}

    # Vectorized resolution: 1.15M rows × row-wise apply() is multi-minute
    # territory. We resolve by collapsing to distinct (cusip, issuer_name)
    # pairs first, then map back. This reduces the resolution work to the
    # number of unique pairs (~67k in production) instead of every row.
    try:
        lookup = get_ticker_lookup()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not build ticker lookup for index: %s", exc)
        return {}

    distinct = df.drop_duplicates(subset=["cusip", "issuer_name"])
    resolved: dict[tuple[str, str], str] = {}
    for cusip, issuer in zip(distinct["cusip"], distinct["issuer_name"]):
        cusip_key = str(cusip).strip().upper() if cusip is not None else ""
        issuer_key = "" if issuer is None else str(issuer)
        if not cusip_key or not issuer_key:
            continue
        ticker = lookup.resolve(issuer_key, cusip_key)
        if ticker:
            resolved[(cusip_key, issuer_key)] = str(ticker).strip().upper()

    if not resolved:
        return {}

    # Map each row's (cusip, issuer_name) back to a ticker.
    cusip_col = df["cusip"].astype(str).str.strip().str.upper()
    issuer_col = df["issuer_name"].astype(str)

    mapping: dict[str, set[str]] = {}
    for cusip, issuer in zip(cusip_col, issuer_col):
        ticker = resolved.get((cusip, issuer))
        if not ticker:
            continue
        mapping.setdefault(ticker, set()).add(cusip)

    return {t: sorted(cusips) for t, cusips in mapping.items() if cusips}


_index_lock = threading.Lock()
_index_cache: dict[str, list[str]] | None = None
_index_cache_key: tuple[str, int | None] | None = None


def _load_index(read_db_path: Path | str | None = None) -> dict[str, list[str]]:
    """Load (and lazily build) the holdings-derived ticker index.

    ``read_db_path`` is where the SELECT runs (default: the live DB, used by the
    standalone Streamlit app). The API passes its per-process read-only snapshot
    so the index build never opens the live writer DB. Cache *validity* is keyed
    on the live DB's mtime (the data version, stable across restarts), not the
    snapshot's — a fresh snapshot copy on every API restart must not force an
    expensive rebuild.

    The result is cached in-process (one entry, auto-invalidated when the data
    version changes); the on-disk cache is the persistence layer across restarts.
    """
    global _index_cache, _index_cache_key
    read_path = Path(read_db_path) if read_db_path else DASHBOARD_DB_FILE
    version_mtime = _safe_source_mtime()
    key = (str(read_path), version_mtime)
    with _index_lock:
        if _index_cache is not None and _index_cache_key == key:
            return _index_cache

        cached = _read_cache(version_mtime) if version_mtime is not None else None
        if cached is not None:
            _index_cache, _index_cache_key = cached, key
            return _index_cache

        fresh = _build_from_holdings(version_mtime, read_path)
        if version_mtime is not None and fresh:
            try:
                _write_cache(version_mtime, fresh)
            except OSError as exc:
                logger.warning("Could not persist holdings ticker index: %s", exc)
        _index_cache, _index_cache_key = fresh, key
        return _index_cache


def invalidate_ticker_index() -> None:
    """Clear both the in-process and on-disk ticker index caches."""
    global _index_cache, _index_cache_key
    with _index_lock:
        _index_cache = None
        _index_cache_key = None
        path = _index_path()
        if path.exists():
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("Could not delete ticker index cache %s: %s", path, exc)
        # Also clear the lru_cache-wrapped public accessor so the next call
        # actually re-invokes ``_load_index`` rather than returning stale data.
        try:
            get_ticker_index.cache_clear()
        except AttributeError:  # pragma: no cover - defensive
            pass


def get_ticker_index(read_db_path: Path | str | None = None) -> dict[str, list[str]]:
    """Public accessor for the ticker→CUSIP index (read-only dict of lists).

    Pass ``read_db_path`` (e.g. the API's read-only snapshot) to build the index
    without touching the live writer DB; defaults to the live DB.
    """
    return dict(_load_index(read_db_path))


def _resolve_term_to_ticker(term: str, read_db_path: Path | str | None = None) -> str:
    """Resolve a user-typed ticker term to the canonical ticker key the
    holdings index uses, consulting the alias table as a fallback.
    """
    cleaned = term.strip().upper()
    if not cleaned:
        return ""
    index = get_ticker_index(read_db_path)
    if cleaned in index:
        return cleaned
    aliased = TICKER_ALIASES.get(cleaned)
    if aliased and aliased in index:
        return aliased
    # Last resort: try the alias key even if it doesn't appear in the index —
    # the downstream cusips_for_ticker() lookup will simply return [].
    return aliased or cleaned


def cusips_for_ticker(ticker: str, read_db_path: Path | str | None = None) -> list[str]:
    """Return the CUSIPs registered against ``ticker`` (case-insensitive).

    Falls back to the alias table for tickers the user types that the
    holdings index doesn't know directly (e.g. ``ORAN`` → ``ORANY``).
    """
    if not ticker:
        return []
    cleaned = ticker.strip().upper()
    if not cleaned:
        return []
    index = get_ticker_index(read_db_path)
    if cleaned in index:
        return list(index[cleaned])
    aliased = TICKER_ALIASES.get(cleaned)
    if aliased and aliased in index:
        return list(index[aliased])
    return []


def expand_ticker_terms(terms: Iterable[str], read_db_path: Path | str | None = None) -> list[str]:
    """For each ticker-shaped term, return the CUSIPs it maps to.

    Non-ticker-shaped terms are skipped (the search filter still applies the
    ILIKE clauses for those). Duplicate CUSIPs across terms are removed while
    preserving order.
    """
    seen: set[str] = set()
    cusips: list[str] = []
    for term in terms:
        if not is_ticker_like(term):
            continue
        for cusip in cusips_for_ticker(term, read_db_path):
            if cusip not in seen:
                seen.add(cusip)
                cusips.append(cusip)
    return cusips