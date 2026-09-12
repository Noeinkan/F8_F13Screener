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
* Links to open something travel as Telegram buttons, returned separately from
  the text (``headline_buttons``, ``digest_buttons``). ``links_line`` turns the
  same buttons back into inline links for when Telegram refuses a button URL.
"""
import math
from datetime import date, datetime
from html import escape
from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple
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

# A Telegram inline button: (label, url).
Button = Tuple[str, str]


def _esc(value: object) -> str:
    return escape(str(value or ''), quote=False)


def _num(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def fmt_money(dollars: float) -> str:
    dollars = abs(dollars)
    if dollars >= 1_000_000_000:
        return f"${dollars / 1_000_000_000:.1f}B"
    if dollars >= 10_000_000:
        return f"${dollars / 1_000_000:.0f}M"
    if dollars >= 1_000_000:
        return f"${dollars / 1_000_000:.1f}M"
    if dollars >= 1_000:
        return f"${dollars / 1_000:.0f}k"
    return f"${dollars:.0f}"


def period_label(report_date: str) -> str:
    """'2026-06-30' -> 'Q2 2026'; empty when the date is missing or unreadable."""
    try:
        parsed = date.fromisoformat(str(report_date or '')[:10])
    except ValueError:
        return ''
    return f"Q{(parsed.month - 1) // 3 + 1} {parsed.year}"


def is_amendment(form: str) -> bool:
    return str(form or '').strip().upper().endswith('/A')


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


def dashboard_compare_url(base_url: str, fund_name: str, old_accession: str, new_accession: str) -> str:
    """Deep link to the Compare tab, pinned to this filing and the one before it."""
    base = (base_url or '').rstrip('/')
    return (
        f"{base}/fund-analysis?fund={quote(fund_name or '', safe='')}&tab=compare"
        f"&old={quote(old_accession, safe='')}&new={quote(new_accession, safe='')}"
    )


def _fund_url(base_url: str, fund_name: str, diff: Optional[Dict]) -> str:
    """Compare view when the diff says which two filings it compared, snapshot otherwise."""
    old = (diff or {}).get('from_accession_number')
    new = (diff or {}).get('to_accession_number')
    if old and new and old != new:
        return dashboard_compare_url(base_url, fund_name, old, new)
    return dashboard_fund_url(base_url, fund_name)


def links_line(buttons: Sequence[Button]) -> str:
    """The same buttons as inline text links - the fallback when Telegram refuses a button."""
    if not buttons:
        return ''
    links = [f"<a href='{_esc(url)}'>{_esc(label)}</a>" for label, url in buttons]
    return '🔗 ' + ' · '.join(links)


# --------------------------------------------------------------------------- #
# Position sizes
# --------------------------------------------------------------------------- #


def _value_multiplier(diff: Dict) -> int:
    """Whether the diff's values are dollars (x1) or thousands of dollars (x1000).

    13F values were reported in thousands until 2023 and in dollars since, and
    storage keeps whatever the filing said. Like ``src/web/value_units.py``, pick
    the scale whose median implied share price lands closest to $100.
    """
    prices = []
    for position in (diff.get('new_positions') or []) + (diff.get('closed_positions') or []):
        value, shares = _num(position.get('value_usd')), _num(position.get('shares'))
        if value > 0 and shares > 0:
            prices.append(value / shares)
    for position in (diff.get('increased') or []) + (diff.get('decreased') or []):
        value, shares = _num(position.get('new_value_usd')), _num(position.get('new_shares'))
        if value > 0 and shares > 0:
            prices.append(value / shares)
    if not prices:
        return 1
    mid = median(prices)
    return min((1, 1000), key=lambda scale: abs(math.log10(mid * scale) - 2))


def _moves(diff: Optional[Dict]) -> List[Tuple[float, str]]:
    """Every position change as (estimated dollars traded, one-line description)."""
    if not diff:
        return []
    scale = _value_multiplier(diff)
    moves: List[Tuple[float, str]] = []

    for key, verb in (('new_positions', 'Nuova'), ('closed_positions', 'Chiusa')):
        for position in diff.get(key) or []:
            dollars = _num(position.get('value_usd')) * scale
            moves.append((dollars, f"{verb}: {_esc(position.get('issuer_name'))} ({fmt_money(dollars)})"))

    for key, verb in (('increased', 'Aumentata'), ('decreased', 'Ridotta')):
        for position in diff.get(key) or []:
            new_shares = _num(position.get('new_shares'))
            price = _num(position.get('new_value_usd')) / new_shares if new_shares else 0
            # Shares traded at this quarter's price: a position that only moved
            # with the market is not a trade, so the value change would mislead.
            dollars = abs(new_shares - _num(position.get('old_shares'))) * price * scale
            pct = _num(position.get('pct_change'))
            sign = '+' if pct >= 0 else '−'
            moves.append((
                dollars,
                f"{verb}: {_esc(position.get('issuer_name'))} {sign}{abs(pct):.0f}% (~{fmt_money(dollars)})",
            ))

    return moves


def _top_move(diff: Optional[Dict]) -> str:
    sized = [move for move in _moves(diff) if move[0] > 0]
    return max(sized, key=lambda move: move[0])[1] if sized else ''


def _dollars_moved(diff: Optional[Dict]) -> float:
    return sum(dollars for dollars, _ in _moves(diff))


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
    form: str = '',
    report_date: str = '',
) -> str:
    """A single filing as a headline - the everyday alert. Links go in ``headline_buttons``."""
    heading = f"🔔 <b>{_esc(fund_name)}</b>"
    quarter = period_label(report_date)
    if quarter:
        heading += f" — {quarter}"
    lines = [heading, f"📅 {fmt_datetime(filing_date)}"]

    if is_amendment(form):
        # An amendment often lists only the rows it adds or corrects, so against
        # the full previous filing it can show hundreds of phantom "chiuse".
        lines.append(f"✏️ Rettifica ({_esc(form)}): il confronto può essere parziale")

    summary = _change_summary(portfolio_diff)
    if summary:
        lines.append(f"📊 {summary}")
    elif not holdings_saved:
        lines.append("⚠️ holdings non ancora elaborate")

    top = _top_move(portfolio_diff)
    if top:
        lines.append(f"🔝 {top}")

    if _esc(filer_name) and filer_name != fund_name:
        lines.append(f"🏢 <i>{_esc(filer_name)}</i>")

    return '\n'.join(lines)


def headline_buttons(
    fund_name: str,
    filing_url: str,
    dashboard_base_url: str,
    portfolio_diff: Optional[Dict] = None,
) -> List[Button]:
    buttons: List[Button] = []
    if dashboard_base_url:
        url = _fund_url(dashboard_base_url, fund_name, portfolio_diff)
        buttons.append(('📊 Confronto' if 'tab=compare' in url else '📊 Dashboard', url))
    if filing_url:
        buttons.append(('📄 EDGAR', filing_url))
    return buttons


def format_digest(
    alerts: Sequence[Dict],
    dashboard_base_url: str,
    period: Optional[FilingPeriod] = None,
    filed: Optional[int] = None,
    tracked: Optional[int] = None,
) -> str:
    """Many filings rolled into one message - what a deadline wave should look like.

    Replaces the 42 separate messages that arrived on 14 August 2026 with a
    single scannable list, biggest money moved first. ``filed``/``tracked`` put
    the wave's progress in the header, so it needs no message of its own.
    """
    if not alerts:
        return ''

    header = f"📦 <b>{len(alerts)} nuovi filing</b>"
    if period:
        header += f" — {_esc(period.label)}"
    lines = [header]
    if filed is not None and tracked:
        pct = int(round(100 * filed / tracked))
        lines.append(f"📊 {filed} di {tracked} fondi hanno depositato ({pct}%)")
    lines.append('')

    def weight(alert: Dict) -> Tuple[float, int]:
        # Dollars first: a fund with 900 small positions must not outrank one
        # that sold a $2B stake. Counts only break ties when values are missing.
        diff = alert.get('portfolio_diff') or {}
        count = sum(
            len(diff.get(key, []) or [])
            for key in ('new_positions', 'closed_positions', 'increased', 'decreased')
        )
        return _dollars_moved(diff), count

    ordered = sorted(alerts, key=weight, reverse=True)

    for alert in ordered[:MAX_DIGEST_ROWS]:
        fund = alert.get('fund_name') or alert.get('filer_name') or '?'
        diff = alert.get('portfolio_diff')
        url = _fund_url(dashboard_base_url, fund, diff)
        summary = _change_summary(diff)
        row = f"• <a href='{_esc(url)}'>{_esc(fund)}</a>"
        if is_amendment(alert.get('form', '')):
            row += " ✏️"
        if summary:
            row += f" — {summary}"
        lines.append(row)

    if len(ordered) > MAX_DIGEST_ROWS:
        lines.append(f"<i>...e altri {len(ordered) - MAX_DIGEST_ROWS} fondi</i>")

    if any(is_amendment(alert.get('form', '')) for alert in ordered[:MAX_DIGEST_ROWS]):
        lines.append('')
        lines.append("<i>✏️ = rettifica: il confronto può essere parziale</i>")

    return '\n'.join(lines)


def digest_buttons(dashboard_base_url: str) -> List[Button]:
    base = (dashboard_base_url or '').rstrip('/')
    return [('📊 Apri il dashboard', f"{base}/")] if base else []


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
