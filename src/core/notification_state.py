"""
State shared between the poller and the out-of-process reporter.

The poller (``f8-screener``) runs continuously and knows what is happening; the
reporter (``f8-heartbeat``, a systemd timer) runs every few minutes and is the
only thing that can still speak when the poller is dead. They meet here, through
three files under ``data/realtime/notifications``:

* ``health.json``   - the poller's proof of life. Written every cycle, read by
  the reporter to decide whether the silence is a quiet quarter or a crash.
* ``queue/``        - one JSON file per alert waiting to be sent. A directory
  rather than a shared list so the two processes never contend: the poller only
  ever creates files, the reporter only ever reads and deletes them.
* ``sent_markers.json`` - which once-per-event messages already went out, so a
  restart cannot re-send today's heartbeat or this quarter's reminder.

Every write goes through a temp file and ``os.replace``, which is atomic on both
Windows and Linux: a reader either sees the old file or the new one, never a
half-written one.
"""
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.paths import (
    NOTIFY_DIR,
    NOTIFY_HEALTH_FILE,
    NOTIFY_QUEUE_DIR,
    NOTIFY_SENT_FILE,
)

logger = logging.getLogger(__name__)

# How many days of per-day counters to keep in health.json. Two is enough for a
# heartbeat that reports "yesterday" just after midnight.
_DAILY_RETENTION = 3

_UNSAFE_FILENAME = re.compile(r'[^A-Za-z0-9._-]')


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=2, default=str)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open('r', encoding='utf-8') as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Stato notifiche illeggibile (%s): %s", path.name, exc)
        return default


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #


@dataclass
class Health:
    """What the reporter needs to judge whether the poller is alive and well."""

    started_at: Optional[datetime] = None
    # Last *healthy* cycle: SEC answered for enough funds to trust "no filings".
    last_cycle_at: Optional[datetime] = None
    last_cycle_stats: Dict[str, int] = field(default_factory=dict)
    consecutive_errors: int = 0
    last_error: Optional[str] = None
    daily: Dict[str, Dict[str, int]] = field(default_factory=dict)
    # Last cycle that reached the end, healthy or degraded. Newer than
    # ``last_cycle_at`` means the poller is alive but SEC is not answering.
    last_attempt_at: Optional[datetime] = None

    def age_seconds(self, now: Optional[datetime] = None) -> Optional[float]:
        """Seconds since the last healthy cycle, or ``None`` if none ever completed."""
        if self.last_cycle_at is None:
            return None
        return ((now or datetime.now()) - self.last_cycle_at).total_seconds()

    def attempt_age_seconds(self, now: Optional[datetime] = None) -> Optional[float]:
        """Seconds since the poller last finished a cycle of any kind."""
        latest = max(
            (moment for moment in (self.last_attempt_at, self.last_cycle_at) if moment),
            default=None,
        )
        if latest is None:
            return None
        return ((now or datetime.now()) - latest).total_seconds()

    def totals_for(self, day: str) -> Dict[str, int]:
        return self.daily.get(day, {})


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def read_health() -> Health:
    raw = _read_json(NOTIFY_HEALTH_FILE, {})
    if not isinstance(raw, dict):
        return Health()
    return Health(
        started_at=_parse_dt(raw.get('started_at')),
        last_cycle_at=_parse_dt(raw.get('last_cycle_at')),
        last_cycle_stats=raw.get('last_cycle_stats') or {},
        consecutive_errors=int(raw.get('consecutive_errors') or 0),
        last_error=raw.get('last_error'),
        daily=raw.get('daily') or {},
        last_attempt_at=_parse_dt(raw.get('last_attempt_at')),
    )


def _write_health(health: Health) -> None:
    _atomic_write_json(
        NOTIFY_HEALTH_FILE,
        {
            'started_at': health.started_at.isoformat() if health.started_at else None,
            'last_cycle_at': health.last_cycle_at.isoformat() if health.last_cycle_at else None,
            'last_attempt_at': health.last_attempt_at.isoformat() if health.last_attempt_at else None,
            'last_cycle_stats': health.last_cycle_stats,
            'consecutive_errors': health.consecutive_errors,
            'last_error': health.last_error,
            'daily': health.daily,
        },
    )


_DAILY_KEYS = ('total', 'matched', 'sent', 'filtered', 'failed', 'errors', 'fetch_failed')


def _add_daily(health: Health, now: datetime, stats: Dict[str, int], counter: str) -> None:
    day = now.date().isoformat()
    totals = dict(health.daily.get(day, {}))
    totals[counter] = totals.get(counter, 0) + 1
    for key in _DAILY_KEYS:
        if key in (stats or {}):
            try:
                totals[key] = totals.get(key, 0) + int(stats[key])
            except (TypeError, ValueError):
                continue
    health.daily[day] = totals

    for stale in sorted(health.daily)[:-_DAILY_RETENTION]:
        health.daily.pop(stale, None)


def record_startup(now: Optional[datetime] = None) -> None:
    """Note that the poller has just started. Clears any stale error streak."""
    now = now or datetime.now()
    health = read_health()
    health.started_at = now
    health.consecutive_errors = 0
    health.last_error = None
    _write_health(health)


