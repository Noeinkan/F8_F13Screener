"""The quarterly calendar that decides when the screener speaks."""
from datetime import date

from src.core import filing_calendar


# ---------------------------------------------------------------------------
# The four deadlines
# ---------------------------------------------------------------------------

def test_2026_has_the_four_known_deadlines():
    deadlines = {p.label: p.deadline for p in filing_calendar.deadlines_for_year(2026)}

    assert deadlines["Q4 2025"] == date(2026, 2, 14)
    assert deadlines["Q1 2026"] == date(2026, 5, 15)
    assert deadlines["Q2 2026"] == date(2026, 8, 14)
    assert deadlines["Q3 2026"] == date(2026, 11, 14)


def test_q4_reports_the_previous_year():
    """Q4 is filed in February of the following year, so its period year lags."""
    q4 = next(p for p in filing_calendar.deadlines_for_year(2026) if p.quarter == "Q4")

    assert q4.period_year == 2025
    assert q4.period_end == date(2025, 12, 31)
    assert q4.months_label == "Oct-Dec"


def test_period_ends_precede_their_deadlines_by_about_45_days():
    for period in filing_calendar.deadlines_for_year(2026):
        gap = (period.deadline - period.period_end).days
        assert 44 <= gap <= 46, f"{period.label} gap was {gap}"


# ---------------------------------------------------------------------------
# Where are we now?
# ---------------------------------------------------------------------------

def test_mid_september_is_waiting_on_q3():
    today = date(2026, 9, 12)

    assert filing_calendar.latest_deadline(today).label == "Q2 2026"
    assert filing_calendar.next_deadline(today).label == "Q3 2026"
    assert filing_calendar.days_until_next(today) == 63


def test_january_looks_back_to_the_previous_year():
    """Early January must reach into last year's deadlines, not give up."""
    today = date(2026, 1, 5)

    assert filing_calendar.latest_deadline(today).label == "Q3 2025"
    assert filing_calendar.next_deadline(today).label == "Q4 2025"


def test_deadline_day_itself_counts_as_passed():
    today = date(2026, 8, 14)
    assert filing_calendar.latest_deadline(today).label == "Q2 2026"


# ---------------------------------------------------------------------------
# Filing waves - the window where alerts get batched
# ---------------------------------------------------------------------------

def test_deadline_day_is_inside_the_wave():
    window = filing_calendar.active_window(date(2026, 8, 14))
    assert window is not None and window.label == "Q2 2026"


def test_wave_opens_two_days_early_and_runs_a_week_past():
    assert filing_calendar.active_window(date(2026, 8, 12)) is not None
    assert filing_calendar.active_window(date(2026, 8, 21)) is not None


def test_outside_the_wave_there_is_none():
    # Three days before the window opens, and eight days after it closes.
    assert filing_calendar.active_window(date(2026, 8, 11)) is None
    assert filing_calendar.active_window(date(2026, 8, 22)) is None
    assert filing_calendar.active_window(date(2026, 9, 12)) is None


def test_wave_bounds_are_configurable():
    """A late amendment on 26 August is outside the default window but inside a wider one."""
    late = date(2026, 8, 26)

    assert filing_calendar.active_window(late) is None
    assert filing_calendar.active_window(late, days_after=20) is not None
