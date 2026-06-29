"""Best-effort ticker enrichment for dashboard display tables."""

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.core.paths import CACHE_DIR


SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
TICKER_REFERENCE_FILE = Path(CACHE_DIR) / "sec_company_tickers_exchange.json"

logger = logging.getLogger(__name__)

# CUSIP -> ticker overrides for issuers whose SEC reference name maps to more
# than one ticker (typically multi-share-class companies such as Alphabet).
# Consulted before the name-based lookup so ambiguous names still resolve.
CUSIP_TICKER_OVERRIDES: dict[str, str] = {
    # Alphabet Inc
    "02079K305": "GOOG",   # Class C
    "02079K107": "GOOGL",  # Class A
    # Berkshire Hathaway (SEC reference lists both BRK-A and BRK-B under one
    # name, so name-based lookup is ambiguous).
    "084670108": "BRK-A",  # Class A
    "084670702": "BRK-B",  # Class B
    # News Corp
    "65157J106": "NWSA",   # Class A
    "65157J205": "NWS",    # Class B
    # Fox Corp / Twenty-First Century Fox dual class
    "337538106": "FOXA",   # Class A
    "337539208": "FOX",    # Class B
    # Discovery / Warner Bros. Discovery legacy share classes
    "25746U109": "DISCA",  # Class A
    "25746U208": "DISCK",  # Class C
    # Lennar Corp
    "526057104": "LEN",    # Class A
    "526057302": "LENB",   # Class B
    # ---- ETFs ----
    # SEC `company_tickers_exchange.json` only registers a handful of ETFs
    # (mostly SPDR/iShares commodity and crypto trusts). Most broad-market and
    # sector ETFs held by 13F funds are missing from the reference, and SPY's
    # 13F issuer name ("STATE STR SPDR S&P 500 ETF T") does not alias-match
    # the SEC's "SPDR S&P 500 ETF TRUST" record. CUSIP overrides close both
    # gaps. CUSIPs verified against each fund's official fact sheet.
    "78462F103": "SPY",   # SPDR S&P 500 ETF Trust
    "464287200": "IVV",   # iShares Core S&P 500 ETF
    "922908363": "VOO",   # Vanguard S&P 500 ETF
    "922908769": "VTI",   # Vanguard Total Stock Market ETF
    "464287655": "IWM",   # iShares Russell 2000 ETF
    "464287234": "EEM",   # iShares MSCI Emerging Markets ETF
    "464287465": "EFA",   # iShares MSCI EAFE ETF
    "922908736": "VUG",   # Vanguard Growth ETF
    "922908744": "VTV",   # Vanguard Value ETF
    "921908844": "VIG",   # Vanguard Dividend Appreciation ETF
    "921937835": "BND",   # Vanguard Total Bond Market ETF
}

_CORPORATE_SUFFIXES = {
    "ADS",
    "ADR",
    "AND",
    "CO",
    "COM",
    "CORP",
    "CORPORATION",
    "INC",
    "INCORPORATED",
    "LTD",
    "LIMITED",
    "PLC",
    "SA",
    "SE",
    "SPONSORED",
    "THE",
}

# Words that add no discriminative value when comparing issuer names.
# Dropped (along with corporate suffixes) when building alias keys so that
# "BANK AMERICA CORP" (13F) and "BANK OF AMERICA CORP" (SEC reference)
# normalize to the same alias key.
_NAME_NOISE_WORDS = {
    "OF",
    "THE",
    "AND",
}

_WORD_ALIASES = {
    "CORPORATION": "CORP",
    "INCORPORATED": "INC",
    "LIMITED": "LTD",
    "MANUFAC": "MFG",
    "MANUFACTURING": "MFG",
    "TECHNOLOGIES": "TECHNOLOGY",
    # 13F filings frequently abbreviate "INTERNATIONAL" as "INTL".
    "INTL": "INTERNATIONAL",
    "INTLS": "INTERNATIONAL",
    "GRP": "GROUP",
    "HLDG": "HOLDINGS",
    "HLDGS": "HOLDINGS",
}


def _sec_user_agent() -> str:
    try:
        from config_secret import SEC_USER_AGENT

        if SEC_USER_AGENT:
            return SEC_USER_AGENT
    except ImportError:
        pass
    return os.getenv("SEC_USER_AGENT", "F8 13F Screener ticker enrichment")


