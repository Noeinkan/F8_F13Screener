# CLAUDE.md

Compact working notes for this repo.

## Project

SEC 13F screener: poll SEC EDGAR RSS, filter tracked hedge funds by CIK, parse Information Table XML/HTML, store holdings in SQLite, send Telegram alerts, and compare quarter-over-quarter portfolios.

## Commands

```powershell
# Install deps
rtk pip install -r requirements.txt

# Main poller
rtk python -m src.cli.main

# Historical refresh + dashboard DB
rtk python -m src.cli.process_historical_13f full --yes --save-db

# Fast local rebuild of dashboard DB from historical CSV (no SEC re-fetch)
rtk python -m src.cli.process_historical_13f bootstrap-dashboard-db

# Tests
rtk pytest tests/ -v

# Single test file
rtk pytest tests/test_sec_client.py -v

# Cached filings viewer
rtk python -m src.cli.view_cached_filings

# Historical GUI
python src/gui/filing_processor_gui.py

# Local dashboard restart + browser open
.\dashboard.bat
.\dashboard.bat -Port 8503
.\dashboard.bat -RebuildDb
.\dashboard.bat -RebuildDb -FullRefresh -Workers 2
```

## Dashboard

- `dashboard.bat` calls `scripts/restart_dashboard.ps1`.
- It kills any old dashboard instance, clears the port, starts Streamlit, waits for `/_stcore/health`, then opens the browser.
- If the SQLite DB is malformed, rebuild with `rtk python -m src.cli.process_historical_13f full --yes --save-db` or `./dashboard.bat -RebuildDb`.
- Dashboard analytics now read from `src/core/data/13f_dashboard.duckdb` (DuckDB). CSV exports remain optional artifacts.
- For local pre-deploy smoke check: verify SQLite integrity, then run `./dashboard.bat`.

## Config

- Secrets live in `config_secret.py` using `config_secret.template.py` as reference.
- Required fields: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SEC_USER_AGENT`.
- `SEC_USER_AGENT` must be a real email to satisfy SEC requirements.

## High-Value Files

- `src/cli/main.py`: real-time polling loop.
- `src/cli/process_historical_13f.py`: historical catalog/holdings pipeline and dashboard DB refresh.
- `src/core/sec_client.py`: RSS + filing URL / accession / CIK extraction.
- `src/core/parser.py`: Information Table parsing; XML first, HTML fallback.
- `src/core/storage.py`: SQLite storage and accession lookup helpers.
- `src/core/diff.py`: portfolio diff helpers for Telegram and dashboard history views.
- `src/web/dashboard.py`: Streamlit dashboard (`Overview`, `Fund Detail`, `Fund History`, `Portfolio Diff`, `Holdings Search`).
- `src/core/hedge_funds_config.py`: tracked funds list.

## Rules

- Match tracked funds by CIK only, never by fund name.
- `HoldingsParser` tries XML first, then HTML fallback.
- `paths.py` is the single source of truth for data paths and directory creation.
- `seen_filings` is written before Telegram notification; send failures must not cause re-processing.
- Dashboard comparisons are normalized positions, not raw rows.
- Normalization key is CUSIP when present, otherwise `issuer_name|share_class|put_call`.
- `compute_portfolio_diff()` stays Telegram-friendly; dashboard history uses `compute_detailed_portfolio_diff()` and `compute_quarterly_history_transitions()`.

## Data Notes

- Main SQLite tables: `seen_filings`, `holdings`, `statistics`.
- `holdings` stores `accession_number` so quarter snapshots and diffs can be rebuilt later.
- Holdings are not deduped across polling cycles on insert.

## Adding a Fund

Add a zero-padded 10-digit CIK entry to `src/core/hedge_funds_config.py`:

```python
'0001234567': 'Fund Name (Manager Name)',
```
