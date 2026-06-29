"""Fund analysis API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from src.api._fund_service import (
    build_compare_export,
    build_compare_lanes,
    build_compare_sankey,
    build_fund_compare,
    build_fund_header,
    build_fund_history_export,
    build_fund_history_payload,
    build_fund_snapshot,
    build_fund_snapshot_export,
)
from src.api.deps import raise_db_error
from src.api.exceptions import DashboardDbError
from src.api.repository import load_accessions_for_fund
from src.api.serialize import dataframe_to_csv_text

router = APIRouter(prefix="/api/funds", tags=["funds"])


def _safe_filename_token(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value) or "export"


def _csv_response(rows: list[dict], filename: str) -> PlainTextResponse:
    import pandas as pd

    csv_text = dataframe_to_csv_text(pd.DataFrame(rows)) if rows else ""
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{fund}")
def fund_header(fund: str) -> dict[str, object]:
    try:
        return build_fund_header(fund)
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {}


@router.get("/{fund}/accessions")
def fund_accessions(fund: str) -> dict[str, object]:
    try:
        accessions = load_accessions_for_fund(fund)
        return {"accessions": build_fund_header(fund)["accessions"]}
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {"accessions": []}


@router.get("/{fund}/history")
def fund_history(fund: str) -> dict[str, object]:
    try:
        return build_fund_history_payload(fund)
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {}


@router.get("/{fund}/history/export")
def fund_history_export(fund: str) -> PlainTextResponse:
    try:
        payload = build_fund_history_export(fund)
    except DashboardDbError as exc:
        raise_db_error(exc)

    return _csv_response(payload["rows"], payload["filename"])


@router.get("/{fund}/accessions/{accession}/holdings")
def fund_holdings(
    fund: str,
    accession: str,
    view: str = Query(default="normalized", pattern="^(normalized|raw)$"),
    top_n: int = Query(default=10, ge=5, le=25),
    filter: str = Query(default=""),
) -> dict[str, object]:
    try:
        return build_fund_snapshot(fund, accession, view=view, top_n=top_n, filter_text=filter)
    except DashboardDbError as exc:
        raise_db_error(exc)
    return {}


@router.get("/{fund}/accessions/{accession}/holdings/export")
def fund_holdings_export(
    fund: str,
    accession: str,
    view: str = Query(default="normalized", pattern="^(normalized|raw)$"),
    top_n: int = Query(default=10, ge=5, le=25),
    filter: str = Query(default=""),
) -> PlainTextResponse:
    try:
        payload = build_fund_snapshot_export(
            fund, accession, view=view, top_n=top_n, filter_text=filter
        )
    except DashboardDbError as exc:
        raise_db_error(exc)

    return _csv_response(payload["rows"], payload["filename"])


@router.get("/{fund}/compare")
def fund_compare(
    fund: str,
    old_accession: str | None = Query(default=None),
    new_accession: str | None = Query(default=None),
) -> dict[str, object]:
    try:
        return build_fund_compare(fund, old_accession=old_accession, new_accession=new_accession)
    except (DashboardDbError, ValueError) as exc:
        if isinstance(exc, DashboardDbError):
            raise_db_error(exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {}


@router.get("/{fund}/compare/export/{section}")
def fund_compare_export(
    fund: str,
    section: str,
    old_accession: str | None = Query(default=None),
    new_accession: str | None = Query(default=None),
) -> PlainTextResponse:
    try:
        payload = build_compare_export(
            fund,
            section,
            old_accession=old_accession,
            new_accession=new_accession,
        )
    except DashboardDbError as exc:
        raise_db_error(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _csv_response(payload["rows"], payload["filename"])


@router.get("/{fund}/compare/charts/sankey")
def fund_compare_sankey(
    fund: str,
    old_accession: str | None = Query(default=None),
    new_accession: str | None = Query(default=None),
    top_n: int = Query(default=20, ge=5, le=40),
    top_n_buys: int | None = Query(default=None, ge=5, le=50),
    top_n_sells: int | None = Query(default=None, ge=5, le=50),
    scale_mode: str | None = Query(default=None),
    min_visible_pct: float | None = Query(default=None, ge=0, le=100),
    include_options: bool = Query(default=False),
) -> dict[str, object]:
    try:
        return build_compare_sankey(
            fund,
            old_accession=old_accession,
            new_accession=new_accession,
            top_n=top_n,
            top_n_buys=top_n_buys,
            top_n_sells=top_n_sells,
            scale_mode=scale_mode,
            min_visible_pct=min_visible_pct,
            include_options=include_options,
        )
    except (DashboardDbError, ValueError) as exc:
        if isinstance(exc, DashboardDbError):
            raise_db_error(exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {}


@router.get("/{fund}/compare/charts/lanes")
def fund_compare_lanes(
    fund: str,
    old_accession: str | None = Query(default=None),
    new_accession: str | None = Query(default=None),
    top_n: int = Query(default=20, ge=5, le=40),
    top_n_buys: int | None = Query(default=None, ge=5, le=50),
    top_n_sells: int | None = Query(default=None, ge=5, le=50),
    include_options: bool = Query(default=False),
) -> dict[str, object]:
    try:
        return build_compare_lanes(
            fund,
            old_accession=old_accession,
            new_accession=new_accession,
            top_n=top_n,
            top_n_buys=top_n_buys,
            top_n_sells=top_n_sells,
            include_options=include_options,
        )
    except (DashboardDbError, ValueError) as exc:
        if isinstance(exc, DashboardDbError):
            raise_db_error(exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rows": []}
