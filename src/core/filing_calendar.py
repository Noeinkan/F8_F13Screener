"""
The SEC 13F quarterly calendar.

13F-HR is a quarterly form due 45 days after the quarter ends, and funds almost
all file within a day or two of the deadline. That single fact drives the whole
notification strategy: for ~355 days a year there is genuinely nothing to say,
and for ~10 days there is far too much. Everything that decides *when* to speak
- the pre-deadline reminder, the wave-progress report, whether an alert is
batched into a digest or sent on its own - asks this module first.

The four deadlines mirror ``frontend/src/components/FilingCalendar.tsx`` exactly
so the dashboard and the Telegram messages never disagree about which quarter is
being awaited. Like the dashboard, this does not shift a deadline that lands on
a weekend to the next business day; the real SEC rule does, but a reminder that
arrives a day or two early is harmless and one source of truth is worth more
than that precision.
"""
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

# quarter, period-end (month, day), deadline (month, day), label.
# The period-end year is the deadline year except for Q4, which is reported in
# February of the following year.
_QUARTERS = (
    ('Q4', 12, 31, 2, 14, 'Oct-Dec', -1),
    ('Q1', 3, 31, 5, 15, 'Jan-Mar', 0),
    ('Q2', 6, 30, 8, 14, 'Apr-Jun', 0),
    ('Q3', 9, 30, 11, 14, 'Jul-Sep', 0),
)


@dataclass(frozen=True)
class FilingPeriod:
    """One reporting quarter and the date its 13F-HR is due."""

    quarter: str
    period_year: int
    months_label: str
    period_end: date
    deadline: date

    @property
    def label(self) -> str:
        return f"{self.quarter} {self.period_year}"


def deadlines_for_year(year: int) -> List[FilingPeriod]:
    """The four 13F deadlines that land in ``year``."""
    periods = []
    for quarter, end_m, end_d, dl_m, dl_d, months, year_offset in _QUARTERS:
        period_year = year + year_offset
        periods.append(
            FilingPeriod(
                quarter=quarter,
                period_year=period_year,
                months_label=months,
                period_end=date(period_year, end_m, end_d),
                deadline=date(year, dl_m, dl_d),
            )
        )
    return periods


def _window(today: date) -> List[FilingPeriod]:
    """Deadlines from last year through next year, in chronological order."""
    periods = (
        deadlines_for_year(today.year - 1)
        + deadlines_for_year(today.year)
        + deadlines_for_year(today.year + 1)
    )
    return sorted(periods, key=lambda p: p.deadline)


def latest_deadline(today: date) -> Optional[FilingPeriod]:
    """The most recent deadline that has already passed (the data you should have)."""
    passed = [p for p in _window(today) if p.deadline <= today]
    return passed[-1] if passed else None


def next_deadline(today: date) -> Optional[FilingPeriod]:
    """The next deadline still ahead (the data you are waiting for)."""
    upcoming = [p for p in _window(today) if p.deadline > today]
    return upcoming[0] if upcoming else None


def days_until_next(today: date) -> Optional[int]:
    nxt = next_deadline(today)
    return (nxt.deadline - today).days if nxt else None


def active_window(
    today: date,
    days_before: int = 2,
    days_after: int = 7,
) -> Optional[FilingPeriod]:
    """The filing wave ``today`` falls inside, or ``None`` outside a wave.

    A "wave" is the stretch around a deadline when dozens of funds file within
    hours of each other - the only time batching alerts into a digest beats
    sending them one by one. Outside it, a lone filing (usually an amendment) is
    worth an immediate message.
    """
    for period in _window(today):
        start = date.fromordinal(period.deadline.toordinal() - days_before)
        end = date.fromordinal(period.deadline.toordinal() + days_after)
        if start <= today <= end:
            return period
    return None
