"""
Telegram notification service.

This module owns *delivery* only. What a message says is composed in
``src.core.report_builder``, so the wording of an alert can be asserted in a
test without mocking an HTTP call.
"""
import logging
import time
from datetime import datetime
from typing import Dict, Optional
import requests

from src.core import report_builder
from src.utils.message_bridge import save_message_to_viewer

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Service for sending Telegram notifications"""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        max_retries: int = 3,
        retry_delay: int = 60,
        dashboard_base_url: str = '',
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.dashboard_base_url = dashboard_base_url
        self.telegram_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        self._disabled_due_to_unauthorized = False

    def send_message(self, message: str) -> bool:
        """
        Send a message via Telegram with automatic retry

        Args:
            message: Message text (supports HTML formatting)

        Returns:
            True if message sent successfully, False otherwise
        """
        if self._disabled_due_to_unauthorized:
            return False

        payload = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }

        for attempt in range(self.max_retries):
            try:
                response = requests.post(self.telegram_url, data=payload, timeout=10)
                if response.status_code == 200:
                    logger.info("Notifica Telegram inviata con successo")
                    # Save message for viewer
                    save_message_to_viewer(message)
                    return True
                if response.status_code == 401:
                    self._disabled_due_to_unauthorized = True
                    logger.warning(
                        "Errore Telegram permanente: token bot non valido (HTTP 401). "
                        "Invio notifiche disabilitato per questo processo finche la configurazione non viene corretta."
                    )
                    return False
                else:
                    logger.warning(f"Errore Telegram (tentativo {attempt+1}/{self.max_retries}): {response.status_code}")
            except requests.exceptions.RequestException as e:
                logger.error(f"Eccezione Telegram (tentativo {attempt+1}/{self.max_retries}): {e}")

            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)

        logger.error("Fallito invio notifica Telegram dopo tutti i tentativi")
        return False

    @staticmethod
    def _format_date(date_str: str) -> str:
        """Italian date formatting, passing unparseable input straight through."""
        try:
            datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            return date_str
        return report_builder.fmt_datetime(date_str)

    def send_filing_alert(
        self,
        fund_name: str,
        filer_name: str,
        filing_date: str,
        filing_url: str,
        holdings_saved: bool = False,
        portfolio_diff: Optional[Dict] = None,
    ) -> bool:
        """
        Send a 13F filing alert, optionally including a quarter-over-quarter diff.

        Args:
            fund_name: Name of the matched fund
            filer_name: Name of the filer
            filing_date: Filing date
            filing_url: URL to the filing on EDGAR
            holdings_saved: Whether holdings were successfully saved
            portfolio_diff: Output of compute_portfolio_diff(), or None

        Returns:
            True if message sent successfully
        """
        message = report_builder.format_headline_alert(
            fund_name=fund_name,
            filer_name=filer_name,
            filing_date=filing_date,
            filing_url=filing_url,
            dashboard_base_url=self.dashboard_base_url,
            holdings_saved=holdings_saved,
            portfolio_diff=portfolio_diff,
        )
        return self.send_message(message)

    def send_daily_summary(self, date: str, count: int, top_filers: list) -> bool:
        """
        Send daily summary of filtered filings

        Args:
            date: Date of the summary
            count: Total number of filtered filings
            top_filers: List of (filer_name, count) tuples

        Returns:
            True if message sent successfully
        """
        message = (
            f"📋 <b>Daily Summary - {date}</b>\n\n"
            f"🔍 Filings filtrati: <b>{count}</b>\n"
            f"(Non corrispondono agli hedge funds monitorati)\n\n"
            f"📊 <b>Top Filers:</b>\n"
        )

        for filer, filing_count in top_filers:
            message += f"  • {filer}: {filing_count}\n"

        message += f"\n💡 Questi filing sono stati esclusi perché non fanno parte della watchlist."

        return self.send_message(message)
