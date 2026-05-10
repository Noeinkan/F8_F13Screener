"""
Telegram bot command handler (two-way control via long-polling).

Runs in a daemon thread alongside the SEC polling loop.
Commands: /start, /stop, /status
Only accepts messages from the authorized chat_id.
"""
import logging
import threading
import time
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_SUPPORTED_COMMANDS = {'/start', '/stop', '/status', '/help'}


class TelegramCommandHandler:
    """
    Long-polls Telegram getUpdates and dispatches /start, /stop, /status.

    pause_event: when set, the SEC polling loop should pause.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        pause_event: threading.Event,
        last_check_ref: Optional[list] = None,
    ):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.pause_event = pause_event
        # Mutable container so main loop can update the timestamp in-place:
        # last_check_ref[0] = datetime | None
        self.last_check_ref = last_check_ref or [None]
        self._base_url = f'https://api.telegram.org/bot{bot_token}'
        self._offset: Optional[int] = None
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the command listener thread (daemon, non-blocking)."""
        self._thread = threading.Thread(
            target=self._poll_loop,
            name='telegram-commands',
            daemon=True,
        )
        self._thread.start()
        logger.info('Telegram command handler avviato')

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        while True:
            try:
                updates = self._get_updates(timeout=30)
                for update in updates:
                    self._offset = update['update_id'] + 1
                    self._dispatch(update)
            except Exception as e:
                logger.warning(f'Telegram command poll error: {e}')
                time.sleep(5)

    def _get_updates(self, timeout: int = 30) -> list:
        params = {'timeout': timeout, 'allowed_updates': ['message']}
        if self._offset is not None:
            params['offset'] = self._offset
        try:
            resp = requests.get(
                f'{self._base_url}/getUpdates',
                params=params,
                timeout=timeout + 5,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get('result', [])
            logger.warning(f'getUpdates HTTP {resp.status_code}')
        except requests.exceptions.RequestException as e:
            logger.warning(f'getUpdates request failed: {e}')
        return []

    def _dispatch(self, update: dict) -> None:
        msg = update.get('message') or update.get('edited_message')
        if not msg:
            return

        # Security: only accept messages from the authorized chat
        chat_id = str(msg.get('chat', {}).get('id', ''))
        if chat_id != self.chat_id:
            logger.warning(f'Comando da chat non autorizzato: {chat_id}')
            return

        text = (msg.get('text') or '').strip().lower()
        # Handle "/command@botname" form
        command = text.split('@')[0]

        if command == '/stop':
            self.pause_event.set()
            self._reply('⏸ <b>Polling in pausa.</b>\nManda /start per riprendere.')
            logger.info('Polling SEC messo in pausa via Telegram')

        elif command == '/start':
            self.pause_event.clear()
            self._reply('▶ <b>Polling ripreso.</b>')
            logger.info('Polling SEC ripreso via Telegram')

        elif command == '/status':
            state = '⏸ In pausa' if self.pause_event.is_set() else '▶ Attivo'
            last = self.last_check_ref[0]
            last_str = last.strftime('%d/%m/%Y %H:%M:%S') if last else 'N/D'
            self._reply(
                f'📡 <b>Stato:</b> {state}\n'
                f'🕐 <b>Ultimo check:</b> {last_str}'
            )

        elif command == '/help':
            self._reply(
                '📋 <b>Comandi disponibili:</b>\n'
                '/start — riprende il polling SEC\n'
                '/stop — mette in pausa il polling SEC\n'
                '/status — mostra stato corrente\n'
                '/help — mostra questo messaggio'
            )

    def _reply(self, text: str) -> None:
        try:
            requests.post(
                f'{self._base_url}/sendMessage',
                data={
                    'chat_id': self.chat_id,
                    'text': text,
                    'parse_mode': 'HTML',
                    'disable_web_page_preview': True,
                },
                timeout=10,
            )
        except requests.exceptions.RequestException as e:
            logger.warning(f'Reply failed: {e}')
