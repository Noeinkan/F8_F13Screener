# F8 F13 Screener Product Brief

## Executive Summary

F8 F13 Screener is a self-hosted Python application that monitors SEC EDGAR for Form 13F-HR filings from a fixed watchlist of tracked hedge funds, downloads each Information Table, parses it into normalized holdings, persists the data, and pushes alerts and analytics through Telegram and a React + FastAPI dashboard.

- Single-repo project at the repository root (`README.md`, `CLAUDE.md`, `PROJECT_INDEX.md`, `src/`, `frontend/`, `tests/`, `deploy/`, `data/`, `scripts/`).
- Two coordinated pipelines: a long-running real-time poller (`src/cli/main.py`) and a historical rebuild pipeline (`src/cli/process_historical_13f.py`).
- Two storage backends: SQLite for runtime alert state (`src/core/storage.py`) and DuckDB as the canonical store for parsed holdings (`src/core/dashboard_storage.py`).
- Canonical UI is React + Vite + Mantine served through FastAPI (`src/api/app.py`, `frontend/src/App.tsx`); a legacy Streamlit dashboard (`src/web/dashboard.py`) remains available for local opt-in.
- Production deployment is wired via three systemd units on Hetzner (`deploy/f8-api.service`, `deploy/f8-web.service`, `deploy/f8-screener.service`).

## Problem it Solves

- 13F-HR filings are public on EDGAR but are spread across filing index pages and per-filer information tables, with no off-the-shelf push feed that filters to a specific fund list.
- The codebase reduces three recurring manual tasks to automation:
  - Watching EDGAR for new 13F-HR filings filed by a configured watchlist of institutional managers.
  - Pulling each filing's Information Table, parsing it into a clean row-per-position dataset, and storing it for later querying.
  - Producing quarter-over-quarter portfolio deltas (new positions, closed positions, materially increased/decreased positions) so a user can react quickly to disclosures.
- All alert and dashboard logic is keyed on CIK (zero-padded 10-digit Central Index Key), not on filer name; the README rule "Match tracked funds by CIK only, never by fund name" is enforced in `src/core/sec_client.py` (`should_notify`, `fetch_recent_13f_for_cik`) and tests in `tests/test_sec_client.py`.

## What it Does

- Polls SEC for new filings in two ways, then merges them:
  - `SECClient.fetch_recent_13f_for_cik` queries `data.sec.gov/submissions/CIK<CIK>.json` for each tracked CIK and returns recent `13F-HR` / `13F-HR/A` entries with form, filing date, accession number, primary document, and constructed EDGAR filing-index URL (`src/core/sec_client.py`).
  - `SECClient.fetch_13f_feed` falls back to the EDGAR Atom RSS feed when `enable_atom_fallback` is true (`src/core/config.py`, `src/cli/main.py`).
- Discovers the Information Table inside each filing index page via `HoldingsParser.get_information_table_url` (`src/core/parser.py`), which prefers rows explicitly labelled "INFORMATION TABLE" (XML over HTML), then links containing `infotable`, then a final XML fallback that excludes `primary_doc.xml`.
- Parses the Information Table using XML first (`HoldingsParser._parse_xml_format`) and falls back to HTML table parsing (`_parse_html_format`, `_map_table_headers`, `_parse_table_row`); produces a list of normalized holding dictionaries with fields `issuer_name, share_class, cusip, figi, value_x1000, value, shares_raw, shares, sh_prn, put_call, investment_discretion, other_manager, voting_authority_sole/shared/none`.
- Persists each new filing's holdings to both DuckDB (`DashboardStorage.save_holdings`, canonical) and SQLite (`Storage.save_holdings`, compatibility). Writes a `seen_filings` row before notification so Telegram failures do not cause reprocessing (`src/cli/main.py:_process_holdings`).
- Computes a quarter-over-quarter portfolio diff via `compute_portfolio_diff` and `compute_detailed_portfolio_diff` in `src/core/diff.py`; the Telegram-friendly output is produced by `format_diff_for_telegram` (≤5 items per section, ≥10% share-change threshold by default, see `MIN_CHANGE_PCT` and `MAX_ITEMS_PER_SECTION`).
- Sends an HTML-formatted Telegram message per filing via `TelegramNotifier.send_filing_alert` (`src/core/notifier.py`), and also accepts inbound Telegram commands (`/start`, `/stop`, `/status`, `/help`) through `TelegramCommandHandler` (`src/core/telegram_commands.py`) using long polling on `getUpdates`.
- Serves a dashboard through:
  - `src/api/app.py` — FastAPI app factory; routers mounted for `/api/health`, `/api/db/state`, `/api/cache/refresh`, `/api/cache/refresh/status`, `/api/funds`, `/api/admin/statistics`, `/api/overview/{summary,funds,recent-filings,filings-timeline,top-held,exports/full,exports/latest}`, `/api/funds/{fund}/{accessions,history,history/export,accessions/{accession}/holdings,accessions/{accession}/holdings/export,compare,compare/export/{section},compare/charts/sankey,compare/charts/lanes}`, `/api/holdings/{search,search/export}`, `/api/consensus/{trends,trends/export}`.
  - `frontend/src/App.tsx` — React Router shell with routes `/`, `/fund-analysis`, `/consensus-trends`, `/holdings-search`; `frontend/package.json` uses Mantine 8, React Query 5, Plotly.js 3, React Table 8.
