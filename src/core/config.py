"""
Centralized configuration management for 13F Alert System
"""
import os
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass, field

from src.core.paths import (
    LAST_CHECK_FILE,
    REALTIME_DATA_DIR,
    LOGS_DIR,
    HOLDINGS_DB_FILE,
)


@dataclass
class Config:
    """Application configuration"""

    # Telegram credentials
    telegram_bot_token: str
    telegram_chat_id: str

    # SEC API
    sec_user_agent: str

    # RSS Feed
    rss_url: str = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=13F-HR&count=100&output=atom'

    # Polling intervals (seconds)
    poll_interval: int = 900  # 15 minutes for production

    # Retry configuration
    max_retries: int = 3
    retry_delay: int = 60

    # File paths - using centralized paths.py
    base_dir: Path = Path(REALTIME_DATA_DIR).parent.parent  # Project root
    last_check_file: Path = Path(LAST_CHECK_FILE)
    daily_summary_file: Path = Path(REALTIME_DATA_DIR) / '13f_daily_summary.json'
    holdings_db: Path = HOLDINGS_DB_FILE
    log_file: Path = Path(LOGS_DIR) / '13f_alerts.log'

    # Feature flags
    auto_launch_viewer: bool = True
    enable_filtered_daily_summary: bool = False

    # Submissions watcher
    submissions_recent_limit: int = 10
    submissions_request_delay_seconds: float = 1.0
    enable_atom_fallback: bool = True

    # Hedge funds filter
    hedge_funds_cik: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> 'Config':
        """Load configuration from environment or config_secret.py"""

        # Try loading from config_secret.py first
        try:
            from config_secret import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SEC_USER_AGENT
            bot_token = TELEGRAM_BOT_TOKEN
            chat_id = TELEGRAM_CHAT_ID
            user_agent = SEC_USER_AGENT
        except ImportError:
            # Fallback to environment variables
            bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
            chat_id = os.getenv('TELEGRAM_CHAT_ID')
            user_agent = os.getenv('SEC_USER_AGENT')

        if not bot_token or not chat_id:
            raise ValueError(
                "ERRORE: Credenziali mancanti!\n"
                "Crea il file config_secret.py (vedi config_secret.template.py)\n"
                "oppure imposta le variabili d'ambiente TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID"
            )

        # Load hedge funds configuration
        try:
            from src.core.hedge_funds_config import HEDGE_FUNDS_CIK
            hedge_funds = HEDGE_FUNDS_CIK
        except ImportError:
            from hedge_funds_config import HEDGE_FUNDS_CIK
            hedge_funds = HEDGE_FUNDS_CIK

        def _env_bool(key: str, default: bool) -> bool:
            val = os.getenv(key)
            if val is None:
                return default
            return val.strip().lower() not in ('0', 'false', 'no', '')

        def _env_int(key: str, default: int) -> int:
            val = os.getenv(key)
            try:
                return int(val) if val is not None else default
            except ValueError:
                return default

        def _env_float(key: str, default: float) -> float:
            val = os.getenv(key)
            try:
                return float(val) if val is not None else default
            except ValueError:
                return default

        return cls(
            telegram_bot_token=bot_token,
            telegram_chat_id=chat_id,
            sec_user_agent=user_agent or 'YourName yourname@email.com',
            poll_interval=_env_int('F13F_POLL_INTERVAL_SECONDS', 120),
            auto_launch_viewer=_env_bool('F13F_AUTO_LAUNCH_VIEWER', True),
            enable_filtered_daily_summary=_env_bool('F13F_ENABLE_FILTERED_DAILY_SUMMARY', False),
            submissions_recent_limit=_env_int('F13F_SUBMISSIONS_RECENT_LIMIT', 10),
            submissions_request_delay_seconds=_env_float('F13F_SUBMISSIONS_REQUEST_DELAY_SECONDS', 1.0),
            enable_atom_fallback=_env_bool('F13F_ENABLE_ATOM_FALLBACK', True),
            hedge_funds_cik=hedge_funds
        )

    @property
    def telegram_url(self) -> str:
        """Get Telegram API URL"""
        return f'https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage'

    def validate(self) -> None:
        """Validate configuration"""
        if self.telegram_bot_token == 'YOUR_BOT_TOKEN' or self.telegram_chat_id == 'YOUR_CHAT_ID':
            raise ValueError("ERRORE: Configura BOT_TOKEN e CHAT_ID!")

        if self.sec_user_agent == 'YourName yourname@email.com':
            raise ValueError("WARNING: Configura USER_AGENT con il tuo email!")