def _normalize_issuer_key(value: Any, *, drop_suffixes: bool = False, max_words: int | None = None) -> str:
    if value is None or value is pd.NA:
        return ""

    # Strip SEC jurisdiction suffixes like "/DE/", "/MA/", "/CAN/" that would
    # otherwise leak into the normalized key as spurious state-code tokens
    # (e.g. "BANK OF AMERICA CORP /DE/" -> "BANK OF AMERICA CORP DE").
    text = str(value).upper().replace("&", " AND ")
    text = re.sub(r"\s*/[A-Z0-9]+/\s*", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    words = [_WORD_ALIASES.get(word, word) for word in text.split()]
    if drop_suffixes:
        words = [word for word in words if word not in _CORPORATE_SUFFIXES and word not in _NAME_NOISE_WORDS]
    if max_words is not None:
        words = words[:max_words]
    return " ".join(words)


def _sorted_alias_key(value: Any) -> str:
    """Word-order-insensitive alias key (suffixes + noise words dropped).

    Lets "DISNEY WALT CO" (13F) match "WALT DISNEY CO" (SEC reference) without
    requiring an exact word-order match. Only used as a last-resort alias.
    """
    normalized = _normalize_issuer_key(value, drop_suffixes=True)
    if not normalized:
        return ""
    return " ".join(sorted(normalized.split()))


def _normalize_cusip(value: Any) -> str:
    if value is None or value is pd.NA:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _unique_mapping(candidates: dict[str, set[str]]) -> dict[str, str]:
    return {
        key: next(iter(tickers))
        for key, tickers in candidates.items()
        if key and len(tickers) == 1
    }


def _listed_exchange(value: Any) -> str:
    return str(value or "").strip().upper()


def _is_plain_common_ticker(ticker: str) -> bool:
    return bool(ticker) and "-" not in ticker and "." not in ticker and "/" not in ticker


def _preferred_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        name_key = _normalize_issuer_key(row.get("name"))
        ticker = str(row.get("ticker") or "").strip().upper()
        if name_key and ticker:
            normalized_row = dict(row)
            normalized_row["ticker"] = ticker
            rows_by_name[name_key].append(normalized_row)

    preferred = []
    for grouped_rows in rows_by_name.values():
        candidates = [
            row
            for row in grouped_rows
            if _listed_exchange(row.get("exchange")) in {"NYSE", "NASDAQ", "NYSE AMERICAN"}
        ] or grouped_rows
        plain_candidates = [row for row in candidates if _is_plain_common_ticker(str(row.get("ticker") or ""))]
        preferred.extend(plain_candidates or candidates)
    return preferred


@dataclass(frozen=True)
class TickerLookup:
    exact: dict[str, str]
    aliases: dict[str, str]

    def resolve(self, issuer_name: Any, cusip: Any = None) -> str:
        if cusip is not None:
            cusip_key = _normalize_cusip(cusip)
            if cusip_key and (ticker := CUSIP_TICKER_OVERRIDES.get(cusip_key)):
                return ticker

        exact_key = _normalize_issuer_key(issuer_name)
        if not exact_key:
            return ""
        if ticker := self.exact.get(exact_key):
            return ticker

        alias_keys = [
            _normalize_issuer_key(issuer_name, drop_suffixes=True),
            _normalize_issuer_key(issuer_name, max_words=4),
            _normalize_issuer_key(issuer_name, drop_suffixes=True, max_words=4),
            _normalize_issuer_key(issuer_name, max_words=3),
            _normalize_issuer_key(issuer_name, drop_suffixes=True, max_words=3),
            _sorted_alias_key(issuer_name),
        ]
        for key in alias_keys:
            if ticker := self.aliases.get(key):
                return ticker
        return ""


def build_ticker_lookup(rows: list[dict[str, Any]]) -> TickerLookup:
    exact_candidates: dict[str, set[str]] = defaultdict(set)
    alias_candidates: dict[str, set[str]] = defaultdict(set)

    for row in _preferred_rows(rows):
        ticker = str(row.get("ticker") or "").strip().upper()
        name = row.get("name")
        if not ticker or not name:
            continue

        exact_candidates[_normalize_issuer_key(name)].add(ticker)
        for key in {
            _normalize_issuer_key(name, drop_suffixes=True),
            _normalize_issuer_key(name, max_words=4),
            _normalize_issuer_key(name, drop_suffixes=True, max_words=4),
            _normalize_issuer_key(name, max_words=3),
            _normalize_issuer_key(name, drop_suffixes=True, max_words=3),
            _sorted_alias_key(name),
        }:
            alias_candidates[key].add(ticker)

    return TickerLookup(
        exact=_unique_mapping(exact_candidates),
        aliases=_unique_mapping(alias_candidates),
    )


def _rows_from_sec_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    fields = payload.get("fields") or []
    data = payload.get("data") or []
    if not fields or not data:
        return []

    return [dict(zip(fields, row)) for row in data]


def _download_ticker_reference() -> list[dict[str, Any]]:
    response = requests.get(
        SEC_COMPANY_TICKERS_URL,
        headers={"User-Agent": _sec_user_agent()},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    TICKER_REFERENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TICKER_REFERENCE_FILE.write_text(json.dumps(payload), encoding="utf-8")
    return _rows_from_sec_payload(payload)


def load_ticker_reference_rows() -> list[dict[str, Any]]:
    if TICKER_REFERENCE_FILE.exists():
        try:
            payload = json.loads(TICKER_REFERENCE_FILE.read_text(encoding="utf-8"))
            return _rows_from_sec_payload(payload)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read ticker reference cache %s: %s", TICKER_REFERENCE_FILE, exc)

    try:
        return _download_ticker_reference()
    except requests.RequestException as exc:
        logger.warning("Could not download SEC ticker reference: %s", exc)
        return []


@lru_cache(maxsize=1)
def get_ticker_lookup() -> TickerLookup:
    return build_ticker_lookup(load_ticker_reference_rows())


def add_ticker_column(
    df: pd.DataFrame,
    *,
    issuer_col: str = "Issuer",
    ticker_col: str = "Ticker",
    cusip_col: str = "CUSIP",
    lookup: TickerLookup | None = None,
) -> pd.DataFrame:
    if df.empty or issuer_col not in df.columns:
        return df

    enriched_df = df.copy()
    ticker_lookup = lookup or get_ticker_lookup()
    cusip_series = enriched_df[cusip_col] if cusip_col in enriched_df.columns else None

    def _resolve(row: pd.Series) -> str:
        issuer = row[issuer_col]
        cusip = row[cusip_col] if cusip_series is not None else None
        return ticker_lookup.resolve(issuer, cusip)

    tickers = enriched_df.apply(_resolve, axis=1)

    if ticker_col in enriched_df.columns:
        enriched_df[ticker_col] = tickers
    else:
        issuer_index = enriched_df.columns.get_loc(issuer_col)
        enriched_df.insert(issuer_index, ticker_col, tickers)
    return enriched_df