- Provides CSV export endpoints that read from DuckDB (`FULL_HOLDINGS_EXPORT_SQL`, `LATEST_SNAPSHOT_EXPORT_SQL` in `src/web/sql_queries.py`).
- Lets a user trigger a full rebuild of the canonical DuckDB from inside the dashboard by calling `POST /api/cache/refresh`, which spawns `python -m src.cli.process_historical_13f full --yes` in a detached subprocess and returns a job handle (`src/api/refresh.py`, `src/api/routers/meta.py`).
- Includes a Tkinter-based local Telegram Message Viewer (`src/gui/telegram_viewer.py`) launched on startup when `auto_launch_viewer` is true; it shows the last ~100 messages saved by `src/utils/message_bridge.py`.
- Provides three deploy-time systemd units and a single deploy script (`deploy/deploy.sh`) that clones/updates the repo on `root@77.42.70.26` and pins the API to port 9002 because another FastAPI app on the host already owns 9001.

## Target Users

- A single operator (or a small group) who runs the tool locally or on the Hetzner VPS referenced in `deploy/f8-api.service`, configures their own Telegram bot and chat ID in `config_secret.py`, and curates the fund list in `src/core/hedge_funds_config.py`.
- The operator is the same person consuming Telegram alerts (the chat ID is the only authorized sender/receiver in `TelegramCommandHandler._dispatch`).
- The application is not multi-tenant: there is no per-user authentication in the API (`src/api/settings.py` only configures CORS origins) and no login in the dashboard; everything is bound to a single Telegram chat ID and the operator's local machine.

## Inputs

- Required secrets in `config_secret.py` (template at `config_secret.template.py`):
  - `TELEGRAM_BOT_TOKEN` — Telegram bot token from @BotFather.
  - `TELEGRAM_CHAT_ID` — the single authorized chat ID.
  - `SEC_USER_AGENT` — SEC requires a real contact email per `README.md` and `Config.validate()`.
- Optional environment overrides consumed by `Config.from_env` (`src/core/config.py`):
  - `F13F_POLL_INTERVAL_SECONDS` (default 120).
  - `F13F_AUTO_LAUNCH_VIEWER`, `F13F_ENABLE_FILTERED_DAILY_SUMMARY`.
  - `F13F_SUBMISSIONS_RECENT_LIMIT` (default 10), `F13F_SUBMISSIONS_REQUEST_DELAY_SECONDS` (default 1.0), `F13F_ENABLE_ATOM_FALLBACK`.
  - `REPLAY_WINDOW_DAYS` for `src/cli/replay_missed_alerts.py` (default 21).
- API server overrides (`src/api/settings.py`): `API_SERVER_ADDRESS` (default `127.0.0.1`), `API_SERVER_PORT` (default `9001`, pinned to `9002` on Hetzner), `API_RELOAD`, `CORS_ORIGINS`, `F8_API_PROXY_TARGET` (Vite proxy target), `F8_API_PUBLIC_PORT`.
- Watchlist: the dictionary `HEDGE_FUNDS_CIK` in `src/core/hedge_funds_config.py`. As shipped it contains zero-padded 10-digit CIK entries for roughly 60 funds grouped into value investing, growth/tech, and mega funds/quant. `get_total_funds()` returns the current count.
- Historical period: `CUTOFF_DATE = '2020-01-01'` and CLI overrides `--start-date` / `--end-date` for the historical pipeline (`src/cli/process_historical_13f.py`).
- HTTP endpoints used:
  - `https://data.sec.gov/submissions/CIK<10-digit>.json` (per CIK).
  - `https://www.sec.gov/Archives/edgar/data/<cik>/<acc_no_dashes>/<acc>-index.htm` (filing index).
  - The Information Table URL discovered from that index.
  - `https://api.telegram.org/bot<token>/sendMessage`, `/getUpdates`, `/deleteWebhook`.

