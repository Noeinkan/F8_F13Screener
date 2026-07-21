"""Helpers for serving a local dashboard snapshot on Windows."""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable


CopyFile = Callable[[Path, Path], object]

logger = logging.getLogger(__name__)

# Snapshots are named "<stem>.<pid>.snapshot.duckdb" so concurrent readers never
# share a file. Nothing removed them, so every restart leaked a copy of the DB.
_SNAPSHOT_PID_RE = re.compile(r"\.(\d+)\.snapshot\.duckdb$")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        import ctypes

        SYNCHRONIZE = 0x00100000  # noqa: N806
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Owned by another user, so it exists.
        return True
    return True


def prune_orphan_snapshots(snapshot_dir: Path, keep_pid: int | None = None) -> list[Path]:
    """Delete snapshots whose owning process is gone. Returns the removed paths."""

    snapshot_dir = Path(snapshot_dir)
    if not snapshot_dir.is_dir():
        return []

    keep_pid = os.getpid() if keep_pid is None else keep_pid
    removed: list[Path] = []

    for candidate in snapshot_dir.glob("*.snapshot.duckdb"):
        match = _SNAPSHOT_PID_RE.search(candidate.name)
        if not match:
            continue
        pid = int(match.group(1))
        if pid == keep_pid or _pid_alive(pid):
            continue
        try:
            candidate.unlink()
        except OSError as exc:
            # Still mapped by a live reader on Windows; it will be retried later.
            logger.debug("Could not remove orphan snapshot %s: %s", candidate, exc)
            continue
        removed.append(candidate)

    if removed:
        logger.info("Removed %s orphan dashboard snapshot(s)", len(removed))
    return removed


def resolve_dashboard_snapshot(
    source_path: Path,
    snapshot_path: Path,
    *,
    copy_func: CopyFile | None = None,
    attempts: int = 5,
    sleep_seconds: float = 0.25,
) -> tuple[Path, str | None]:
    """Refresh a process-local snapshot of the live dashboard DB.

    On Windows, DuckDB files are exclusive across processes. The Streamlit
    dashboard therefore reads from its own snapshot instead of opening the live
    writer database directly.
    """

    source_path = Path(source_path)
    snapshot_path = Path(snapshot_path)
    copy_impl = copy_func or shutil.copy2

    if not source_path.exists():
        raise FileNotFoundError(f"Database non trovato: {source_path}")

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    retries = max(attempts, 1)
    last_error: OSError | None = None

    for attempt in range(retries):
        temp_fd, temp_name = tempfile.mkstemp(
            prefix="dashboard_snapshot_",
            suffix=snapshot_path.suffix,
            dir=str(snapshot_path.parent),
        )
        os.close(temp_fd)
        temp_path = Path(temp_name)

        try:
            copy_impl(source_path, temp_path)
            os.replace(temp_path, snapshot_path)
            return snapshot_path, None
        except OSError as exc:
            last_error = exc
            temp_path.unlink(missing_ok=True)
            if attempt + 1 < retries:
                time.sleep(sleep_seconds * (attempt + 1))

    if snapshot_path.exists():
        snapshot_time = datetime.fromtimestamp(snapshot_path.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        return (
            snapshot_path,
            "DB live occupato; uso snapshot locale aggiornata alle "
            f"{snapshot_time}.",
        )

    if last_error is not None:
        raise last_error

    raise RuntimeError("Impossibile creare la snapshot del database dashboard.")