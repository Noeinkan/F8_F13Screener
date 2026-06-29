"""Meta and admin API routes."""

from __future__ import annotations

from fastapi import APIRouter

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
def refresh_cache() -> dict[str, bool]:
    clear_repository_cache()
    return {"ok": True}


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
