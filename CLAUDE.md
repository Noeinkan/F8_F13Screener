# CLAUDE.md

Compact working notes for this repo.

See [PROJECT_INDEX.md](PROJECT_INDEX.md) first for the shortest route to the current repo map.

## Project

SEC 13F screener: poll SEC EDGAR RSS, filter tracked hedge funds by CIK, parse Information Table XML/HTML, store parsed holdings in canonical DuckDB (with SQLite runtime compatibility state), send Telegram alerts, and compare quarter-over-quarter portfolios.

## Commands

```powershell
# Install deps
rtk pip install -r requirements.txt

# Main poller
rtk python -m src.main alerts

# Dashboard (canonical — React + FastAPI)
rtk python -m src.main dashboard
powershell -ExecutionPolicy Bypass -File .\dev.ps1

# Dashboard status — what is currently serving?
rtk python -m src.main status

# Legacy Streamlit dashboard (opt-in only)
rtk python -m src.main dashboard-streamlit
rtk python -m src.main dashboard-streamlit -Port 8503
rtk python -m src.main dashboard-streamlit -RebuildDb

# Historical refresh + dashboard DB
rtk python -m src.cli.process_historical_13f full --yes

# Optional CSV export from canonical DuckDB
rtk python -m src.cli.process_historical_13f export --export-scope both

# Tests
rtk pytest tests/ -v

# Single test file
rtk pytest tests/test_sec_client.py -v

# Cached filings viewer
rtk python -m src.cli.view_cached_filings

# Historical GUI
python src/gui/filing_processor_gui.py

# Local dashboard restart (thin wrapper: pre-flight port cleanup + dev.ps1)
.\dashboard.bat
.\dashboard.bat -Streamlit           # opt into legacy Streamlit
```

## Dashboard

The canonical dashboard is **React + FastAPI**, launched with **one** command:

- Windows: `.\dev.ps1` (or `rtk python -m src.main dashboard`)
- Anywhere: `rtk python -m src.main dashboard`

This always:
- pre-frees ports 5173-5179, 9001, 9002, 8501, 8502, 3000 via `scripts/_free_ports.ps1`
  so a stale listener never wins the race (use `-SkipFreePorts` to opt out).
- starts FastAPI on `http://127.0.0.1:9001` by default (`python -m src.api`); on the
  Hetzner VPS the API is pinned to **port 9002** via `API_SERVER_PORT` because another
  FastAPI app on that host already owns 9001 — Vite's `/api` proxy is driven by
  `F8_API_PROXY_TARGET` (see `deploy/f8-web.service`) so the same code runs locally
  and remotely.
- starts the Vite dev server on `http://127.0.0.1:5173` (proxies `/api` to the API)

If the UI looks stale, **first run** `rtk python -m src.main status`. It shows
which of the known ports (5173, 9001, 8501, 8502, 3000) are currently LISTENing,
the owning PID, and the command line, plus a one-line summary like
`Dashboard (React+FastAPI): running on http://127.0.0.1:5173 — api pid X, web pid Y`
or `stopped` / `partial`.

`dashboard.bat` is now a thin wrapper that runs `_free_ports.ps1` and then
delegates to `dev.ps1`. The legacy `start:no-browser` / `node server.js` paths
have been removed from `package.json` — there is no other way to bring the
dashboard up besides `dev.ps1` or `python -m src.main dashboard`. `npm start`
still works (it runs the same `concurrently` recipe) but `dev.ps1` is the
recommended entrypoint on Windows because of the pre-flight cleanup.

### Hetzner VPS deployment

On `77.42.70.26` the dashboard is exposed via two systemd services
(`f8-api` on 9002, `f8-web` on 5173) and UFW allows 5173 + 9002. The
legacy Streamlit service (`f8-dashboard.service`, port 8502) has been
**removed from the repo and disabled on the host** — the canonical URLs are:

- Web UI: `http://77.42.70.26:5173/`
- API:   `http://77.42.70.26:9002/`

`deploy/deploy.sh` and `deploy/install.sh` install Node.js + frontend deps,
register `f8-api.service` and `f8-web.service`, and remove the legacy
`f8-dashboard.service` if it still exists on the host. New deploys will
keep the canonical stack in sync.

If the DuckDB is stale or missing, rebuild with `rtk python -m src.cli.process_historical_13f full --yes`.
Dashboard analytics read from `src/core/data/13f_dashboard.duckdb` (DuckDB).
API layer lives in `src/api/`; React UI in `frontend/`.

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
- `src/api/`: FastAPI JSON analytics API (no Streamlit imports).
- `frontend/`: React + Vite dashboard UI.
- `src/web/dashboard.py`: legacy Streamlit dashboard (no longer deployed on the Hetzner VPS; opt-in only locally via `python -m src.main dashboard-streamlit`).
- `deploy/f8-api.service`, `deploy/f8-web.service`: systemd units for the FastAPI API (port 9002 on Hetzner) and the Vite/React web UI (port 5173).
- `deploy/f8-screener.service`: systemd unit for the realtime poller.
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

- DuckDB `src/core/data/13f_dashboard.duckdb`, table `holdings`, is the canonical store for parsed holdings.
- SEC submissions/cache and historical catalog files are discovery metadata, not holdings truth.
- CSV exports and dashboard snapshots are derived/rebuildable artifacts.
- `processed_filings_tracking.json` is audit/optimization state only; DuckDB row coverage decides whether holdings exist.
- SQLite tables such as `seen_filings` and `statistics` remain realtime alert state; SQLite `holdings` is compatibility storage, not dashboard truth.
- If `diagnose-consistency` reports a small mismatch set, run `rtk python -m src.cli.process_historical_13f holdings --yes` and re-check; if mismatches are broad, open a separate repair backlog.

## Adding a Fund

Add a zero-padded 10-digit CIK entry to `src/core/hedge_funds_config.py`:

```python
'0001234567': 'Fund Name (Manager Name)',
```
