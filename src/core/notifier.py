"""
Telegram notification service
"""
import logging
import time
from datetime import datetime
from typing import Optional
import requests

from src.utils.message_bridge import save_message_to_viewer

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Service for sending Telegram notifications"""

    def __init__(self, bot_token: str, chat_id: str, max_retries: int = 3, retry_delay: int = 60):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.telegram_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'

    def send_message(self, message: str) -> bool:
        """
        Send a message via Telegram with automatic retry

        Args:
            message: Message text (supports HTML formatting)

        Returns:
            True if message sent successfully, False otherwise
        """
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
        MONTHS_IT = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu',
                     'lug', 'ago', 'set', 'ott', 'nov', 'dic']
        try:
            dt = datetime.fromisoformat(date_str)
            return f"{dt.day:02d} {MONTHS_IT[dt.month - 1]} {dt.year}, {dt.hour:02d}:{dt.minute:02d}"
        except (ValueError, TypeError):
            return date_str

    def send_filing_alert(
        self,
        fund_name: str,
        filer_name: str,
        filing_date: str,
        filing_url: str,
        holdings_saved: bool = False
    ) -> bool:
        """
        Send a 13F filing alert

        Args:
            fund_name: Name of the matched fund
            filer_name: Name of the filer
            filing_date: Filing date
            filing_url: URL to the filing on EDGAR
            holdings_saved: Whether holdings were successfully saved

        Returns:
            True if message sent successfully
        """
        message = (
            f"🔔 <b>Nuovo Form 13F-HR Rilevato!</b>\n\n"
            f"📊 <b>Fund:</b> {fund_name}\n"
            f"🏢 <b>Filer:</b> {filer_name}\n"
            f"📅 <b>Data:</b> {self._format_date(filing_date)}\n"
            f"🔗 <b>Link:</b> <a href='{filing_url}'>Visualizza su EDGAR</a>"
        )

        if holdings_saved:
            message += f"\n\n✅ <b>Holdings salvate nel database</b>"

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
