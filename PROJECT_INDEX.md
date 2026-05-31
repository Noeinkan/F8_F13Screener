# Project Index

Use this file first when you need a fast mental model of the repo.

## What This Project Does

SEC 13F screener for tracked hedge funds. It polls SEC EDGAR, parses Information Tables, stores holdings, sends Telegram alerts, and serves a local Streamlit dashboard.

## Read First

1. [CLAUDE.md](CLAUDE.md) for the compact operating notes.
2. [README.md](README.md) for the user-facing workflow and launch commands.
3. [src/core/paths.py](src/core/paths.py) for the canonical data-path rules.

## Canonical Entrypoints

- [src/main.py](src/main.py): unified app entrypoint.
- [src/cli/main.py](src/cli/main.py): realtime poller and Telegram flow.
- [src/cli/process_historical_13f.py](src/cli/process_historical_13f.py): historical refresh and dashboard DB rebuild.
- [src/web/dashboard.py](src/web/dashboard.py): Streamlit dashboard.
- [dashboard.bat](dashboard.bat): Windows launcher wrapper.
- [deploy.sh](deploy.sh): root Bash wrapper that forwards to the real deploy script.

## High-Value Modules

- [src/core/sec_client.py](src/core/sec_client.py): SEC RSS/submissions discovery and accession lookup.
- [src/core/parser.py](src/core/parser.py): XML-first holdings parsing with HTML fallback.
- [src/core/storage.py](src/core/storage.py): SQLite persistence and accession helpers.
- [src/core/diff.py](src/core/diff.py): portfolio diff and history helpers.
- [src/core/dashboard_snapshot.py](src/core/dashboard_snapshot.py): snapshot handling for dashboard reads on Windows.
- [src/core/dashboard_storage.py](src/core/dashboard_storage.py): dashboard storage access.
- [src/core/hedge_funds_config.py](src/core/hedge_funds_config.py): tracked fund CIK list.
- [src/core/notifier.py](src/core/notifier.py): Telegram notification plumbing.
- [src/web/dashboard.py](src/web/dashboard.py): Streamlit app entry and page orchestration.
- [src/web/data_service.py](src/web/data_service.py): dashboard data loading and query plumbing.
- [src/web/sql_queries.py](src/web/sql_queries.py): SQL used by the dashboard.
- [src/web/charts.py](src/web/charts.py): chart builders.
- [src/web/formatting.py](src/web/formatting.py): table and value formatting helpers.
- [src/web/instrument_transforms.py](src/web/instrument_transforms.py): instrument normalization/transforms.
- [src/web/diff_views.py](src/web/diff_views.py): diff view rendering helpers.
- [src/web/pages/overview.py](src/web/pages/overview.py), [src/web/pages/fund_detail.py](src/web/pages/fund_detail.py), [src/web/pages/fund_history.py](src/web/pages/fund_history.py), [src/web/pages/portfolio_diff.py](src/web/pages/portfolio_diff.py), [src/web/pages/holdings_search.py](src/web/pages/holdings_search.py): dashboard pages.

## Data Locations

- `data/`: main app data.
- `data/realtime/`: realtime outputs.
- `data/historical/`: historical catalog and holdings artifacts.
- `data/exports/`: exported CSVs.
- `cache/dashboard/`: per-process dashboard snapshots and fallback cache.
- `src/core/data/`: dashboard and holdings databases used by the app.

## Rules That Matter

- Match tracked funds by CIK only, never by fund name.
- `HoldingsParser` tries XML first, then HTML fallback.
- `src/core/paths.py` is the source of truth for data paths and directory creation.
- `seen_filings` is written before Telegram notification so send failures do not cause reprocessing.
- Dashboard comparisons use normalized positions, not raw rows.
- Normalization key is CUSIP when present, otherwise `issuer_name|share_class|put_call`.
- Dashboard history uses detailed diff helpers; Telegram uses the simpler diff helper.

## Common Commands

```powershell
python -m src.main dashboard
python -m src.main alerts
python -m src.cli.process_historical_13f full --yes --save-db
python -m src.cli.process_historical_13f bootstrap-dashboard-db
rtk pytest tests/ -v
```

## Verified Recently

- `python -m src.main dashboard` starts cleanly.
- `rtk pytest tests/test_web_charts.py tests/test_web_instrument_transforms.py tests/test_web_sql_queries.py tests/test_web_formatting.py tests/test_dashboard_snapshot.py tests/test_diff.py -q` passes.

## Tests To Check First

- [tests/test_sec_client.py](tests/test_sec_client.py)
- [tests/test_parse_information_table.py](tests/test_parse_information_table.py)
- [tests/test_storage.py](tests/test_storage.py)
- [tests/test_diff.py](tests/test_diff.py)
- [tests/test_dashboard_snapshot.py](tests/test_dashboard_snapshot.py)
- [tests/test_web_charts.py](tests/test_web_charts.py)
- [tests/test_web_instrument_transforms.py](tests/test_web_instrument_transforms.py)
- [tests/test_web_sql_queries.py](tests/test_web_sql_queries.py)
- [tests/test_web_formatting.py](tests/test_web_formatting.py)

## Troubleshooting Shortcuts

- If `run .\dashboard.bat` fails, do not use `run`; use `dashboard.bat` or `python -m src.main dashboard`.
- If the dashboard DB is stale or malformed, rebuild with `python -m src.cli.process_historical_13f full --yes --save-db` or `python -m src.main dashboard -RebuildDb`.
- If SEC parsing changes, start with [src/core/parser.py](src/core/parser.py) and [tests/test_parse_information_table.py](tests/test_parse_information_table.py).

## Adding A New Fund

Add a zero-padded 10-digit CIK entry in [src/core/hedge_funds_config.py](src/core/hedge_funds_config.py):

```python
'0001234567': 'Fund Name (Manager Name)',
```