"""
The periodic reporter: everything Telegram says that is not a single filing.

Runs out of process, on a timer (``f8-heartbeat.timer`` on the VPS), rather than
inside the poller. That separation is the whole point: a poller cannot report
its own death. If ``f8-screener`` crashes, hangs, or is killed mid-cycle, this
process is still scheduled, still reads the health file, sees that no cycle has
completed, and says so.

Each run does up to five things, in order, each guarded so nothing is ever sent
twice:

1. **Digest** - flushes any alerts the poller parked during a filing wave.
2. **Health** - alarms if the poller has gone quiet, and says so again when it
   comes back.
3. **Heartbeat** - once a day, proof that silence means "no filings" and not
   "process is down".
4. **Reminder** - a few days before each quarterly deadline.
5. **Wave progress** - during a wave, how many tracked funds have filed.

Run it by hand with ``python -m src.cli.notify_reporter --dry-run`` to see what
it *would* send without sending anything.
"""
import argparse
import logging
import sys
from datetime import date, datetime
from typing import List, Optional

from src.core import filing_calendar, notification_state, report_builder
from src.core.config import Config
from src.core.filing_calendar import FilingPeriod
from src.core.notifier import TelegramNotifier
from src.core.storage import Storage
from src.utils.console import safe_print

logger = logging.getLogger(__name__)