## Outputs

- Telegram HTML messages per filing alert, generated by `TelegramNotifier.send_filing_alert`, including the matched fund name, filer name, formatted date (Italian month abbreviations in `_format_date`), filing link, "Holdings salvate" confirmation, and any portfolio-diff section produced by `format_diff_for_telegram` (Nuove posizioni, Posizioni chiuse, Variazioni significative with arrow + percentage + share counts).
- Optional daily summary messages (`send_daily_summary`) listing top filers among the unmatched filings from the previous day, gated by `enable_filtered_daily_summary`.
- SQLite database `data/13f_holdings.db` with tables `seen_filings`, `holdings`, `statistics` (schema in `src/core/storage.py`).
- DuckDB database `data/13f_dashboard.duckdb` (single `holdings` table, schema in `src/core/dashboard_storage.py`).
- Historical catalog JSON at `data/historical/catalog/historical_13f_catalog_5years.json` and per-CIK filing cache under `data/cache/<CIK>.json` (24h TTL).
- Tracking JSON at `data/historical/tracking/processed_filings_tracking.json`; processing metrics JSON `processing_metrics.json`; runtime state JSON `data/realtime/last_13f_check_v2.json`.
- Per-process dashboard snapshot at `cache/dashboard/13f_dashboard.<pid>.snapshot.duckdb` produced by `src/core/dashboard_snapshot.py:resolve_dashboard_snapshot`.
- CSV exports via `process_historical_13f.py export` (e.g. `data/exports/f8_13f_all_holdings.csv`, `data/exports/f8_13f_latest_snapshot.csv`) and inline CSV downloads from each FastAPI endpoint.
- Telegram message log JSON consumed by the Tkinter viewer at `data/messages/telegram_messages.json` (rolling last 100 messages).
- Rotating log file `logs/13f_alerts.log` (10 MB × 5 backups via `RotatingFileHandler` in `src/cli/main.py`).
- Refresh-job log files at `logs/refresh_<unix_ts>_<pid>.log` from backgrounded `process_historical_13f.py full` runs.

## Benefits & Value Proposition

- Two-stage alert pipeline with deduplication: `seen_filings` is written before Telegram send, so transient Telegram outages cannot cause duplicate alerts (`src/cli/main.py:mark_filing_seen` is called before `notifier.send_filing_alert`).
- Canonical holdings store in DuckDB with SQLite fallback, plus reconciliation tools:
  - `process_historical_13f.py diagnose-consistency` compares discovery metadata, tracking JSON, and DuckDB row counts (`build_holdings_consistency_report`).
  - `process_historical_13f.py backfill-values` re-parses filings whose holdings were saved without a value column.
  - `_needs_holdings_backfill` in `src/cli/main.py` triggers a backfill on the next cycle if SQLite has rows but DuckDB does not.
- Quarter-over-quarter diff helpers explicitly separate "Telegram-friendly" (`compute_portfolio_diff` + `format_diff_for_telegram`) from "dashboard-rich" (`compute_detailed_portfolio_diff` + `compute_quarterly_history_transitions`), and the position identity used for matching is CUSIP-first with an `issuer_name|share_class|put_call` fallback (`build_position_key` in `src/core/diff.py`, `POSITION_KEY_SQL` in `src/web/sql_queries.py`).
- The dashboard uses per-process DuckDB snapshots on Windows so the live writer process and the read process do not contend for file locks (`src/core/dashboard_snapshot.py`); the FastAPI layer caches the snapshot resolution by source-mtime to avoid re-copying the database on every request (`src/api/repository.py:_resolve_snapshot_cached`).
- On Windows, `dashboard.bat` / `dev.ps1` pre-emptively kill any stale listener on ports 5173-5179, 9001, 8501, 8502, 3000 via `scripts/_free_ports.ps1`, so a prior crashed process cannot win the port race.
- The system exposes a typed HTTP surface (FastAPI + Pydantic models on routers) so the React frontend, future programmatic clients, or `httpx` tests can use the same data pipeline.
- Test coverage covers SEC client extraction, parser XML/HTML paths, SQLite storage CRUD, diff math, dashboard snapshotting, API health, API fund analysis, API parity with the Streamlit version, and refresh status (`tests/test_sec_client.py`, `tests/test_parse_information_table.py`, `tests/test_storage.py`, `tests/test_diff.py`, `tests/test_dashboard_snapshot.py`, `tests/test_api_health.py`, `tests/test_api_fund_analysis.py`, `tests/test_api_parity.py`, `tests/test_api_refresh.py`).

