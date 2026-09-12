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
it *would* send without sending anything. A dry run also leaves the state alone:
the queue keeps its alerts and no "already sent" marker is written, so the real
run that follows still sends everything.
"""
import argparse
import logging
import sys
from datetime import date, datetime
from typing import List, Optional, Sequence

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

    def _send(
        self,
        message: str,
        label: str,
        buttons: Sequence[report_builder.Button] = (),
        silent: bool = False,
    ) -> bool:
        if not message:
            return False
        if self.dry_run:
            extra = ''.join(f"\n[{text}] {url}" for text, url in buttons)
            mode = ' (silenzioso)' if silent else ''
            safe_print(f"\n----- {label}{mode} -----\n{message}{extra}\n")
            return True
        sent = self.notifier.send_message(message, buttons=list(buttons), silent=silent)
        logger.info("%s: %s", label, 'inviato' if sent else 'FALLITO')
        return sent

    def _mark(self, marker: str, now: datetime) -> None:
        if not self.dry_run:
            notification_state.mark_sent(marker, now)

    def _clear(self, marker: str) -> None:
        if not self.dry_run:
            notification_state.clear_marker(marker)

    @staticmethod
    def _wave_count_marker(period: FilingPeriod, filed: int) -> str:
        """Shared by the digest and the progress message: a count is reported once."""
        return f"wave-count:{period.label}:{filed}"

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

        if self.dry_run:
            alerts = notification_state.peek_alerts()
        else:
            alerts = notification_state.drain_alerts()
        if not alerts:
            return False

        period = filing_calendar.active_window(
            now.date(),
            days_before=self.config.digest_days_before,
            days_after=self.config.digest_days_after,
        )
        filed = len(self._funds_filed_for(period)) if period else None
        message = report_builder.format_digest(
            alerts,
            self.config.dashboard_base_url,
            period,
            filed=filed,
            tracked=len(self.config.hedge_funds_cik),
        )

        if not self._send(
            message,
            f"digest ({len(alerts)} filing)",
            buttons=report_builder.digest_buttons(self.config.dashboard_base_url),
        ):
            # Delivery failed and the queue files are already gone, so put them
            # back rather than dropping a whole wave's worth of alerts.
            for alert in alerts:
                key = f"{alert.get('fund_name', 'alert')}-{alert.get('queued_at', '')}"
                notification_state.queue_alert(key, alert)
            return False
        if period and filed:
            self._mark(self._wave_count_marker(period, filed), now)
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
            attempt_age = health.attempt_age_seconds(now)
            # The process still finishes cycles, they just cannot read SEC (a
            # 403 block, an outage). Saying "poller dead" here would send the
            # reader to restart a service that is working fine.
            poller_alive_but_degraded = (
                health.consecutive_errors > 0
                and health.last_attempt_at is not None
                and attempt_age is not None
                and attempt_age <= threshold
            )
            if poller_alive_but_degraded:
                message = report_builder.format_degraded_alarm(
                    unhealthy_for_seconds=age,
                    last_cycle_at=health.last_cycle_at,
                    last_attempt_at=health.last_attempt_at,
                    reason=health.last_error,
                    failed_cycles=health.consecutive_errors,
                )
            else:
                message = report_builder.format_health_alarm(
                    silent_for_seconds=age,
                    last_cycle_at=health.last_cycle_at,
                    last_error=health.last_error,
                    threshold_minutes=self.config.health_stale_minutes,
                )
            if self._send(message, 'allarme salute'):
                self._mark('health-alarm-open', now)
                return True
            return False

        if alarm_open:
            recovered = (
                "✅ <b>Screener tornato attivo</b>\n"
                f"Ciclo completato {report_builder.fmt_datetime(health.last_cycle_at.isoformat())}."
            )
            if self._send(recovered, 'ripristino'):
                self._clear('health-alarm-open')
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

        # Silent: it lands in the chat to be glanced at, but a daily buzz that
        # says "nothing happened" teaches the reader to ignore the buzzes that matter.
        if self._send(message, 'heartbeat', silent=True):
            self._mark(marker, now)
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
            self._mark(marker, now)
            return True
        return False

    # -- 5. wave progress -------------------------------------------------- #

    def _funds_filed_for(self, period: FilingPeriod) -> List[str]:
        """Distinct tracked funds that have filed for ``period``, most recent arrival last.

        seen_filings holds the same CIK in both a padded and an unpadded
        spelling for historical rows, so normalise before counting or the same
        fund is counted twice.
        """
        start = period.period_end.isoformat()
        end = date.fromordinal(
            period.deadline.toordinal() + self.config.digest_days_after
        ).isoformat()

        rows = self.storage.get_matched_filings_between(start, end)
        # Storage orders by filing date only, and a whole wave shares one date;
        # the acceptance time is what tells 20:27 apart from 09:03.
        rows = sorted(
            rows,
            key=lambda row: (str(row.get('filing_date') or ''), str(row.get('acceptance_datetime') or '')),
        )
        by_cik = {}
        for row in rows:
            raw = str(row.get('cik') or '').strip()
            key = raw.zfill(10) if raw.isdigit() else raw
            if key:
                # Re-insert so dict order follows each fund's latest filing.
                by_cik.pop(key, None)
                by_cik[key] = self.config.hedge_funds_cik.get(key, row.get('filer_name') or key)
        return list(by_cik.values())

    def send_wave_progress(self, now: datetime) -> bool:
        """How much of the wave has landed - only when that number has moved.

        Every digest already carries the count in its header, so this speaks
        only for arrivals no digest reported, and at most once per
        ``wave_progress_every_hours``.
        """
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
        count_marker = self._wave_count_marker(period, len(filed))
        if notification_state.was_sent(count_marker):
            return False

        newest_first = list(reversed(filed))
        message = report_builder.format_wave_progress(
            period, len(filed), len(self.config.hedge_funds_cik), newest_first[:10]
        )
        if self._send(message, 'avanzamento wave', silent=True):
            self._mark(marker, now)
            self._mark(count_marker, now)
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
