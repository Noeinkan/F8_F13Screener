"""Shared API helpers."""

from __future__ import annotations

from fastapi import HTTPException

from src.api.exceptions import DashboardDbError


def raise_db_error(exc: DashboardDbError) -> None:
    raise HTTPException(
        status_code=503,
        detail={"message": str(exc), "recovery_hint": exc.recovery_hint},
    ) from exc
