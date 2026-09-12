"""CSV export routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from src.api import demo
from src.api.deps import raise_db_error
from src.api.exceptions import DashboardDbError
from src.api.repository import query
from src.api.serialize import dataframe_to_csv_text
from src.web.sql_queries import FULL_HOLDINGS_EXPORT_SQL, LATEST_SNAPSHOT_EXPORT_SQL

router = APIRouter(prefix="/api/overview/exports", tags=["exports"])


@router.get("/full")
def export_full_holdings() -> PlainTextResponse:
    # Also refused by the demo gate; repeated here so the rule survives a
    # caller that never goes through the middleware.
    if demo.is_enabled():
        raise HTTPException(
            status_code=403,
            detail={
                "code": "demo_unavailable",
                "message": demo.BLOCKED_PATHS["/api/overview/exports/full"],
            },
        )
    try:
        csv_text = dataframe_to_csv_text(query(FULL_HOLDINGS_EXPORT_SQL))
    except DashboardDbError as exc:
        raise_db_error(exc)
        csv_text = ""
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="f8_13f_all_holdings.csv"'},
    )


@router.get("/latest")
def export_latest_snapshot() -> PlainTextResponse:
    try:
        csv_text = dataframe_to_csv_text(query(LATEST_SNAPSHOT_EXPORT_SQL))
    except DashboardDbError as exc:
        raise_db_error(exc)
        csv_text = ""
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="f8_13f_latest_snapshot.csv"'},
    )