## Typical Workflow

- Install: `rtk pip install -r requirements.txt` from the repo root; `npm --prefix frontend install` (run automatically by `dev.ps1` if missing).
- Configure: `cp config_secret.template.py config_secret.py` and set the three required values; adjust `src/core/hedge_funds_config.py` to add or remove CIKs.
- Refresh data once: `python -m src.cli.process_historical_13f full --yes` (writes catalog JSON, parses all filings since 2020-01-01 into DuckDB; default `--save-db` is on, `--save-csv` is opt-in).
- Launch dashboard (canonical): `python -m src.main dashboard` or `dashboard.bat` / `dev.ps1`. This frees ports, starts FastAPI on `http://127.0.0.1:9001`, and starts Vite on `http://127.0.0.1:5173` (proxying `/api`).
- Run the realtime poller: `python -m src.cli.main` (entry point referenced as `python -m src.main alerts` in the docs). It iterates the CIK list, calls `process_submissions` and `process_feed_fallback` in `src/cli/main.py`, marks each filing as seen, parses and saves holdings, then sends a Telegram alert with the diff.
- Operate via Telegram: the bot accepts `/stop` (pause polling), `/start` (resume and trigger an immediate check), `/status` (running/paused + last check timestamp), `/help`. Only the configured `chat_id` is honored.
- Use the dashboard: browse Overview / Fund Analysis / Consensus Trends / Holdings Search, optionally trigger a full DB rebuild from the top bar (`POST /api/cache/refresh` under the hood), download CSVs from any of the `/export` routes.
- Deploy to Hetzner: `bash deploy/deploy.sh [--skip-tests] [--rebuild-db] [--workers N]` clones/updates `/opt/F8_F13Screener`, installs requirements + frontend deps, and restarts `f8-screener`, `f8-api`, `f8-web`. Optional `--rebuild-db` triggers an in-place historical full refresh and CSV export after deployment.
- Tear down / inspect state: `python -m src.main status` lists which of the known dashboard ports (5173, 9001, 8501, 8502, 3000) are LISTENing along with PID and command line.

## Technical Foundation

- Language: Python 3 with `requests`, `feedparser`, `beautifulsoup4` (+ `lxml`), `tenacity`, `tqdm`, `duckdb`, `pandas`, `fastapi` (+ `uvicorn[standard]`), `pydantic`, `streamlit`, `plotly`, `psutil` (only in the Tkinter viewer), and `pytest`/`httpx` for tests (see `requirements.txt`).
- Frontend stack: React 18 + TypeScript + Vite 6, Mantine 8 (`@mantine/core`, `@mantine/hooks`), TanStack React Query 5, TanStack React Table 8, Plotly.js 3 + `react-plotly.js`, React Router 6 (`frontend/package.json`, `frontend/vite.config.ts`).
- Concurrency: `concurrent.futures.ThreadPoolExecutor` / `ProcessPoolExecutor` in `process_historical_13f.py`, gated by a `TokenBucketRateLimiter` defaulting to 10 req/s (SEC rate-limit guidance) and configurable via `--rate` / `--capacity`.
- HTTP clients: `requests.Session` in `SECClient` with a retry loop (`max_retries=3`, `retry_delay=60` by default). The historical pipeline additionally wraps `requests.get` in `tenacity.retry` (`stop_after_attempt(3)`, exponential wait).
- Storage:
  - SQLite tables `seen_filings (entry_id PK, filer_name, cik, filing_date, acceptance_datetime, processed_at, matched)`, `holdings (id PK, filing_date, fund_name, fund_cik, accession_number, filing_url, acceptance_datetime, issuer_name, share_class, cusip, figi, value_x1000, value_usd, shares_raw, shares, sh_prn, put_call, investment_discretion, other_manager, other_managers_raw, all_columns_raw, voting_authority_sole/shared/none, created_at)`, and `statistics (id=1, total_checked, matched, filtered, last_match_date, last_update)` (`src/core/storage.py`).
  - DuckDB single `holdings` table mirroring the SQLite schema in `src/core/dashboard_storage.py` with indexes on `accession_number`, `(fund_name, filing_date)`, and `cusip`.
