from pathlib import Path
import shutil

import pytest

from src.core.dashboard_snapshot import resolve_dashboard_snapshot


def test_resolve_dashboard_snapshot_creates_fresh_copy(tmp_path):
    source = tmp_path / "13f_dashboard.duckdb"
    snapshot = tmp_path / "cache" / "dashboard.snapshot.duckdb"
    source.write_bytes(b"live-data")

    resolved_path, warning = resolve_dashboard_snapshot(
        source,
        snapshot,
        attempts=1,
        sleep_seconds=0,
    )

    assert resolved_path == snapshot
    assert warning is None
    assert snapshot.read_bytes() == b"live-data"


def test_resolve_dashboard_snapshot_retries_then_succeeds(tmp_path):
    source = tmp_path / "13f_dashboard.duckdb"
    snapshot = tmp_path / "cache" / "dashboard.snapshot.duckdb"
    source.write_bytes(b"live-data")

    attempts = {"count": 0}

    def flaky_copy(src: Path, dst: Path):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError("locked")
        shutil.copy2(src, dst)

    resolved_path, warning = resolve_dashboard_snapshot(
        source,
        snapshot,
        copy_func=flaky_copy,
        attempts=3,
        sleep_seconds=0,
    )

    assert resolved_path == snapshot
    assert warning is None
    assert attempts["count"] == 3
    assert snapshot.read_bytes() == b"live-data"


def test_resolve_dashboard_snapshot_uses_existing_snapshot_when_live_db_locked(tmp_path):
    source = tmp_path / "13f_dashboard.duckdb"
    snapshot = tmp_path / "cache" / "dashboard.snapshot.duckdb"
    source.write_bytes(b"live-data")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(b"stale-data")

    def locked_copy(_src: Path, _dst: Path):
        raise PermissionError("locked")

    resolved_path, warning = resolve_dashboard_snapshot(
        source,
        snapshot,
        copy_func=locked_copy,
        attempts=2,
        sleep_seconds=0,
    )

    assert resolved_path == snapshot
    assert snapshot.read_bytes() == b"stale-data"
    assert warning is not None
    assert "snapshot locale" in warning


def test_resolve_dashboard_snapshot_raises_without_existing_snapshot(tmp_path):
    source = tmp_path / "13f_dashboard.duckdb"
    snapshot = tmp_path / "cache" / "dashboard.snapshot.duckdb"
    source.write_bytes(b"live-data")

    def locked_copy(_src: Path, _dst: Path):
        raise PermissionError("locked")

    with pytest.raises(PermissionError):
        resolve_dashboard_snapshot(
            source,
            snapshot,
            copy_func=locked_copy,
            attempts=2,
            sleep_seconds=0,
        )