def record_cycle(stats: Dict[str, int], now: Optional[datetime] = None) -> None:
    """Record a completed polling cycle - the poller's heartbeat."""
    now = now or datetime.now()
    health = read_health()
    health.last_cycle_at = now
    health.last_attempt_at = now
    health.last_cycle_stats = dict(stats or {})
    health.consecutive_errors = 0
    health.last_error = None
    _add_daily(health, now, stats, 'cycles')
    _write_health(health)


def record_cycle_error(message: str, now: Optional[datetime] = None) -> None:
    """Record a cycle that raised. Consecutive failures are what trigger an alarm."""
    now = now or datetime.now()
    health = read_health()
    health.consecutive_errors += 1
    health.last_error = f"{now.isoformat(timespec='seconds')} - {message}"[:500]
    _write_health(health)


def record_cycle_degraded(
    stats: Dict[str, int],
    reason: str,
    now: Optional[datetime] = None,
) -> None:
    """Record a cycle that ran to the end but could not read SEC for most funds.

    It is *not* a heartbeat: ``last_cycle_at`` stays where the last healthy
    cycle left it, so a blocked or down SEC cannot pass for a quiet day. It
    does prove the process is alive (``last_attempt_at``), which lets the
    reporter say "SEC unreachable" instead of "poller dead".
    """
    now = now or datetime.now()
    health = read_health()
    health.last_attempt_at = now
    health.last_cycle_stats = dict(stats or {})
    health.consecutive_errors += 1
    health.last_error = f"{now.isoformat(timespec='seconds')} - {reason}"[:500]
    _add_daily(health, now, stats, 'degraded_cycles')
    _write_health(health)


# --------------------------------------------------------------------------- #
# Alert queue
# --------------------------------------------------------------------------- #


def queue_alert(key: str, payload: Dict[str, Any]) -> None:
    """Park an alert for the reporter to fold into the next digest."""
    safe = _UNSAFE_FILENAME.sub('_', key)[:120] or 'alert'
    target = NOTIFY_QUEUE_DIR / f"{safe}.json"
    try:
        _atomic_write_json(target, payload)
    except OSError as exc:
        logger.warning("Impossibile accodare alert %s: %s", key, exc)


def pending_alert_count() -> int:
    try:
        return sum(1 for _ in NOTIFY_QUEUE_DIR.glob('*.json'))
    except OSError:
        return 0


def oldest_pending_age_seconds(now: Optional[datetime] = None) -> Optional[float]:
    """Age of the longest-waiting queued alert, or ``None`` if the queue is empty.

    Read from file mtimes rather than by parsing every queued alert, so the
    reporter can decide whether a digest is ripe without opening the files.
    """
    try:
        mtimes = [path.stat().st_mtime for path in NOTIFY_QUEUE_DIR.glob('*.json')]
    except OSError:
        return None
    if not mtimes:
        return None
    return (now or datetime.now()).timestamp() - min(mtimes)


def _read_queue(remove: bool) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    try:
        files = sorted(NOTIFY_QUEUE_DIR.glob('*.json'))
    except OSError:
        return alerts

    for path in files:
        payload = _read_json(path, None)
        if isinstance(payload, dict):
            alerts.append(payload)
        if not remove:
            continue
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("Impossibile rimuovere %s dalla coda: %s", path.name, exc)

    alerts.sort(key=lambda item: str(item.get('queued_at') or ''))
    return alerts


def drain_alerts() -> List[Dict[str, Any]]:
    """Read and remove every queued alert. Only the reporter calls this."""
    return _read_queue(remove=True)


def peek_alerts() -> List[Dict[str, Any]]:
    """Read every queued alert and leave the queue as it was - for a dry run."""
    return _read_queue(remove=False)


# --------------------------------------------------------------------------- #
# Once-per-event markers
# --------------------------------------------------------------------------- #


def was_sent(marker: str) -> bool:
    markers = _read_json(NOTIFY_SENT_FILE, {})
    return isinstance(markers, dict) and marker in markers


def mark_sent(marker: str, now: Optional[datetime] = None) -> None:
    markers = _read_json(NOTIFY_SENT_FILE, {})
    if not isinstance(markers, dict):
        markers = {}
    markers[marker] = (now or datetime.now()).isoformat(timespec='seconds')

    # Keep the file from growing without bound; markers are all date-stamped so
    # the newest few hundred are always the relevant ones.
    if len(markers) > 400:
        for stale in sorted(markers, key=lambda k: markers[k])[:-200]:
            markers.pop(stale, None)

    _atomic_write_json(NOTIFY_SENT_FILE, markers)


def clear_marker(marker: str) -> None:
    """Forget a marker. Used to close an open alarm once the poller recovers."""
    markers = _read_json(NOTIFY_SENT_FILE, {})
    if isinstance(markers, dict) and marker in markers:
        markers.pop(marker, None)
        _atomic_write_json(NOTIFY_SENT_FILE, markers)


def state_dir() -> Path:
    return NOTIFY_DIR
