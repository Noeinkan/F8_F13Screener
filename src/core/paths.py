"""
Centralized path configuration for F8_F13Screener project.
All file paths should be imported from here.
"""
import os
from pathlib import Path

# Project root directory (where this file is located)
PROJECT_ROOT = Path(__file__).parent.absolute()

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
REALTIME_DATA_DIR = DATA_DIR / "realtime"
HISTORICAL_DATA_DIR = DATA_DIR / "historical"
MESSAGES_DATA_DIR = DATA_DIR / "messages"
CACHE_DIR = DATA_DIR / "cache"
NOTIFY_DIR = REALTIME_DATA_DIR / "notifications"
# One file per pending alert. The poller writes them and the reporter deletes
# them after sending, so the two processes never contend over a shared file.
NOTIFY_QUEUE_DIR = NOTIFY_DIR / "queue"

# Log directory
LOGS_DIR = PROJECT_ROOT / "logs"

# Config directory
CONFIG_DIR = PROJECT_ROOT / "config"

# Ensure directories exist
for directory in [
    DATA_DIR,
    REALTIME_DATA_DIR,
    HISTORICAL_DATA_DIR / "catalog",
    HISTORICAL_DATA_DIR / "holdings",
    HISTORICAL_DATA_DIR / "tracking",
    MESSAGES_DATA_DIR,
    CACHE_DIR,
    LOGS_DIR,
    CONFIG_DIR,
    NOTIFY_DIR,
    NOTIFY_QUEUE_DIR,
]:
    directory.mkdir(parents=True, exist_ok=True)

# Real-time monitoring files
LAST_CHECK_FILE = str(REALTIME_DATA_DIR / "last_13f_check_v2.json")
REALTIME_HOLDINGS_CSV = str(REALTIME_DATA_DIR / "13f_holdings_tracker.csv")
REALTIME_LOG_FILE = str(LOGS_DIR / "13f_alerts.log")
HOLDINGS_DB_FILE = DATA_DIR / "13f_holdings.db"
# The dashboard DuckDB can be pointed elsewhere with F8_DASHBOARD_DB. The
# public demo uses it to read the frozen snapshot in demo/fixtures/ instead of
# the live database; it is equally the way to run the dashboard against a copy
# without moving the real file.
_DASHBOARD_DB_OVERRIDE = (os.getenv("F8_DASHBOARD_DB") or "").strip()
DASHBOARD_DB_FILE = (
    Path(_DASHBOARD_DB_OVERRIDE).expanduser()
    if _DASHBOARD_DB_OVERRIDE
    else DATA_DIR / "13f_dashboard.duckdb"
)

# Historical processing files
CATALOG_FILE = str(
    HISTORICAL_DATA_DIR / "catalog" / "historical_13f_catalog_5years.json"
)
HISTORICAL_HOLDINGS_CSV = str(
    HISTORICAL_DATA_DIR / "holdings" / "13f_holdings_5years.csv"
)
PROCESSED_TRACKING_FILE = str(
    HISTORICAL_DATA_DIR / "tracking" / "processed_filings_tracking.json"
)
PROCESSING_METRICS_FILE = str(
    HISTORICAL_DATA_DIR / "tracking" / "processing_metrics.json"
)
PROCESSING_CHECKPOINT_FILE = str(
    HISTORICAL_DATA_DIR / "tracking" / "processing_checkpoint.json"
)

# Message files
MESSAGE_LOG_FILE = str(MESSAGES_DATA_DIR / "telegram_messages.json")

# Notification state. NOTIFY_HEALTH_FILE is the poller's proof of life, written
# every cycle and read by the out-of-process reporter; NOTIFY_SENT_FILE records
# which once-per-event messages (a given quarter's reminder, today's heartbeat)
# have already gone out, so a restart cannot send them twice.
NOTIFY_HEALTH_FILE = NOTIFY_DIR / "health.json"
NOTIFY_SENT_FILE = NOTIFY_DIR / "sent_markers.json"

# Config files
ENV_EXAMPLE_FILE = str(CONFIG_DIR / ".env.example")

# Cache directory for filing cache
FILING_CACHE_DIR = str(CACHE_DIR)
