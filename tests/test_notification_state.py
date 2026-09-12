"""The state the poller and the reporter pass between each other."""
from datetime import datetime, timedelta

import pytest

from src.core import notification_state


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point every state file at a temp dir so tests never touch real data."""
    queue = tmp_path / "queue"
    queue.mkdir()
    monkeypatch.setattr(notification_state, "NOTIFY_DIR", tmp_path)
    monkeypatch.setattr(notification_state, "NOTIFY_QUEUE_DIR", queue)
    monkeypatch.setattr(notification_state, "NOTIFY_HEALTH_FILE", tmp_path / "health.json")
    monkeypatch.setattr(notification_state, "NOTIFY_SENT_FILE", tmp_path / "sent.json")
    return tmp_path


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_is_empty_before_the_poller_ever_runs():
    health = notification_state.read_health()

    assert health.last_cycle_at is None
    assert health.age_seconds() is None


def test_recording_a_cycle_makes_the_poller_look_alive():
    now = datetime(2026, 9, 12, 8, 0)
    notification_state.record_cycle({"total": 74, "matched": 1}, now=now)

    health = notification_state.read_health()
    assert health.last_cycle_at == now
    assert health.age_seconds(now + timedelta(minutes=5)) == pytest.approx(300)


def test_daily_counters_accumulate_across_cycles():
    now = datetime(2026, 9, 12, 8, 0)
    notification_state.record_cycle({"total": 40, "matched": 0}, now=now)
    notification_state.record_cycle({"total": 34, "matched": 2}, now=now + timedelta(minutes=2))

    totals = notification_state.read_health().totals_for("2026-09-12")
    assert totals["cycles"] == 2
    assert totals["total"] == 74
    assert totals["matched"] == 2


def test_only_the_last_few_days_of_counters_are_kept():
    base = datetime(2026, 9, 1, 8, 0)
    for offset in range(8):
        notification_state.record_cycle({"total": 1}, now=base + timedelta(days=offset))

    daily = notification_state.read_health().daily
    assert len(daily) == 3
    assert "2026-09-08" in daily


def test_errors_accumulate_until_a_cycle_succeeds():
    notification_state.record_cycle_error("SEC 503")
    notification_state.record_cycle_error("SEC 503 again")

    assert notification_state.read_health().consecutive_errors == 2

    notification_state.record_cycle({"total": 1})
    health = notification_state.read_health()
    assert health.consecutive_errors == 0
    assert health.last_error is None


def test_a_degraded_cycle_proves_life_but_is_not_a_heartbeat():
    healthy_at = datetime(2026, 9, 12, 8, 0)
    notification_state.record_cycle({"total": 10}, now=healthy_at)

    degraded_at = healthy_at + timedelta(minutes=40)
    notification_state.record_cycle_degraded(
        {"total": 0, "fetch_failed": 58},
        "SEC non raggiungibile: 58/58 fondi falliti, ultimo errore HTTP 403",
        now=degraded_at,
    )

    health = notification_state.read_health()
    assert health.last_cycle_at == healthy_at, "an outage must not refresh the healthy-cycle clock"
    assert health.last_attempt_at == degraded_at
    assert health.attempt_age_seconds(degraded_at) == 0
    assert health.consecutive_errors == 1
    assert "HTTP 403" in health.last_error

    totals = health.totals_for("2026-09-12")
    assert totals["cycles"] == 1
    assert totals["degraded_cycles"] == 1
    assert totals["fetch_failed"] == 58


def test_a_healthy_cycle_after_an_outage_clears_the_error():
    notification_state.record_cycle_degraded({}, "SEC non raggiungibile")
    notification_state.record_cycle({"total": 1})

    health = notification_state.read_health()
    assert health.consecutive_errors == 0
    assert health.last_error is None


def test_health_written_before_last_attempt_existed_still_reads(isolated_state):
    (isolated_state / "health.json").write_text(
        '{"last_cycle_at": "2026-09-12T08:00:00", "consecutive_errors": 0}', encoding="utf-8"
    )

    health = notification_state.read_health()
    assert health.last_attempt_at is None
    assert health.attempt_age_seconds(datetime(2026, 9, 12, 8, 5)) == 300


def test_startup_clears_a_stale_error_streak():
    notification_state.record_cycle_error("boom")
    notification_state.record_startup()

    assert notification_state.read_health().consecutive_errors == 0


def test_corrupt_health_file_reads_as_empty_rather_than_raising(isolated_state):
    (isolated_state / "health.json").write_text("{not json", encoding="utf-8")

    assert notification_state.read_health().last_cycle_at is None


# ---------------------------------------------------------------------------
# Alert queue
# ---------------------------------------------------------------------------

def test_queued_alerts_come_back_in_the_order_they_were_queued():
    notification_state.queue_alert("b", {"fund_name": "B", "queued_at": "2026-08-14T10:00:00"})
    notification_state.queue_alert("a", {"fund_name": "A", "queued_at": "2026-08-14T09:00:00"})

    drained = notification_state.drain_alerts()
    assert [a["fund_name"] for a in drained] == ["A", "B"]


def test_draining_empties_the_queue():
    notification_state.queue_alert("x", {"fund_name": "X"})
    assert notification_state.pending_alert_count() == 1

    notification_state.drain_alerts()
    assert notification_state.pending_alert_count() == 0
    assert notification_state.drain_alerts() == []


def test_peeking_leaves_the_queue_intact():
    """What a dry run reads; draining here would silently eat a wave's digest."""
    notification_state.queue_alert("x", {"fund_name": "X"})

    assert [a["fund_name"] for a in notification_state.peek_alerts()] == ["X"]
    assert notification_state.pending_alert_count() == 1


def test_queueing_the_same_filing_twice_stores_it_once():
    """The queue key is the entry_id, so a re-run cannot duplicate an alert."""
    notification_state.queue_alert("filing:1:acc", {"fund_name": "A"})
    notification_state.queue_alert("filing:1:acc", {"fund_name": "A"})

    assert notification_state.pending_alert_count() == 1


def test_entry_ids_with_slashes_and_colons_are_safe_filenames():
    notification_state.queue_alert("filing:0000909661:0000908834-26-000432", {"fund_name": "F"})

    assert notification_state.pending_alert_count() == 1
    assert notification_state.drain_alerts()[0]["fund_name"] == "F"


def test_oldest_pending_age_is_none_for_an_empty_queue():
    assert notification_state.oldest_pending_age_seconds() is None


def test_oldest_pending_age_grows_with_time():
    notification_state.queue_alert("x", {"fund_name": "X"})
    later = datetime.now() + timedelta(minutes=10)

    age = notification_state.oldest_pending_age_seconds(later)
    assert age is not None and age > 550


# ---------------------------------------------------------------------------
# Once-per-event markers
# ---------------------------------------------------------------------------

def test_markers_record_and_clear():
    assert notification_state.was_sent("heartbeat:2026-09-12") is False

    notification_state.mark_sent("heartbeat:2026-09-12")
    assert notification_state.was_sent("heartbeat:2026-09-12") is True

    notification_state.clear_marker("heartbeat:2026-09-12")
    assert notification_state.was_sent("heartbeat:2026-09-12") is False


def test_clearing_an_absent_marker_is_harmless():
    notification_state.clear_marker("never-set")


def test_marker_file_does_not_grow_without_bound():
    base = datetime(2026, 1, 1)
    for i in range(450):
        notification_state.mark_sent(f"marker:{i}", now=base + timedelta(minutes=i))

    # The newest survive, the oldest are pruned.
    assert notification_state.was_sent("marker:449") is True
    assert notification_state.was_sent("marker:0") is False
