"""
Telegram notification service.

This module owns *delivery* only. What a message says is composed in
``src.core.report_builder``, so the wording of an alert can be asserted in a
test without mocking an HTTP call.
"""
import json
import logging
import time
from datetime import datetime
from typing import Dict, Optional, Sequence
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

    def send_message(
        self,
        message: str,
        buttons: Optional[Sequence[report_builder.Button]] = None,
        silent: bool = False,
    ) -> bool:
        """
        Send a message via Telegram with automatic retry

        Args:
            message: Message text (supports HTML formatting)
            buttons: (label, url) pairs shown as one row of buttons under the text
            silent: deliver without a sound or vibration - for routine messages

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
        if silent:
            payload['disable_notification'] = True
        if buttons:
            payload['reply_markup'] = json.dumps({
                'inline_keyboard': [[{'text': label, 'url': url} for label, url in buttons]]
            })

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
                if response.status_code == 400 and buttons:
                    # Telegram rejects the whole message when it dislikes a
                    # button URL (localhost is refused outright). Retrying the
                    # same payload cannot help, so resend the links as text.
                    logger.warning(
                        "Pulsanti rifiutati da Telegram (%s): reinvio con link testuali",
                        response.text[:200],
                    )
                    return self.send_message(
                        f"{message}\n{report_builder.links_line(buttons)}", silent=silent
                    )
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
        form: str = '',
        report_date: str = '',
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
            form: SEC form type ('13F-HR' or '13F-HR/A'), when known
            report_date: Quarter end the filing reports on (YYYY-MM-DD), when known

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
            form=form,
            report_date=report_date,
        )
        buttons = report_builder.headline_buttons(
            fund_name, filing_url, self.dashboard_base_url, portfolio_diff
        )
        return self.send_message(message, buttons=buttons)

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
