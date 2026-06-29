"""Overview API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.api._overview_service import (
    build_filings_timeline,
    build_overview_funds,
    build_overview_summary,
    build_recent_filings,
    build_top_held,
)
from src.api.deps import raise_db_error
from src.api.exceptions import DashboardDbError

router = APIRouter(prefix="/api/overview", tags=["overview"])


@router.get("/summary")
def overview_summary() -> dict[str, object]:
    try:
        return build_overview_summary()
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {}


@router.get("/funds")
def overview_funds(filter: str = Query(default="")) -> dict[str, object]:
    try:
        return build_overview_funds(filter)
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {}


@router.get("/recent-filings")
def recent_filings() -> dict[str, object]:
    try:
        return {"rows": build_recent_filings()}
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {"rows": []}


@router.get("/filings-timeline")
def filings_timeline() -> dict[str, object]:
    try:
        return {"rows": build_filings_timeline()}
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {"rows": []}


@router.get("/top-held")
def top_held() -> dict[str, object]:
    try:
        return {"rows": build_top_held()}
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {"rows": []}
