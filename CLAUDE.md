# F8_F13Screener — CLAUDE.md

## What this project does

SEC 13F filing screener. Polls the SEC EDGAR RSS feed every 15 minutes, filters for ~53 tracked hedge funds by CIK, parses their holdings from the Information Table XML/HTML, stores everything in SQLite, and fires Telegram alerts on matches.

## Project layout

```
src/
  core/
    config.py          — Config dataclass; loads from config_secret.py or env vars
    paths.py           — All file paths (single source of truth); auto-creates dirs on import
    hedge_funds_config.py — HEDGE_FUNDS_CIK dict (CIK → fund name); ~53 funds in 3 categories
    sec_client.py      — SECClient: RSS feed fetch, CIK extraction, match filter
    parser.py          — HoldingsParser: finds Information Table URL, parses XML then HTML fallback
    storage.py         — Storage: SQLite CRUD (seen_filings, holdings, statistics tables)
    notifier.py        — TelegramNotifier: sends alerts and daily summaries
  cli/
    main.py            — FilingProcessor orchestrator + polling loop (entry point)
    process_historical_13f.py — Bulk-download historical 13F data
    view_cached_filings.py    — CLI viewer for stored filings
  gui/
    filing_processor_gui.py   — Tkinter GUI for historical processing
    telegram_viewer.py        — Tkinter GUI for viewing Telegram messages
```

## Data directories (auto-created by paths.py)

```
src/core/data/
  realtime/       — last_13f_check_v2.json, holdings CSV export
  historical/
    catalog/      — historical_13f_catalog_5years.json
    holdings/     — 13f_holdings_5years.csv
    tracking/     — checkpoint and metrics JSON files
  messages/       — telegram_messages.json
  cache/          — filing cache
src/core/logs/    — 13f_alerts.log (rotating, 10MB × 5)
src/core/data/13f_holdings.db — SQLite database
```

## Configuration

Credentials go in `config_secret.py` (gitignored). See `config_secret.template.py`.

Required fields:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SEC_USER_AGENT` — must be a real email (SEC requirement)

Fallback: environment variables with the same names.

## Running

```powershell
# Main loop (polls every 15 min, sends Telegram alerts)
python -m src.cli.main

# Historical bulk processing
python -m src.cli.process_historical_13f

# GUI for historical processing
python src/gui/filing_processor_gui.py

# View cached filings
python -m src.cli.view_cached_filings
```

## Key design decisions

- **CIK-based filtering** (`should_notify` in `sec_client.py`): matches by CIK extracted from the filing URL, not by name string. Leading zeros are stripped for flexible matching.
- **Mark-before-notify**: filings are written to `seen_filings` immediately after parsing (before the Telegram send), so a notification failure never causes a re-send.
- **Parser fallback chain**: `parse_information_table` tries XML (`_parse_xml_format`) first, then HTML table (`_parse_html_format`). The HTML path uses a priority-ordered header mapping to avoid ambiguous column names.
- **Holdings deduplication**: not deduped on insert — each polling cycle that finds a new filing writes a fresh set of rows. `accession_number` is stored for manual dedup queries.
- **`paths.py` as single source of truth**: importing `paths.py` creates all directories. Do not hardcode paths elsewhere.

## Adding a new hedge fund

Edit `src/core/hedge_funds_config.py` — add an entry to `HEDGE_FUNDS_CIK`:
```python
'0001234567': 'Fund Name (Manager Name)',
```
CIK must be zero-padded to 10 digits as it appears in SEC URLs.

## SQLite schema (quick ref)

| Table | Key columns |
|---|---|
| `seen_filings` | `entry_id` (PK), `filer_name`, `cik`, `filing_date`, `matched` |
| `holdings` | `fund_cik`, `filing_date`, `cusip`, `issuer_name`, `value_usd`, `shares` |
| `statistics` | single row: `total_checked`, `matched`, `filtered` |

Indexes: `(fund_cik, filing_date)`, `(cusip, filing_date)`, `(filing_date)` on seen_filings.

## Dependencies

`requests`, `feedparser`, `beautifulsoup4`, `lxml` (for XML parser), `tkinter` (stdlib).
Install: `pip install requests feedparser beautifulsoup4 lxml`
