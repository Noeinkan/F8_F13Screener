"""
Composes the text of every periodic Telegram message.

Deliberately pure: it takes plain numbers and dataclasses and returns a string.
Nothing here touches the database, the network or the clock beyond what is
handed to it, so each message shape can be asserted in a test without standing
up a poller.

House style, applied everywhere below:

* Alerts are *headlines*, not reports. The dashboard is where analysis happens,
  so a message says which fund, when, and how much moved, then links out.
* Every message that describes a quarter names it ("Q2 2026"), because the whole
  system runs on a calendar the reader cannot be expected to hold in their head.
* Fund and filer names are HTML-escaped: several tracked funds have an "&" in
  their name, which Telegram's HTML parser would otherwise reject.
"""
from datetime import date, datetime
from html import escape
from typing import Dict, List, Optional, Sequence
from urllib.parse import quote

from src.core.filing_calendar import FilingPeriod

MONTHS_IT = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu',
             'lug', 'ago', 'set', 'ott', 'nov', 'dic']

# The calendar carries the dashboard's English period labels ("Jul-Sep") so the
# two stay in step; the Telegram messages are Italian, so translate on the way
# out rather than forking the calendar.
QUARTER_MONTHS_IT = {'Q1': 'gen-mar', 'Q2': 'apr-giu', 'Q3': 'lug-set', 'Q4': 'ott-dic'}

# Above this many funds in one digest, list only the busiest and give a count
# for the rest: a deadline-day wave can carry 40+ and Telegram caps a message
# at 4096 characters.
MAX_DIGEST_ROWS = 25


def _esc(value: object) -> str:
    return escape(str(value or ''), quote=False)


def fmt_date(value: date) -> str:
    return f"{value.day:02d} {MONTHS_IT[value.month - 1]} {value.year}"


