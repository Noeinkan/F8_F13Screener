"""Message wording - asserted without any network or database."""
from datetime import date, datetime

from src.core import report_builder
from src.core.filing_calendar import FilingPeriod

DASH = "http://77.42.70.26:5173"

Q2 = FilingPeriod(
    quarter="Q2",
    period_year=2026,
    months_label="Apr-Jun",
    period_end=date(2026, 6, 30),
    deadline=date(2026, 8, 14),
)


def _diff(new=0, closed=0, up=0, down=0):
    return {
        "new_positions": [{"issuer_name": f"N{i}"} for i in range(new)],
        "closed_positions": [{"issuer_name": f"C{i}"} for i in range(closed)],
        "increased": [{"issuer_name": f"U{i}"} for i in range(up)],
        "decreased": [{"issuer_name": f"D{i}"} for i in range(down)],
    }


# ---------------------------------------------------------------------------
# Deep links
# ---------------------------------------------------------------------------

def test_dashboard_link_targets_the_fund_analysis_route():
    url = report_builder.dashboard_fund_url(DASH, "Citadel (Kenneth Griffin)")

    assert url.startswith("http://77.42.70.26:5173/fund-analysis?fund=")
    assert "tab=snapshot" in url


def test_dashboard_link_percent_encodes_the_fund_name():
    """Fund names carry spaces, parentheses and '&' - all must survive the URL."""
    url = report_builder.dashboard_fund_url(DASH, "Brown & Co (Jo)")

    assert " " not in url
    assert "%26" in url  # the ampersand


def test_dashboard_link_tolerates_a_trailing_slash_on_the_base():
    assert "//fund-analysis" not in report_builder.dashboard_fund_url(DASH + "/", "X")


# ---------------------------------------------------------------------------
# Headline alert
# ---------------------------------------------------------------------------

def test_headline_carries_counts_not_positions():
    msg = report_builder.format_headline_alert(
        "Citadel", "Citadel Advisors", "2026-08-14T20:27:53", "https://sec.gov/x",
        DASH, holdings_saved=True, portfolio_diff=_diff(new=3, closed=2, up=4, down=1),
    )

    assert "+3 nuove" in msg
    assert "−2 chiuse" in msg
    assert "~5 variate" in msg
    assert "N0" not in msg  # no per-position detail


def test_headline_omits_the_filer_when_it_matches_the_fund():
    msg = report_builder.format_headline_alert(
        "Citadel", "Citadel", "2026-08-14T20:27:53", "https://sec.gov/x", DASH,
    )
    assert msg.count("Citadel") == 2  # the heading, and the dashboard link


def test_headline_shows_the_filer_when_it_differs():
    msg = report_builder.format_headline_alert(
        "Shannon River", "HighTower Advisors, LLC", "2026-08-26T10:02:47",
        "https://sec.gov/x", DASH,
    )
    assert "HighTower Advisors" in msg


def test_headline_flags_unprocessed_holdings():
    msg = report_builder.format_headline_alert(
        "Fund", "Fund", "2026-08-14T20:27:53", "https://sec.gov/x", DASH,
        holdings_saved=False, portfolio_diff=None,
    )
    assert "holdings non ancora elaborate" in msg


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

def test_digest_is_empty_for_no_alerts():
    assert report_builder.format_digest([], DASH, Q2) == ""


def test_digest_names_the_quarter_and_counts_the_filings():
    alerts = [{"fund_name": f"Fund {i}", "portfolio_diff": _diff(new=i)} for i in range(4)]
    msg = report_builder.format_digest(alerts, DASH, Q2)

    assert "4 nuovi filing" in msg
    assert "Q2 2026" in msg


def test_digest_puts_the_biggest_movers_first():
    alerts = [
        {"fund_name": "Quiet", "portfolio_diff": _diff(new=1)},
        {"fund_name": "Busy", "portfolio_diff": _diff(new=30, closed=10)},
    ]
    msg = report_builder.format_digest(alerts, DASH, Q2)

    assert msg.index("Busy") < msg.index("Quiet")


def test_digest_truncates_a_deadline_day_wave():
    """42 funds filed on 14 Aug 2026; Telegram caps a message at 4096 chars."""
    alerts = [{"fund_name": f"Fund {i:02d}", "portfolio_diff": _diff(new=1)} for i in range(42)]
    msg = report_builder.format_digest(alerts, DASH, Q2)

    assert "e altri 17 fondi" in msg
    assert len(msg) < 4096


def test_digest_escapes_fund_names():
    msg = report_builder.format_digest(
        [{"fund_name": "Brown & Co", "portfolio_diff": _diff(new=1)}], DASH, Q2
    )
    assert "Brown &amp; Co" in msg


# ---------------------------------------------------------------------------
# Heartbeat, alarm, reminder, progress
# ---------------------------------------------------------------------------

def test_heartbeat_reports_the_day_and_the_next_deadline():
    msg = report_builder.format_heartbeat(
        date(2026, 9, 12), {"cycles": 40, "total": 2900, "matched": 0}, Q2, 63,
    )

    assert "12 set 2026" in msg
    assert "40 cicli" in msg
    assert "fra 63 giorni" in msg


def test_heartbeat_survives_a_day_with_no_counters():
    msg = report_builder.format_heartbeat(date(2026, 9, 12), {}, None, None)
    assert "0 cicli" in msg


def test_health_alarm_says_how_long_and_what_to_run():
    msg = report_builder.format_health_alarm(
        silent_for_seconds=8040,
        last_cycle_at=datetime(2026, 9, 12, 8, 14),
        last_error="HTTPError 503",
        threshold_minutes=30,
    )

    assert "2h 14m" in msg
    assert "HTTPError 503" in msg
    assert "systemctl status f8-screener" in msg


def test_health_alarm_when_no_cycle_ever_ran():
    """'Silenzioso da mai' is nonsense; a poller that never started says so."""
    msg = report_builder.format_health_alarm(None, None, None, 30)

    assert "Screener mai partito" in msg
    assert "silenzioso da" not in msg


def test_duration_formats_by_magnitude():
    assert report_builder.fmt_duration(90) == "1m"
    assert report_builder.fmt_duration(3660) == "1h 1m"
    assert report_builder.fmt_duration(180000) == "2g 2h"
    assert report_builder.fmt_duration(None) == "mai"


def test_reminder_names_the_quarter_and_the_period():
    msg = report_builder.format_deadline_reminder(Q2, 3)

    assert "Q2 2026" in msg
    assert "14 ago 2026" in msg
    # The calendar carries the dashboard's English label; Telegram gets Italian.
    assert "apr-giu" in msg
    assert "Apr-Jun" not in msg


def test_change_summary_omits_the_zero_parts():
    msg = report_builder.format_headline_alert(
        "Fund", "Fund", "2026-08-14T20:27:53", "https://sec.gov/x", DASH,
        holdings_saved=True, portfolio_diff=_diff(new=0, closed=0, up=2, down=1),
    )

    assert "~3 variate" in msg
    assert "+0" not in msg
    assert "−0" not in msg


def test_wave_progress_reports_a_share_of_tracked_funds():
    msg = report_builder.format_wave_progress(Q2, 31, 48, ["Citadel", "Point72"])

    assert "31 di 48 fondi" in msg
    assert "65%" in msg
    assert "Citadel" in msg


def test_wave_progress_survives_zero_tracked_funds():
    msg = report_builder.format_wave_progress(Q2, 0, 0)
    assert "0%" in msg
