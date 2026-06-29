# F8 13F Screener

For a compact repo map, see [PROJECT_INDEX.md](PROJECT_INDEX.md).

SEC 13F screener that:

- monitors SEC filings for tracked hedge funds (CIK-based matching),
- parses holdings (XML first, HTML fallback),
- stores realtime and historical data,
- sends Telegram alerts,
- serves a local React + FastAPI dashboard (legacy Streamlit still available).

## Quick Start (Windows PowerShell)

From the repository root:

```powershell
# 1) Activate venv
.\.venv\Scripts\Activate.ps1

# 2) Install dependencies
rtk pip install -r requirements.txt

# 3) Launch dashboard (React + FastAPI)
python -m src.main dashboard
```

Dashboard URLs:

- Web UI: http://localhost:5173
- API: http://localhost:9001

Legacy Streamlit (port 8502):

```powershell
python -m src.main dashboard-streamlit
```

## Canonical Entrypoints

Use these commands from the repo root:

```powershell
# Dashboard (React + FastAPI)
python -m src.main dashboard
python -m src.main web
npm start

# Legacy Streamlit
python -m src.main dashboard-streamlit

# Realtime alert poller
python -m src.main alerts

# Historical processing (DuckDB canonico)
python -m src.cli.process_historical_13f full --yes
```

Legacy Streamlit options:

```powershell
python -m src.main dashboard-streamlit -Port 8503
python -m src.main dashboard-streamlit -RebuildDb
python -m src.main dashboard-streamlit -RebuildDb -FullRefresh -Workers 2
```

Legacy wrapper (still supported):

```powershell
bash deploy.sh
.\dashboard.bat
```

## What The Dashboard Launcher Does

When you run `python -m src.main dashboard`, it starts:

- FastAPI on port 9001 (`python -m src.api`)
- Vite dev server on port 5173 (`frontend/`), proxying `/api` to the API

Legacy Streamlit (`python -m src.main dashboard-streamlit`) still uses the Windows restart script and opens port 8502.

## Common Workflows

Refresh dashboard data from SEC:

```powershell
python -m src.cli.process_historical_13f full --yes
```

Optional historical CSV export from DuckDB:

```powershell
python -m src.cli.process_historical_13f export --export-scope both
```

Run tests:

```powershell
rtk pytest tests/ -v
rtk pytest tests/test_sec_client.py -v
```

View cached filings:

```powershell
python -m src.cli.view_cached_filings
```

## Configuration

Create local secrets in `config_secret.py` using `config_secret.template.py` as reference.

Required values:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SEC_USER_AGENT` (must include a real contact email to satisfy SEC requirements)

## Data Locations

- Main app data: `data/`
- Realtime outputs: `data/realtime/`
- Historical catalog/holdings: `data/historical/`
- Export CSVs: `data/exports/`
- Logs: `src/core/logs/`
- Dashboard DB snapshots/cache: `cache/dashboard/`

## Troubleshooting

If `run .\dashboard.bat` fails with a `Start-Process` path error:

- do not use `run` (it may map to NVM's `run.cmd`),
- use `python -m src.main dashboard` or `.\dashboard.bat` directly.

If dashboard fails to load in time:

- check the new Streamlit console window for stack traces,
- verify port availability (`8502` by default),
- retry with another port (`-Port 8503`).

If dashboard data looks stale or malformed:

- rebuild with `python -m src.main dashboard -RebuildDb`, or
- run full historical refresh with `python -m src.cli.process_historical_13f full --yes`.

## Project Layout (High Value)

- `src/main.py`: unified command entrypoint (`dashboard`, `alerts`)
- `src/cli/main.py`: realtime polling + Telegram integration
- `src/cli/process_historical_13f.py`: historical pipeline + dashboard DB refresh
- `src/core/sec_client.py`: SEC feed/submissions access and ID extraction
- `src/core/parser.py`: information table parsing
- `src/core/storage.py`: SQLite persistence
- `src/web/dashboard.py`: Streamlit dashboard