- Path/data location single source of truth: `src/core/paths.py` (`DASHBOARD_DB_FILE = data/13f_dashboard.duckdb`, `HOLDINGS_DB_FILE = data/13f_holdings.db`, `LAST_CHECK_FILE`, `CATALOG_FILE`, `HISTORICAL_HOLDINGS_CSV`, `PROCESSED_TRACKING_FILE`, `MESSAGE_LOG_FILE`, etc.). `paths.py` creates each directory at import time.
- Configuration: `src/core/config.py:Config` dataclass with `Config.from_env()` reading either `config_secret.py` or env vars, `Config.validate()` rejecting placeholder values. Runtime overrides flow through `F13F_*` env vars; API settings flow through `src/api/settings.py`.
- HTTP API composition: `src/api/app.py:create_app()` registers CORS middleware and includes routers from `src.api.routers.{meta, overview, exports, holdings, funds, consensus}`. Dashboard storage is reached through `src/api/repository.py` which wraps DuckDB with an `lru_cache(maxsize=4)` keyed on `(db_path, snapshot_version)` plus a snapshot-resolution cache guarded by a threading lock.
- Telegram control channel: `src/core/telegram_commands.py:TelegramCommandHandler` runs in a daemon thread, polls `getUpdates` with a 30s long-poll, calls `deleteWebhook` on startup, treats HTTP 401 as fatal (disables commands for the process), treats HTTP 409 as transient (waits 60s, logs once), and only dispatches commands whose `chat.id` equals the configured `chat_id`.
- Logging: `RotatingFileHandler` (10 MB × 5) for the realtime poller; rotating, timestamped log files for refresh jobs in `logs/`; `StreamHandler` to console; `disable_web_page_preview=True` on Telegram messages.

## Current Limitations & Boundaries

- Telegram dependency: alerts and the two-way control channel require valid `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`. When the token returns HTTP 401 the notifier sets `_disabled_due_to_unauthorized = True` and stops sending for the process lifetime (`src/core/notifier.py`).
- SEC rate-limit dependency: the historical pipeline relies on SEC's published limits via `TokenBucketRateLimiter(rate=10, capacity=10)` defaults (`src/cli/process_historical_13f.py`); exceeding SEC's policy is the user's responsibility, configurable with `--rate` and `--capacity`.
- Watchlist size: hardcoded to the CIK list in `src/core/hedge_funds_config.py` (about 60 entries as shipped). Two funds are present only as commented-out placeholders (`Ratan Capital Management`, `Magnetar Financial`) because their CIK is not available.
- Single-user model: only one Telegram chat ID is honored; the API has no authentication or rate limiting (only CORS for the dashboard origin). The dashboard DB is opened read-only via per-process snapshots, but anyone who can reach the API port can read holdings.
- Storage separation: SQLite (`data/13f_holdings.db`) and DuckDB (`data/13f_dashboard.duckdb`) are written in parallel by `_process_holdings`; SQLite is treated as compatibility state, DuckDB is canonical. SQLite holdings drift can only be detected via `diagnose-consistency`, and broad drift is treated as a separate repair backlog (not handled in-session) per `PROJECT_INDEX.md`.
- `bootstrap-dashboard-db` mode in `process_historical_13f.py` is explicitly deprecated; the entry point refuses to do anything useful and prints a warning (`bootstrap_dashboard_db_from_csv`).
- Holdings parsing edge cases:
  - XML path is tried first; if `infoTable` / `informationTable` / `infotable` tags are absent, parser silently falls back to HTML (`src/core/parser.py:parse_information_table`).
  - HTML header mapping uses fuzzy substring matching (`canonical_keys` in `_map_table_headers`); uncommon header wording falls into `extra_col_*` keys with the raw value preserved in `all_columns_raw`.
  - The parser strips "SH"/"PRN" suffixes in numeric conversion via `_to_int`, which means trailing alphabetic characters can be lost from numeric fields in pathological cases.
