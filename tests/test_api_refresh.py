"""Smoke tests for the /api/cache/refresh endpoint."""

from __future__ import annotations

import sys
import time

from fastapi.testclient import TestClient

from src.api import refresh
from src.api.app import create_app


client = TestClient(create_app())


def teardown_function(_):
    refresh._current = None
    refresh._history.clear()


def test_refresh_status_when_idle():
    response = client.get("/api/cache/refresh/status")
    assert response.status_code == 200
    body = response.json()
    assert body["running"] is False
    assert body["current"] is None


def test_refresh_post_returns_job(monkeypatch):
    """POSTing should return a job handle without blocking on the real pipeline."""

    class _FakeProc:
        pid = 424242

        def wait(self, timeout=None):  # pragma: no cover - never called in test
            return 0

    captured: dict[str, object] = {}

    def _fake_spawn(command, log_path):
        captured["command"] = list(command)
        captured["log_path"] = log_path
        return _FakeProc()

    monkeypatch.setattr(refresh, "_spawn_subprocess", _fake_spawn)

    response = client.post("/api/cache/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["pid"] == 424242
    assert body["command"][0] == sys.executable
    assert body["command"][1:] == [
        "-m",
        "src.cli.process_historical_13f",
        "full",
        "--yes",
    ]
    assert body["log_path"].endswith(".log")
    assert "running" in body


def test_refresh_status_after_post_reflects_history(monkeypatch):
    class _FakeProc:
        pid = 7

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(refresh, "_spawn_subprocess", lambda cmd, lp: _FakeProc())
    post_resp = client.post("/api/cache/refresh")
    assert post_resp.status_code == 200
    for _ in range(40):
        status = client.get("/api/cache/refresh/status").json()
        if not status["running"]:
            break
        time.sleep(0.05)
    status = client.get("/api/cache/refresh/status").json()
    # Job either finished cleanly or is still tracked as finished (exit_code 0).
    assert status["running"] is False
    history = status["history"]
    assert history, "history should record the finished job"
    assert history[-1]["exit_code"] == 0


def test_refresh_already_running_does_not_respawn(monkeypatch):
    calls: list[object] = []

    class _FakeSlowProc:
        pid = 1

        def wait(self, timeout=None):
            # Block long enough for the second POST to observe the in-flight job.
            time.sleep(0.5)
            return 0

    def _fake_spawn(command, log_path):
        calls.append(command)
        return _FakeSlowProc()

    monkeypatch.setattr(refresh, "_spawn_subprocess", _fake_spawn)
    client.post("/api/cache/refresh")
    client.post("/api/cache/refresh")
    assert len(calls) == 1
    # Wait for the watcher to finalize so the next test starts from a clean slate.
    for _ in range(40):
        if not refresh.is_running():
            break
        time.sleep(0.05)