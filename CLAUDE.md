# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

SEC 13F filing screener. Polls the SEC EDGAR RSS feed every 15 minutes, filters for ~53 tracked hedge funds by CIK, parses their holdings from the Information Table XML/HTML, stores everything in SQLite, fires Telegram alerts on matches, and computes quarter-over-quarter portfolio diffs.

## Commands

```powershell
# Install dependencies
pip install requests feedparser beautifulsoup4 lxml tenacity tqdm pandas pytest

# Main polling loop (polls every 15 min, sends Telegram alerts)
python -m src.cli.main

# Historical bulk processing (last 5 years, ~1000+ filings, resumable)
python -m src.cli.process_historical_13f

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_sec_client.py -v

# View cached filings (CLI)
python -m src.cli.view_cached_filings

# GUI for historical processing
python src/gui/filing_processor_gui.py
```

## Configuration

Credentials go in `config_secret.py` (gitignored). See `config_secret.template.py`.

Required fields: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SEC_USER_AGENT` (must be a real email — SEC requirement). Falls back to environment variables with the same names.

## Architecture and data flow

**Real-time monitoring loop:**
```
SECClient.fetch_13f_feed()           — RSS from SEC EDGAR (feedparser)
  ↓ RSS entries
FilingProcessor.process_feed()       — orchestrates everything (src/cli/main.py)
  ↓ CIK match via should_notify()
HoldingsParser.parse_information_table()  — XML → HTML fallback
  ↓ holdings list
Storage.save_holdings()              — SQLite insert
  ↓
compute_portfolio_diff()             — compares vs previous quarter's accession
  ↓
TelegramNotifier.send_filing_alert() — HTML-formatted Telegram message
  ↓
save_message_to_viewer()             — writes to MESSAGE_LOG_FILE for GUI
```

**Key modules:**
- `src/core/sec_client.py` — `SECClient`: fetches RSS, extracts CIK/accession with regex (LRU-cached), filters via `should_notify()`
- `src/core/parser.py` — `HoldingsParser`: 3-method search for Information Table URL; XML parse first, HTML fallback; priority-ordered header mapping to avoid ambiguous column names
- `src/core/storage.py` — `Storage`: SQLite CRUD for 3 tables; `get_latest_accessions_for_fund()` and `get_holdings_by_accession()` power the diff engine
- `src/core/notifier.py` — `TelegramNotifier`: Telegram API with retry; dates formatted in Italian locale
- `src/core/diff.py` — `compute_portfolio_diff()`: compares holdings dicts keyed by CUSIP; threshold 10% for increased/decreased; `format_diff_for_telegram()` produces HTML with emoji indicators
- `src/core/hedge_funds_config.py` — `HEDGE_FUNDS_CIK` dict: 53 funds in 3 categories (Value, Growth/Tech, Mega/Quant)
- `src/utils/message_bridge.py` — `save_message_to_viewer()`: writes Telegram messages to JSON for the GUI viewer
- `src/cli/telegram_commands.py` — daemon thread: processes `/start`, `/stop`, `/status` commands via Telegram; sets `pause_event` and `check_now_event` in the main loop

## Key design decisions

- **Mark-before-notify**: filings are written to `seen_filings` immediately after parsing, before the Telegram send. A notification failure never causes a re-process on the next poll cycle.
- **CIK-based filtering**: `should_notify()` extracts CIK from the filing URL (handles `/data/XXXXXX/` and `CIK=XXXXXX` patterns), strips leading zeros, and matches against `HEDGE_FUNDS_CIK`. Never match by fund name string.
- **Parser fallback chain**: `parse_information_table` tries XML (`_parse_xml_format`) first, then HTML (`_parse_html_format`). The HTML path uses priority-ordered header matching to avoid ambiguous column names (e.g., matches "VOTING AUTH. - SOLE" before "SOLE").
- **`paths.py` as single source of truth**: importing it auto-creates all required directories. Never hardcode paths elsewhere.
- **Holdings not deduped on insert**: each polling cycle writes fresh rows. `accession_number` is stored to enable manual dedup queries via `get_holdings_by_accession()`.
- **Threading for live control**: `pause_event` and `check_now_event` (threading.Event) let the Telegram command daemon pause/resume polling and force immediate checks without killing the process.

## Adding a new hedge fund

Edit `src/core/hedge_funds_config.py` — add to `HEDGE_FUNDS_CIK`:
```python
'0001234567': 'Fund Name (Manager Name)',
```
CIK must be zero-padded to 10 digits as it appears in SEC URLs.

## SQLite schema

| Table | Key columns |
|---|---|
| `seen_filings` | `entry_id` (PK), `filer_name`, `cik`, `filing_date`, `matched` |
| `holdings` | `fund_cik`, `filing_date`, `cusip`, `issuer_name`, `value_usd`, `shares`, `accession_number` |
| `statistics` | single row: `total_checked`, `matched`, `filtered` |

Indexes: `(fund_cik, filing_date)`, `(cusip, filing_date)`, `(filing_date)` on `seen_filings`, `(accession_number)` on `holdings`.
