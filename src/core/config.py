"""
Centralized configuration management for 13F Alert System
"""
import os
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass

from src.core.paths import (
    LAST_CHECK_FILE,
    REALTIME_DATA_DIR,
    LOGS_DIR,
    DATA_DIR
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
    holdings_db: Path = Path(DATA_DIR) / '13f_holdings.db'
    log_file: Path = Path(LOGS_DIR) / '13f_alerts.log'

    # Feature flags
    auto_launch_viewer: bool = True

    # Hedge funds filter
    hedge_funds_cik: Dict[str, str] = None

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
            from hedge_funds_config import HEDGE_FUNDS_CIK
            hedge_funds = HEDGE_FUNDS_CIK
        except ImportError:
            hedge_funds = {}

        return cls(
            telegram_bot_token=bot_token,
            telegram_chat_id=chat_id,
            sec_user_agent=user_agent or 'YourName yourname@email.com',
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