def fmt_datetime(value: str) -> str:
    """Format an ISO timestamp the way the existing alerts do, tolerating junk."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return _esc(value)
    return (
        f"{parsed.day:02d} {MONTHS_IT[parsed.month - 1]} {parsed.year}, "
        f"{parsed.hour:02d}:{parsed.minute:02d}"
    )


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return 'mai'
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}g {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def dashboard_fund_url(base_url: str, fund_name: str) -> str:
    """Deep link to a fund's snapshot in the React dashboard.

    The Fund Analysis route reads ``?fund=`` and matches it against the fund
    names in the holdings database, which are the same strings the poller reads
    from hedge_funds_config - so the name we alert on is the name that resolves.
    """
    base = (base_url or '').rstrip('/')
    return f"{base}/fund-analysis?fund={quote(fund_name or '', safe='')}&tab=snapshot"


def _change_summary(diff: Optional[Dict]) -> str:
    """The one-line '+3 nuove / -2 chiuse / ~5 variate' shorthand."""
    if not diff:
        return ''
    n_new = len(diff.get('new_positions', []) or [])
    n_closed = len(diff.get('closed_positions', []) or [])
    n_changed = len(diff.get('increased', []) or []) + len(diff.get('decreased', []) or [])

    # Only the non-zero parts: "+0 nuove · −0 chiuse" is noise in a headline.
    parts = []
    if n_new:
        parts.append(f"+{n_new} nuove")
    if n_closed:
        parts.append(f"−{n_closed} chiuse")
    if n_changed:
        parts.append(f"~{n_changed} variate")

    return ' · '.join(parts) if parts else 'nessuna variazione'


def format_headline_alert(
    fund_name: str,
    filer_name: str,
    filing_date: str,
    filing_url: str,
    dashboard_base_url: str,
    holdings_saved: bool = False,
    portfolio_diff: Optional[Dict] = None,
) -> str:
    """A single filing, as a headline plus links - the everyday alert."""
    lines = [
        f"🔔 <b>{_esc(fund_name)}</b>",
        f"📅 {fmt_datetime(filing_date)}",
    ]

    summary = _change_summary(portfolio_diff)
    if summary:
        lines.append(f"📊 {summary}")
    elif not holdings_saved:
        lines.append("⚠️ holdings non ancora elaborate")

    if _esc(filer_name) and filer_name != fund_name:
        lines.append(f"🏢 <i>{_esc(filer_name)}</i>")

    links = [
        f"<a href='{_esc(dashboard_fund_url(dashboard_base_url, fund_name))}'>Dashboard</a>",
        f"<a href='{_esc(filing_url)}'>EDGAR</a>",
    ]
    lines.append('🔗 ' + ' · '.join(links))

    return '\n'.join(lines)


def format_digest(
    alerts: Sequence[Dict],
    dashboard_base_url: str,
    period: Optional[FilingPeriod] = None,
) -> str:
    """Many filings rolled into one message - what a deadline wave should look like.

    Replaces the 42 separate messages that arrived on 14 August 2026 with a
    single scannable list, busiest fund first.
    """
    if not alerts:
        return ''

    header = f"📦 <b>{len(alerts)} nuovi filing</b>"
    if period:
        header += f" — {_esc(period.label)}"
    lines = [header, '']

    def weight(alert: Dict) -> int:
        diff = alert.get('portfolio_diff') or {}
        return (
            len(diff.get('new_positions', []) or [])
            + len(diff.get('closed_positions', []) or [])
            + len(diff.get('increased', []) or [])
            + len(diff.get('decreased', []) or [])
        )

    ordered = sorted(alerts, key=weight, reverse=True)

    for alert in ordered[:MAX_DIGEST_ROWS]:
        fund = alert.get('fund_name') or alert.get('filer_name') or '?'
        url = dashboard_fund_url(dashboard_base_url, fund)
        summary = _change_summary(alert.get('portfolio_diff'))
        row = f"• <a href='{_esc(url)}'>{_esc(fund)}</a>"
        if summary:
            row += f" — {summary}"
        lines.append(row)

    if len(ordered) > MAX_DIGEST_ROWS:
        lines.append(f"<i>...e altri {len(ordered) - MAX_DIGEST_ROWS} fondi</i>")

    base = (dashboard_base_url or '').rstrip('/')
    lines.append('')
    lines.append(f"🔗 <a href='{_esc(base)}/'>Apri il dashboard</a>")

    return '\n'.join(lines)


def format_heartbeat(
    day: date,
    totals: Dict[str, int],
    next_period: Optional[FilingPeriod],
    days_until: Optional[int],
) -> str:
    """The daily 'still alive' line.

    Its only job is to make silence meaningful: if this stops arriving, the
    poller is down, rather than the quarter being quiet.
    """
    cycles = totals.get('cycles', 0)
    checked = totals.get('total', 0)
    matched = totals.get('matched', 0)

    lines = [
        f"✅ <b>Screener attivo</b> — {fmt_date(day)}",
        f"🔄 {cycles} cicli · {checked:,} filing controllati · {matched} match".replace(',', '.'),
    ]

    if next_period and days_until is not None:
        lines.append(
            f"📅 Prossima scadenza: <b>{_esc(next_period.label)}</b> "
            f"il {fmt_date(next_period.deadline)} (fra {days_until} giorni)"
        )

    return '\n'.join(lines)


def format_health_alarm(
    silent_for_seconds: Optional[float],
    last_cycle_at: Optional[datetime],
    last_error: Optional[str],
    threshold_minutes: int,
) -> str:
    """Sent when the poller stops completing cycles - the dead-man's switch."""
    if last_cycle_at is None:
        # No cycle has ever been recorded: a fresh install, or a poller that has
        # never got far enough to finish one. "Silent for never" would be absurd.
        lines = [
            "🚨 <b>Screener mai partito</b>",
            "Nessun ciclo registrato: il poller non ha mai completato un giro.",
        ]
    else:
        lines = [
            f"🚨 <b>Screener silenzioso da {fmt_duration(silent_for_seconds)}</b>",
            f"Nessun ciclo completato da oltre {threshold_minutes} minuti.",
            f"Ultimo ciclo: {fmt_datetime(last_cycle_at.isoformat())}",
        ]

    if last_error:
        lines.append(f"Ultimo errore: <code>{_esc(last_error)}</code>")

    lines.append('')
    lines.append("Sul server: <code>systemctl status f8-screener</code>")

    return '\n'.join(lines)


def format_deadline_reminder(period: FilingPeriod, days_until: int) -> str:
    """Heads-up that a filing window is about to open."""
    return '\n'.join([
        f"📅 <b>{_esc(period.label)} in arrivo</b>",
        f"Scadenza <b>{fmt_date(period.deadline)}</b>, fra {days_until} giorni.",
        f"Periodo {QUARTER_MONTHS_IT.get(period.quarter, period.months_label)}, "
        f"chiuso il {fmt_date(period.period_end)}.",
        '',
        "Nei prossimi giorni gli alert arriveranno raggruppati in digest.",
    ])


def format_wave_progress(
    period: FilingPeriod,
    filed: int,
    tracked: int,
    newly_filed: Sequence[str] = (),
) -> str:
    """How much of the current wave has landed."""
    pct = int(round(100 * filed / tracked)) if tracked else 0
    lines = [
        f"📊 <b>{_esc(period.label)} — {filed} di {tracked} fondi</b> ({pct}%)",
        f"Scadenza {fmt_date(period.deadline)}.",
    ]

    if newly_filed:
        shown = [_esc(name) for name in list(newly_filed)[:10]]
        lines.append('')
        lines.append("Ultimi arrivi: " + ', '.join(shown))
        if len(newly_filed) > 10:
            lines.append(f"<i>...e altri {len(newly_filed) - 10}</i>")

    return '\n'.join(lines)
