"""Background refresh manager for the dashboard API.

The "Refresh data" button is supposed to rebuild the canonical DuckDB by
running ``python -m src.cli.process_historical_13f full --yes``. The actual
historical pipeline can take a long time (catalogue + holdings), so the work
is spawned as a detached subprocess and the API returns immediately with a
job handle. A companion ``status()`` accessor lets the UI poll for progress.

The module is self-contained: it does not import anything from
``src.api.repository`` at import time (only via the optional callback passed
to :func:`on_success`) so the API can start even if the DuckDB is broken.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class RefreshJob:
    """In-memory record of one refresh invocation."""

    pid: int
    started_at: float
    command: list[str]
    log_path: str
    finished_at: Optional[float] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None

    @property
    def running(self) -> bool:
        return self.finished_at is None

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["running"] = self.running
        if self.finished_at is not None:
            d["duration_seconds"] = round(self.finished_at - self.started_at, 2)
        return d


_lock = threading.Lock()
_current: Optional[RefreshJob] = None
_history: list[RefreshJob] = []
MAX_HISTORY = 10


def _log_dir() -> Path:
    # Logs live next to the data dir so they're easy to find on the Hetzner box.
    from src.core.paths import LOGS_DIR  # local import to avoid cycles

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR


def _spawn_subprocess(command: list[str], log_path: Path) -> subprocess.Popen[bytes]:
    """Spawn ``command`` detached so closing the API does not kill the refresh."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "ab", buffering=0)
    kwargs: dict[str, object] = {
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "cwd": str(Path(__file__).resolve().parents[2]),
        "env": os.environ.copy(),
        "close_fds": True,
    }
    if os.name == "nt":
        # DETACHED_PROCESS so the child outlives the API even if it crashes.
        DETACHED_PROCESS = 0x00000008  # noqa: N806
        CREATE_NEW_PROCESS_GROUP = 0x00000200  # noqa: N806
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]


def _wait_and_finalize(
    job: RefreshJob,
    proc: subprocess.Popen[bytes],
    on_success: Optional[Callable[[], None]],
) -> None:
    exit_code = proc.wait()
    job.finished_at = time.time()
    job.exit_code = exit_code
    if exit_code == 0 and on_success is not None:
        try:
            on_success()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("on_success callback failed: %s", exc)
            job.error = f"on_success callback failed: {exc}"
    with _lock:
        _history.append(job)
        if len(_history) > MAX_HISTORY:
            del _history[: len(_history) - MAX_HISTORY]


def start_refresh(on_success: Optional[Callable[[], None]] = None) -> RefreshJob:
    """Start a refresh. Returns the existing job if one is already running.

    The job runs ``python -m src.cli.process_historical_13f full --yes`` in the
    background; ``sys.executable`` is used so the venv's interpreter is picked
    up on the Hetzner deployment (the systemd unit already launches the API
    via the venv python).
    """
    global _current
    with _lock:
        if _current is not None and _current.running:
            return _current

        log_path = _log_dir() / f"refresh_{int(time.time())}_{os.getpid()}.log"
        command = [sys.executable, "-m", "src.cli.process_historical_13f", "full", "--yes"]
        try:
            proc = _spawn_subprocess(command, log_path)
        except OSError as exc:
            job = RefreshJob(
                pid=-1,
                started_at=time.time(),
                command=command,
                log_path=str(log_path),
                finished_at=time.time(),
                exit_code=None,
                error=f"failed to spawn refresh subprocess: {exc}",
            )
            with _lock:
                _history.append(job)
            raise RuntimeError(job.error) from exc

        job = RefreshJob(
            pid=proc.pid,
            started_at=time.time(),
            command=command,
            log_path=str(log_path),
        )
        _current = job

    thread = threading.Thread(
        target=_wait_and_finalize,
        args=(job, proc, on_success),
        name="f8-refresh-watcher",
        daemon=True,
    )
    thread.start()
    logger.info("Started dashboard refresh pid=%s log=%s", proc.pid, log_path)
    return job


def current_job() -> Optional[RefreshJob]:
    global _current
    with _lock:
        if _current is not None and not _current.running:
            _current = None
        return _current


def recent_jobs() -> list[RefreshJob]:
    with _lock:
        return list(_history)


def is_running() -> bool:
    return current_job() is not None