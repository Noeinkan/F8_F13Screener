"""The periodic reporter: when it speaks, and - just as important - when it doesn't."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.cli.notify_reporter import Reporter
from src.core import notification_state
from src.core.config import Config


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    queue = tmp_path / "queue"
    queue.mkdir()
    monkeypatch.setattr(notification_state, "NOTIFY_DIR", tmp_path)
    monkeypatch.setattr(notification_state, "NOTIFY_QUEUE_DIR", queue)
    monkeypatch.setattr(notification_state, "NOTIFY_HEALTH_FILE", tmp_path / "health.json")
    monkeypatch.setattr(notification_state, "NOTIFY_SENT_FILE", tmp_path / "sent.json")
    return tmp_path


@pytest.fixture
def reporter(tmp_path):
    config = Config(
        telegram_bot_token="t",
        telegram_chat_id="c",
        sec_user_agent="test test@example.com",
        holdings_db=tmp_path / "holdings.db",
        dashboard_base_url="http://dash.test:5173",
        hedge_funds_cik={"0000909661": "Farallon", "0001423053": "Citadel"},
    )
    return Reporter(config)


@pytest.fixture
def sent(reporter):
    """Capture what would go to Telegram."""
    messages = []
    with patch.object(reporter.notifier, "send_message", side_effect=lambda m: messages.append(m) or True):
        yield messages


NOW = datetime(2026, 9, 12, 9, 0)


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

def test_no_digest_when_nothing_is_queued(reporter, sent):
    assert reporter.flush_digest(NOW) is False
    assert sent == []


def test_a_fresh_queue_is_left_to_fill_up(reporter, sent):
    """A digest sent the instant the first filing lands is just a single alert."""
    notification_state.queue_alert("a", {"fund_name": "A"})

    assert reporter.flush_digest(NOW) is False
    assert sent == []
    assert notification_state.pending_alert_count() == 1


def test_digest_goes_out_once_the_queue_has_aged(reporter, sent):
    notification_state.queue_alert("a", {"fund_name": "A"})
    ripe = datetime.now() + timedelta(minutes=60)

    assert reporter.flush_digest(ripe) is True
    assert len(sent) == 1
    assert "1 nuovi filing" in sent[0]
    assert notification_state.pending_alert_count() == 0


def test_a_burst_is_not_held_back_for_the_age_rule(reporter, sent):
    """Deadline day fills the queue in minutes; the size cap short-circuits the wait."""
    for i in range(25):
        notification_state.queue_alert(f"fund-{i}", {"fund_name": f"Fund {i}"})

    assert reporter.flush_digest(NOW) is True
    assert "25 nuovi filing" in sent[0]


def test_a_failed_digest_puts_the_alerts_back(reporter):
    notification_state.queue_alert("a", {"fund_name": "A", "queued_at": "2026-08-14T10:00:00"})
    ripe = datetime.now() + timedelta(minutes=60)

    with patch.object(reporter.notifier, "send_message", return_value=False):
        assert reporter.flush_digest(ripe) is False

    assert notification_state.pending_alert_count() == 1, "a whole wave must not be lost"


# ---------------------------------------------------------------------------
# Health - the dead-man's switch
# ---------------------------------------------------------------------------

def test_a_healthy_poller_says_nothing(reporter, sent):
    notification_state.record_cycle({"total": 74}, now=NOW - timedelta(minutes=2))

    assert reporter.check_health(NOW) is False
    assert sent == []


def test_a_silent_poller_raises_the_alarm(reporter, sent):
    notification_state.record_cycle({"total": 74}, now=NOW - timedelta(hours=2))

    assert reporter.check_health(NOW) is True
    assert "Screener silenzioso" in sent[0]


def test_the_alarm_is_raised_once_not_every_ten_minutes(reporter, sent):
    notification_state.record_cycle({"total": 74}, now=NOW - timedelta(hours=2))

    reporter.check_health(NOW)
    reporter.check_health(NOW + timedelta(minutes=10))
    reporter.check_health(NOW + timedelta(minutes=20))

    assert len(sent) == 1


def test_a_poller_that_never_ran_also_alarms(reporter, sent):
    assert reporter.check_health(NOW) is True
    assert "Screener mai partito" in sent[0]


def test_recovery_is_announced_and_closes_the_alarm(reporter, sent):
    notification_state.record_cycle({"total": 74}, now=NOW - timedelta(hours=2))
    reporter.check_health(NOW)
    assert notification_state.was_sent("health-alarm-open") is True

    notification_state.record_cycle({"total": 74}, now=NOW + timedelta(minutes=5))
    assert reporter.check_health(NOW + timedelta(minutes=6)) is True

    assert "tornato attivo" in sent[-1]
    assert notification_state.was_sent("health-alarm-open") is False


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

def test_no_heartbeat_before_the_configured_hour(reporter, sent):
    assert reporter.send_heartbeat(datetime(2026, 9, 12, 6, 0)) is False
    assert sent == []


def test_heartbeat_goes_out_once_a_day(reporter, sent):
    notification_state.record_cycle({"total": 74, "matched": 0}, now=NOW)

    assert reporter.send_heartbeat(NOW) is True
    assert reporter.send_heartbeat(NOW + timedelta(hours=3)) is False
    assert len(sent) == 1
    assert "Screener attivo" in sent[0]


def test_heartbeat_can_be_switched_off(reporter, sent):
    reporter.config.enable_heartbeat = False
    assert reporter.send_heartbeat(NOW) is False


def test_no_heartbeat_while_an_alarm_is_open(reporter, sent):
    """'Screener attivo' must not follow 'Screener silenzioso' on the same day."""
    reporter.check_health(NOW)
    assert notification_state.was_sent("health-alarm-open") is True

    assert reporter.send_heartbeat(NOW) is False
    assert not any("Screener attivo" in m for m in sent)


# ---------------------------------------------------------------------------
# Deadline reminder
# ---------------------------------------------------------------------------

def test_no_reminder_two_months_out(reporter, sent):
    assert reporter.send_reminder(NOW) is False


def test_reminder_fires_inside_the_window_and_only_once(reporter, sent):
    # Three days before the Q3 2026 deadline of 14 November.
    near = datetime(2026, 11, 11, 9, 0)

    assert reporter.send_reminder(near) is True
    assert reporter.send_reminder(near + timedelta(hours=6)) is False
    assert "Q3 2026" in sent[0]


# ---------------------------------------------------------------------------
# Wave progress
# ---------------------------------------------------------------------------

def test_no_wave_progress_outside_a_wave(reporter, sent):
    assert reporter.send_wave_progress(NOW) is False


def test_wave_progress_counts_each_fund_once_despite_cik_padding(reporter, sent):
    """seen_filings holds both '909661' and '0000909661' for the same fund."""
    reporter.storage.mark_filing_seen(
        "filing:909661:acc-1", "FARALLON", "909661", "2026-08-14", matched=True,
    )
    reporter.storage.mark_filing_seen(
        "filing:0000909661:acc-2", "FARALLON", "0000909661", "2026-08-14", matched=True,
    )

    during_wave = datetime(2026, 8, 14, 18, 0)
    assert reporter.send_wave_progress(during_wave) is True
    assert "1 di 2 fondi" in sent[0]


def test_wave_progress_is_rate_limited(reporter, sent):
    reporter.storage.mark_filing_seen(
        "filing:0000909661:acc-1", "FARALLON", "0000909661", "2026-08-14", matched=True,
    )
    during_wave = datetime(2026, 8, 14, 18, 0)

    assert reporter.send_wave_progress(during_wave) is True
    assert reporter.send_wave_progress(during_wave + timedelta(hours=1)) is False
    assert len(sent) == 1


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def test_one_broken_check_does_not_silence_the_others(reporter, sent):
    """The health alarm is the one that matters when things are already broken."""
    with patch.object(Reporter, "flush_digest", side_effect=RuntimeError("disk full")):
        reporter.run_once(NOW)

    assert any("Screener silenzioso" in m or "Nessun ciclo" in m for m in sent)
