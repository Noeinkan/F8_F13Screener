"""Meta and admin API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from src.api import refresh
from src.api.deps import raise_db_error
from src.api.exceptions import DashboardDbError
from src.api.repository import (
    DB_PATH,
    clear_repository_cache,
    get_dashboard_db_state,
    initialize_dashboard_storage,
    table_exists,
)

router = APIRouter(tags=["meta"])

logger = logging.getLogger(__name__)


def _on_refresh_success() -> None:
    """Clear the in-process repository cache so the next query sees the new DuckDB."""
    clear_repository_cache()
    logger.info("Refresh succeeded; repository cache cleared.")


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/db/state")
def db_state() -> dict[str, object]:
    try:
        _, reader_path, warning = initialize_dashboard_storage()
        db_path_raw, _, _ = get_dashboard_db_state()
        return {
            "db_live": str(DB_PATH),
            "read_path": str(reader_path),
            "warning": warning,
            "snapshot_path": db_path_raw,
        }
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {}


@router.post("/api/cache/refresh")
def refresh_cache() -> dict[str, object]:
    """Kick off a full historical refresh in the background.

    Spawns ``python -m src.cli.process_historical_13f full --yes`` and returns
    immediately. Use ``GET /api/cache/refresh/status`` to poll for completion.
    If a refresh is already running, returns the in-flight job without
    starting a second one.
    """
    try:
        job = refresh.start_refresh(on_success=_on_refresh_success)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail={"message": str(exc)})
    payload = job.to_dict()
    payload["already_running"] = not job.running and job.error is None and job.finished_at is None
    return payload


@router.get("/api/cache/refresh/status")
def refresh_status() -> dict[str, object]:
    """Return the current refresh job (if any) and the last few finished jobs."""
    current = refresh.current_job()
    return {
        "running": refresh.is_running(),
        "current": current.to_dict() if current is not None else None,
        "history": [j.to_dict() for j in refresh.recent_jobs()[-5:]],
    }


@router.get("/api/funds")
def list_funds() -> dict[str, list[str]]:
    from src.api.repository import get_fund_options

    try:
        return {"funds": get_fund_options()}
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {"funds": []}


@router.get("/api/admin/statistics")
def statistics() -> dict[str, object]:
    from src.api.repository import query

    try:
        if not table_exists("statistics"):
            return {"available": False, "row": None}
        stats = query("SELECT * FROM statistics WHERE id = 1")
        if stats.empty:
            return {"available": True, "row": None}
        return {"available": True, "row": stats.iloc[0].to_dict()}
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {"available": False, "row": None}
