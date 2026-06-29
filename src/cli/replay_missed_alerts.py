"""
One-shot replay of missed 13F alerts.

Scans `seen_filings` for matched filings from the last N days, and re-sends
a Telegram alert for each one. Does NOT touch `seen_filings`, so the running
real-time poller keeps treating them as already-processed.

Idempotent via a local dedup file (data/realtime/replay_missed_alerts.sent.json).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import Config
from src.core.diff import compute_portfolio_diff
from src.core.notifier import TelegramNotifier
from src.core.paths import REALTIME_DATA_DIR
from src.core.storage import Storage

LOG = logging.getLogger("replay_missed_alerts")
REPLAY_DEDUP_FILE = REALTIME_DATA_DIR / "replay_missed_alerts.sent.json"
WINDOW_DAYS = int(os.environ.get("REPLAY_WINDOW_DAYS", "21"))


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )


def _load_dedup() -> set[str]:
    if not REPLAY_DEDUP_FILE.exists():
        return set()
    try:
        with REPLAY_DEDUP_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return {str(x) for x in data}
    except Exception as exc:  # noqa: BLE001
        LOG.warning("Dedup file unreadable, starting fresh: %s", exc)
    return set()


def _save_dedup(entries: set[str]) -> None:
    REPLAY_DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    with REPLAY_DEDUP_FILE.open("w", encoding="utf-8") as fh:
        json.dump(sorted(entries), fh, indent=2)


def _filing_index_url(cik: str, accession: str) -> str:
    cik_clean = (cik or "").lstrip("0") or "0"
    acc_clean = accession.replace("-", "")
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_clean}&type=13F-HR&dateb=&owner=include&count=40"


def _primary_doc_url(cik: str, accession: str) -> str:
    """Best-effort EDGAR filing-index URL (the bot already has access via /start)."""
    cik_int = (cik or "").lstrip("0") or "0"
    acc_clean = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/"


def _fetch_window_rows(storage: Storage, window_days: int):
    """Return seen_filings rows whose filing_date falls within the window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).date().isoformat()
    with storage._get_connection() as conn:  # noqa: SLF001 (intentional internal use)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT entry_id, filer_name, cik, filing_date, acceptance_datetime, processed_at
            FROM seen_filings
            WHERE matched = 1
              AND cik IS NOT NULL AND cik != ''
              AND filing_date IS NOT NULL AND filing_date != ''
              AND filing_date >= ?
            ORDER BY filing_date ASC
            """,
            (cutoff,),
        )
        return [dict(row) for row in cur.fetchall()]


def _resolve_fund_name(cik: str, hedge_funds: dict[str, str]) -> str:
    if not cik:
        return ""
    padded = cik.zfill(10)
    return hedge_funds.get(padded) or hedge_funds.get(cik) or cik


def _portfolio_diff_for(storage: Storage, cik: str, accession: str):
    try:
        prev_rows = storage.get_latest_accessions_for_fund(cik, limit=2) or []
    except Exception as exc:  # noqa: BLE001
        LOG.warning("latest_accessions_for_fund failed for %s: %s", cik, exc)
        prev_rows = []
    prev_accession = None
    for row in prev_rows:
        if row.get("accession_number") and row["accession_number"] != accession:
            prev_accession = row["accession_number"]
            break
    if not prev_accession:
        return None
    try:
        old_holdings = storage.get_holdings_by_accession(prev_accession) or {}
        new_holdings = storage.get_holdings_by_accession(accession) or {}
    except Exception as exc:  # noqa: BLE001
        LOG.warning("holdings fetch failed for %s vs %s: %s", prev_accession, accession, exc)
        return None
    if not old_holdings or not new_holdings:
        return None
    return compute_portfolio_diff(old_holdings, new_holdings)


def main() -> int:
    _setup_logging()
    try:
        config = Config.from_env()
        config.validate()
    except ValueError as exc:
        LOG.error("Config invalid: %s", exc)
        return 1

    storage = Storage(config.holdings_db)
    notifier = TelegramNotifier(
        config.telegram_bot_token,
        config.telegram_chat_id,
        config.max_retries,
        config.retry_delay,
    )

    rows = _fetch_window_rows(storage, WINDOW_DAYS)
    LOG.info("Window: last %s days | matched rows in seen_filings: %d", WINDOW_DAYS, len(rows))

    dedup = _load_dedup()
    sent_total = 0
    skipped_dedup = 0
    failed = 0

    for row in rows:
        entry_id = row["entry_id"] or ""
        cik = (row.get("cik") or "").strip()
        filer_name = row.get("filer_name") or ""
        filing_date = row.get("filing_date") or ""
        acceptance_dt = row.get("acceptance_datetime") or filing_date
        if not entry_id or not cik or not filing_date:
            continue
        if entry_id in dedup:
            skipped_dedup += 1
            continue

        # Reconstruct friendly name + filing URL. Accession is the last ':' segment
        # of entry_id (handles both `filing:CIK:ACC` and `submissions:CIK:ACC`).
        fund_name = _resolve_fund_name(cik, config.hedge_funds_cik)
        accession = entry_id.rsplit(":", 1)[-1]
        filing_url = _primary_doc_url(cik, accession)

        portfolio_diff = _portfolio_diff_for(storage, cik, accession)
        holdings_saved = portfolio_diff is not None

        ok = notifier.send_filing_alert(
            fund_name=fund_name,
            filer_name=filer_name,
            filing_date=acceptance_dt or filing_date,
            filing_url=filing_url,
            holdings_saved=holdings_saved,
            portfolio_diff=portfolio_diff,
        )
        if ok:
            sent_total += 1
            dedup.add(entry_id)
            LOG.info("Replayed %s | %s | %s", filing_date, fund_name or filer_name, accession)
        else:
            failed += 1
            LOG.error("Failed to replay %s | %s", entry_id, fund_name or filer_name)
            # Persist partial dedup so we don't retry successes after a hard fail.
            _save_dedup(dedup)
            return 2

        # Be friendly to Telegram rate limits and let the user actually read them.
        time.sleep(1.2)

    _save_dedup(dedup)
    LOG.info(
        "Done. sent=%d failed=%d skipped_dedup=%d total_in_window=%d",
        sent_total,
        failed,
        skipped_dedup,
        len(rows),
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
