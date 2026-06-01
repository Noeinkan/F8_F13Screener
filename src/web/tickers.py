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

_WORD_ALIASES = {
    "CORPORATION": "CORP",
    "INCORPORATED": "INC",
    "LIMITED": "LTD",
    "MANUFAC": "MFG",
    "MANUFACTURING": "MFG",
    "TECHNOLOGIES": "TECHNOLOGY",
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

    text = str(value).upper().replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    words = [_WORD_ALIASES.get(word, word) for word in text.split()]
    if drop_suffixes:
        words = [word for word in words if word not in _CORPORATE_SUFFIXES]
    if max_words is not None:
        words = words[:max_words]
    return " ".join(words)


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

    def resolve(self, issuer_name: Any) -> str:
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
    lookup: TickerLookup | None = None,
) -> pd.DataFrame:
    if df.empty or issuer_col not in df.columns:
        return df

    enriched_df = df.copy()
    ticker_lookup = lookup or get_ticker_lookup()
    tickers = enriched_df[issuer_col].apply(ticker_lookup.resolve)

    if ticker_col in enriched_df.columns:
        enriched_df[ticker_col] = tickers
    else:
        issuer_index = enriched_df.columns.get_loc(issuer_col)
        enriched_df.insert(issuer_index, ticker_col, tickers)
    return enriched_df