- Replay coverage: `replay_missed_alerts.py` looks back `REPLAY_WINDOW_DAYS` (default 21) of `seen_filings` rows where `matched=1`; older matches are not replayed.
- Dashboard refresh: `POST /api/cache/refresh` spawns a full `process_historical_13f.py full --yes` subprocess, which can take 30-90 minutes for the bundled fund list (`process_historical_13f.py:process_full_pipeline`); there is no incremental refresh endpoint, only the per-cycle real-time path.
- Legacy Streamlit UI still imports and renders (`src/web/dashboard.py`); on Hetzner the legacy `f8-dashboard.service` is removed by `deploy/deploy.sh`, but locally `python -m src.main dashboard-streamlit` keeps that code path alive.
- File-system coupling: the repo is structured around specific path conventions under `data/`, `logs/`, `cache/`. Any change to those paths must go through `src/core/paths.py`.
- Runtime file size: `README.md` documents that `*.duckdb`, `*.db`, `*.csv` runtime artifacts can exceed GitHub's 100 MB per-file limit and must remain in `.gitignore`; `git filter-repo` is the documented recovery procedure.

## Extensibility & Integration Points

- Adding a fund: add a `'0001234567': 'Fund Name'` entry to `src/core/hedge_funds_config.py`. The realtime poller (`FilingProcessor.process_submissions`), the historical pipeline (`process_full_pipeline`), the API fund lists (`get_fund_options` in `src/api/repository.py`), and the dashboard dropdowns (`src/web/pages/*`) all read from the same dictionary.
- Adding a new CLI mode: extend `src/cli/process_historical_13f.py` (the `choices` list of the `mode` argument) and document in the script's epilog.
- Adding a new FastAPI route: create a module under `src/api/routers/`, register it in `src/api/app.py:create_app()`, and (if needed) add new SQL in `src/web/sql_queries.py` (the FastAPI layer currently re-uses the SQL defined for the Streamlit layer).
- Adding a new dashboard page:
  - Streamlit: add `src/web/pages/<name>.py`, expose a `render_<name>_page(...)`, and wire it into `PAGE_RENDERERS` in `src/web/dashboard.py`.
  - React: add `frontend/src/routes/<Name>.tsx`, register it in `frontend/src/App.tsx`, and add the title mapping in `frontend/src/components/AppShell.tsx` (`PAGE_TITLES`).
- Adding a new Telegram command: extend `_SUPPORTED_COMMANDS` and `_dispatch` in `src/core/telegram_commands.py`. New commands must originate from the authorized `chat_id`.
- Adding a new SEC data source: extend `src/core/sec_client.py` (e.g. another submissions endpoint variant) or change the form tuple in `fetch_recent_13f_for_cik`.
- Storage migration: change schema in `src/core/storage.py` (`_ensure_table_columns` already does additive migrations) or in `src/core/dashboard_storage.py`. The `_has_required_schema` check in `Storage` will reinitialize an SQLite file that is missing `seen_filings`, `holdings`, or `statistics`.
- Deployment topology: `deploy/deploy.sh` accepts `--skip-push`, `--skip-tests`, `--tests "<pytest args>"`, `--rebuild-db`, and `--workers N`; `dev.ps1` accepts `-SkipFreePorts`. The systemd units can be retargeted via `Environment=` overrides (`API_SERVER_PORT`, `F8_API_PROXY_TARGET`, `CORS_ORIGINS`).
- Configuration overrides: add a field to the `Config` dataclass and an `_env_*` parser in `Config.from_env` (`src/core/config.py`); tests in `tests/test_config.py` exercise the env-var path.
- Background jobs: `src/api/refresh.py` is a small detached-subprocess manager; new long-running endpoints can follow the same pattern (return job handle, expose `/status`, store the last `MAX_HISTORY = 10` jobs in memory).
- Filter reuse: `build_position_key`, `compute_detailed_portfolio_diff`, and `compute_quarterly_history_transitions` in `src/core/diff.py` are pure functions; new analytics (e.g. different thresholds, alternative position identities) can layer on top without touching I/O.
- External messaging channels: `src/utils/message_bridge.py:save_message_to_viewer` is a single hook that every outbound Telegram message passes through; the Tkinter viewer reads `MESSAGE_LOG_FILE`. Replacing the channel means replacing `TelegramNotifier` and the message bridge.