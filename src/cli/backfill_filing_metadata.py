"""
Backfill 13F cover-page metadata into the dashboard DuckDB ``filings`` table.

For every filing the storage reports as missing metadata:

1. offline, fill ``form_type`` from the local historical catalog (and learn the
   filing's ``primary_document``, used to build the cover page URL);
2. online, download the raw ``primary_doc.xml`` cover page from SEC — one
   request per filing, at most 5 per second — and store period of report,
   amendment type and the filer's table entry/value totals.

Usage::

    python -m src.cli.backfill_filing_metadata --dry-run --limit 10
    python -m src.cli.backfill_filing_metadata --fund "Scion"
    python -m src.cli.backfill_filing_metadata --offline-only
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests

from src.core.dashboard_storage import DashboardStorage
from src.core.filing_cover import cover_page_url, fetch_cover_page
from src.core.paths import CATALOG_FILE, DASHBOARD_DB_FILE

logger = logging.getLogger(__name__)

MAX_REQUESTS_PER_SECOND = 5
BATCH_SIZE = 50
PLACEHOLDER_USER_AGENT = 'YourName yourname@email.com'
MISMATCH_PREVIEW_ROWS = 20

_CIK_IN_URL = re.compile(r'/edgar/data/(\d+)/')


class RateLimiter:
    """Spaces calls at least ``1 / max_per_second`` seconds apart."""

    def __init__(
        self,
        max_per_second: float = MAX_REQUESTS_PER_SECOND,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.min_interval = 1.0 / max_per_second
        self._clock = clock
        self._sleep = sleep
        self._next_allowed: Optional[float] = None

    def wait(self) -> None:
        now = self._clock()
        if self._next_allowed is not None and now < self._next_allowed:
            self._sleep(self._next_allowed - now)
            now = self._next_allowed
        self._next_allowed = now + self.min_interval


@dataclass
class BackfillSummary:
    selected: int = 0
    catalog_matched: int = 0
    offline_updated: int = 0
    fetched: int = 0
    updated: int = 0
    failed: int = 0
    amendments: Counter = field(default_factory=Counter)
    mismatches: Optional[List[dict]] = None
    failed_accessions: List[str] = field(default_factory=list)


def resolve_user_agent() -> Optional[str]:
    """SEC User-Agent, looked up like ``Config.from_env``: config_secret first, then the environment."""
    try:
        from config_secret import SEC_USER_AGENT  # type: ignore[import-not-found]
        candidate = SEC_USER_AGENT
    except ImportError:
        candidate = None
    candidate = (candidate or os.getenv('SEC_USER_AGENT') or '').strip()
    if not candidate or candidate == PLACEHOLDER_USER_AGENT:
        return None
    return candidate


def load_catalog_index(catalog_path: str | Path) -> Dict[str, dict]:
    """Catalog entries keyed by accession number; empty when the file is missing or unreadable."""
    path = Path(catalog_path)
    if not path.exists():
        logger.warning("Catalog not found at %s; skipping the offline step", path)
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("Catalog at %s unreadable (%s); skipping the offline step", path, exc)
        return {}
    entries = payload.get('filings', []) if isinstance(payload, dict) else payload
    return {
        entry['accession_number']: entry
        for entry in entries or []
        if isinstance(entry, dict) and entry.get('accession_number')
    }


def select_filings(storage, limit: Optional[int], fund: Optional[str]) -> List[dict]:
    if not fund:
        return list(storage.get_filings_missing_metadata(limit))
    # The limit applies to the fund's filings, so filter before truncating.
    needle = fund.casefold()
    rows = [
        row for row in storage.get_filings_missing_metadata(None)
        if needle in (row.get('fund_name') or '').casefold()
    ]
    return rows[:limit] if limit is not None else rows


def _fund_cik(row: dict, catalog_entry: Optional[dict]) -> Optional[str]:
    for candidate in (row.get('fund_cik'), (catalog_entry or {}).get('cik')):
        if candidate and str(candidate).strip().isdigit():
            return str(candidate).strip()
    match = _CIK_IN_URL.search(row.get('filing_url') or '')
    return match.group(1) if match else None


def _write(storage, records: List[dict]) -> int:
    result = storage.upsert_filing_metadata_many(records)
    return result if isinstance(result, int) else len(records)


def run_backfill(
    storage,
    *,
    session=None,
    user_agent: Optional[str] = None,
    limit: Optional[int] = None,
    fund: Optional[str] = None,
    dry_run: bool = False,
    offline_only: bool = False,
    catalog_path: str | Path = CATALOG_FILE,
    rate_limiter: Optional[RateLimiter] = None,
    batch_size: int = BATCH_SIZE,
    out: Callable[[str], None] = print,
) -> BackfillSummary:
    summary = BackfillSummary()
    rows = select_filings(storage, limit, fund)
    summary.selected = len(rows)
    out(f"Filings missing metadata: {len(rows)}" + (f" (fund filter: {fund!r})" if fund else ''))

    # Step 1, offline: form type and primary document from the local catalog.
    catalog = load_catalog_index(catalog_path)
    offline_records = []
    for row in rows:
        entry = catalog.get(row.get('accession_number'))
        if not entry:
            continue
        summary.catalog_matched += 1
        if entry.get('form') and not row.get('form_type'):
            offline_records.append({'accession_number': row['accession_number'], 'form_type': entry['form']})
    out(f"Catalog matches: {summary.catalog_matched}; form types to fill offline: {len(offline_records)}")
    if offline_records:
        if dry_run:
            for record in offline_records:
                out(f"  [dry-run] {record['accession_number']} form_type={record['form_type']}")
        else:
            for start in range(0, len(offline_records), batch_size):
                summary.offline_updated += _write(storage, offline_records[start:start + batch_size])

    # Step 2, online: one cover page request per filing.
    if not offline_only and rows:
        if session is None or not user_agent:
            raise ValueError("fetching cover pages needs a session and an SEC User-Agent")
        limiter = rate_limiter or RateLimiter()
        pending: List[dict] = []

        def flush() -> None:
            batch = pending[:]
            pending.clear()
            if batch:
                summary.updated += _write(storage, batch)

        try:
            for index, row in enumerate(rows, start=1):
                accession = row.get('accession_number')
                entry = catalog.get(accession)
                cik = _fund_cik(row, entry)
                if not accession or not cik:
                    logger.warning("Skipping %r: no accession number or fund CIK", accession)
                    summary.failed += 1
                    summary.failed_accessions.append(str(accession))
                    continue

                url = cover_page_url(cik, accession, (entry or {}).get('primary_document'))
                limiter.wait()
                cover = fetch_cover_page(session, url, user_agent)
                if cover is None:
                    summary.failed += 1
                    summary.failed_accessions.append(accession)
                    continue

                summary.fetched += 1
                if cover.is_amendment:
                    summary.amendments[cover.amendment_type or 'UNKNOWN'] += 1
                record = {
                    'accession_number': accession,
                    'form_type': cover.submission_type,
                    'period_of_report': cover.period_of_report,
                    'amendment_type': cover.amendment_type,
                    'table_entry_total': cover.table_entry_total,
                    'table_value_total': cover.table_value_total,
                }
                record = {key: value for key, value in record.items() if value is not None}

                if dry_run:
                    out(
                        f"  [dry-run] {index}/{len(rows)} {accession} {row.get('fund_name', '')}: "
                        + ', '.join(f"{k}={v}" for k, v in record.items() if k != 'accession_number')
                    )
                    continue
                pending.append(record)
                if len(pending) >= batch_size:
                    flush()
                    out(f"  {index}/{len(rows)} processed, {summary.updated} written")
        finally:
            # An interrupted run keeps what it already downloaded.
            if not dry_run:
                flush()

    getter = getattr(storage, 'get_entry_count_mismatches', None)
    summary.mismatches = list(getter()) if callable(getter) else None

    _print_summary(summary, dry_run=dry_run, offline_only=offline_only, out=out)
    return summary


def _print_summary(summary: BackfillSummary, *, dry_run: bool, offline_only: bool, out: Callable[[str], None]) -> None:
    out('')
    out('Summary' + (' (dry run, nothing written)' if dry_run else ''))
    out(f"  selected:        {summary.selected}")
    out(f"  catalog matches: {summary.catalog_matched}")
    out(f"  offline updated: {summary.offline_updated}")
    if not offline_only:
        out(f"  fetched:         {summary.fetched}")
        out(f"  updated:         {summary.updated}")
        out(f"  failed:          {summary.failed}")
        if summary.failed_accessions:
            out(f"    e.g. {', '.join(summary.failed_accessions[:5])}")
        if summary.amendments:
            by_type = ', '.join(f"{kind}={count}" for kind, count in sorted(summary.amendments.items()))
            out(f"  amendments:      {by_type}")
        else:
            out("  amendments:      none")
    if summary.mismatches is None:
        out("  entry-count mismatches: not available (storage has no get_entry_count_mismatches)")
    else:
        out(f"  entry-count mismatches: {len(summary.mismatches)}")
        for row in summary.mismatches[:MISMATCH_PREVIEW_ROWS]:
            out('    ' + ', '.join(f"{key}={value}" for key, value in row.items()))
        if len(summary.mismatches) > MISMATCH_PREVIEW_ROWS:
            out(f"    ... {len(summary.mismatches) - MISMATCH_PREVIEW_ROWS} more")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='python -m src.cli.backfill_filing_metadata',
        description='Fill period of report, amendment type and table totals from each filing\'s 13F cover page.',
    )
    parser.add_argument('--limit', type=int, default=None, help='process at most N filings')
    parser.add_argument('--fund', default=None, help='only funds whose name contains this text (case-insensitive)')
    parser.add_argument('--dry-run', action='store_true', help='fetch and print, write nothing')
    parser.add_argument('--offline-only', action='store_true', help='only the local catalog step, no SEC requests')
    parser.add_argument('--verbose', action='store_true', help='log every failed request')
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    # Fund names are not all ASCII; don't let a Windows code page end the run.
    reconfigure = getattr(sys.stdout, 'reconfigure', None)
    if callable(reconfigure):
        try:
            reconfigure(encoding='utf-8')
        except (ValueError, OSError):
            pass
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(levelname)s %(name)s: %(message)s',
    )
    if args.limit is not None and args.limit < 1:
        print("--limit must be a positive number", file=sys.stderr)
        return 2

    user_agent = None
    if not args.offline_only:
        user_agent = resolve_user_agent()
        if not user_agent:
            print(
                "SEC_USER_AGENT is not set. Put it in config_secret.py or the SEC_USER_AGENT "
                "environment variable (a name and a real email, as SEC requires).",
                file=sys.stderr,
            )
            return 2

    storage = DashboardStorage(Path(DASHBOARD_DB_FILE))
    if not callable(getattr(storage, 'get_filings_missing_metadata', None)):
        print("This DashboardStorage has no filings metadata table yet (get_filings_missing_metadata).", file=sys.stderr)
        return 2

    session = None if args.offline_only else requests.Session()
    try:
        summary = run_backfill(
            storage,
            session=session,
            user_agent=user_agent,
            limit=args.limit,
            fund=args.fund,
            dry_run=args.dry_run,
            offline_only=args.offline_only,
        )
    finally:
        if session is not None:
            session.close()
    return 1 if summary.failed else 0


if __name__ == '__main__':
    sys.exit(main())