class Reporter:
    """One pass of the periodic notification checks."""

    def __init__(self, config: Config, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.notifier = TelegramNotifier(
            config.telegram_bot_token,
            config.telegram_chat_id,
            config.max_retries,
            config.retry_delay,
            dashboard_base_url=config.dashboard_base_url,
        )
        self.storage = Storage(config.holdings_db)

    # -- delivery ---------------------------------------------------------- #

    def _send(self, message: str, label: str) -> bool:
        if not message:
            return False
        if self.dry_run:
            safe_print(f"\n----- {label} -----\n{message}\n")
            return True
        sent = self.notifier.send_message(message)
        logger.info("%s: %s", label, 'inviato' if sent else 'FALLITO')
        return sent

    # -- 1. digest --------------------------------------------------------- #

    def _digest_is_ripe(self, now: datetime) -> bool:
        """Whether the queue has waited long enough (or grown big enough) to send.

        Without this the digest cadence would just be the timer's cadence. The
        age rule lets a wave accumulate for ``digest_min_age_minutes`` before
        anything goes out; the size cap overrides it when filings pour in, so a
        deadline-day burst is not held back for three quarters of an hour.
        """
        pending = notification_state.pending_alert_count()
        if pending >= self.config.digest_max_pending:
            return True
        age = notification_state.oldest_pending_age_seconds(now)
        if age is None:
            return False
        return age >= self.config.digest_min_age_minutes * 60

    def flush_digest(self, now: datetime) -> bool:
        """Send everything the poller queued during the current wave."""
        if not self._digest_is_ripe(now):
            return False

        alerts = notification_state.drain_alerts()
        if not alerts:
            return False

        period = filing_calendar.active_window(
            now.date(),
            days_before=self.config.digest_days_before,
            days_after=self.config.digest_days_after,
        )
        message = report_builder.format_digest(
            alerts, self.config.dashboard_base_url, period
        )

        if not self._send(message, f"digest ({len(alerts)} filing)"):
            # Delivery failed and the queue files are already gone, so put them
            # back rather than dropping a whole wave's worth of alerts.
            for alert in alerts:
                key = f"{alert.get('fund_name', 'alert')}-{alert.get('queued_at', '')}"
                notification_state.queue_alert(key, alert)
            return False
        return True

    # -- 2. health --------------------------------------------------------- #

    def check_health(self, now: datetime) -> bool:
        """Alarm when the poller stops completing cycles; clear when it resumes."""
        health = notification_state.read_health()
        age = health.age_seconds(now)
        threshold = self.config.health_stale_minutes * 60
        alarm_open = notification_state.was_sent('health-alarm-open')

        stale = age is None or age > threshold

        if stale:
            if alarm_open:
                return False
            message = report_builder.format_health_alarm(
                silent_for_seconds=age,
                last_cycle_at=health.last_cycle_at,
                last_error=health.last_error,
                threshold_minutes=self.config.health_stale_minutes,
            )
            if self._send(message, 'allarme salute'):
                notification_state.mark_sent('health-alarm-open', now)
                return True
            return False

        if alarm_open:
            recovered = (
                "✅ <b>Screener tornato attivo</b>\n"
                f"Ciclo completato {report_builder.fmt_datetime(health.last_cycle_at.isoformat())}."
            )
            if self._send(recovered, 'ripristino'):
                notification_state.clear_marker('health-alarm-open')
                return True
        return False

    # -- 3. heartbeat ------------------------------------------------------ #

    def send_heartbeat(self, now: datetime) -> bool:
        """The once-a-day 'still alive' line."""
        if not self.config.enable_heartbeat:
            return False
        if now.hour < self.config.heartbeat_hour:
            return False
        if notification_state.was_sent('health-alarm-open'):
            # An alarm is outstanding. Following "screener silenzioso" with
            # "screener attivo" would contradict it; the recovery message is
            # what announces the poller is back.
            return False

        marker = f"heartbeat:{now.date().isoformat()}"
        if notification_state.was_sent(marker):
            return False

        health = notification_state.read_health()
        # Just after the configured hour the interesting totals are still
        # yesterday's if the day has barely started, so report whichever day
        # actually has counters.
        today_key = now.date().isoformat()
        totals = health.totals_for(today_key)
        if not totals and health.daily:
            totals = health.daily[sorted(health.daily)[-1]]

        nxt = filing_calendar.next_deadline(now.date())
        days = filing_calendar.days_until_next(now.date())
        message = report_builder.format_heartbeat(now.date(), totals, nxt, days)

        if self._send(message, 'heartbeat'):
            notification_state.mark_sent(marker, now)
            return True
        return False

    # -- 4. deadline reminder ---------------------------------------------- #

    def send_reminder(self, now: datetime) -> bool:
        nxt = filing_calendar.next_deadline(now.date())
        days = filing_calendar.days_until_next(now.date())
        if not nxt or days is None:
            return False
        if not 0 < days <= self.config.reminder_days_before:
            return False

        marker = f"reminder:{nxt.label}"
        if notification_state.was_sent(marker):
            return False

        message = report_builder.format_deadline_reminder(nxt, days)
        if self._send(message, 'promemoria scadenza'):
            notification_state.mark_sent(marker, now)
            return True
        return False

    # -- 5. wave progress -------------------------------------------------- #

    def _funds_filed_for(self, period: FilingPeriod) -> List[str]:
        """Distinct tracked funds that have filed for ``period``.

        seen_filings holds the same CIK in both a padded and an unpadded
        spelling for historical rows, so normalise before counting or the same
        fund is counted twice.
        """
        start = period.period_end.isoformat()
        end = date.fromordinal(
            period.deadline.toordinal() + self.config.digest_days_after
        ).isoformat()

        rows = self.storage.get_matched_filings_between(start, end)
        by_cik = {}
        for row in rows:
            raw = str(row.get('cik') or '').strip()
            key = raw.zfill(10) if raw.isdigit() else raw
            if key:
                by_cik[key] = self.config.hedge_funds_cik.get(key, row.get('filer_name') or key)
        return sorted(by_cik.values())

    def send_wave_progress(self, now: datetime) -> bool:
        period = filing_calendar.active_window(
            now.date(),
            days_before=self.config.digest_days_before,
            days_after=self.config.digest_days_after,
        )
        if not period:
            return False

        every = max(1, self.config.wave_progress_every_hours)
        bucket = now.hour // every
        marker = f"wave:{period.label}:{now.date().isoformat()}:{bucket}"
        if notification_state.was_sent(marker):
            return False

        filed = self._funds_filed_for(period)
        if not filed:
            return False

        message = report_builder.format_wave_progress(
            period, len(filed), len(self.config.hedge_funds_cik), filed[-10:]
        )
        if self._send(message, 'avanzamento wave'):
            notification_state.mark_sent(marker, now)
            return True
        return False

    # -- orchestration ----------------------------------------------------- #

    def run_once(self, now: Optional[datetime] = None) -> int:
        now = now or datetime.now()
        sent = 0
        for step, label in (
            (self.flush_digest, 'digest'),
            (self.check_health, 'health'),
            (self.send_heartbeat, 'heartbeat'),
            (self.send_reminder, 'reminder'),
            (self.send_wave_progress, 'wave'),
        ):
            try:
                if step(now):
                    sent += 1
            except Exception as exc:
                # One broken check must not stop the others - especially not the
                # health alarm, which is the one that matters when things break.
                logger.error("Controllo '%s' fallito: %s", label, exc, exc_info=True)
        return sent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Invia le notifiche periodiche (digest, heartbeat, allarmi, promemoria)."
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Stampa i messaggi invece di inviarli su Telegram.",
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true', help="Log di debug."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )

    try:
        config = Config.from_env()
        config.validate()
    except ValueError as exc:
        print(f"ERRORE CONFIGURAZIONE: {exc}")
        return 1

    sent = Reporter(config, dry_run=args.dry_run).run_once()
    logger.info("Reporter: %s messaggi inviati", sent)
    return 0


if __name__ == '__main__':
    sys.exit(main())
