"""FastAPI application factory for the F8 13F dashboard API."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api import demo, demo_mail, settings
from src.api.static_site import mount_frontend
from src.api.routers import consensus, exports, funds, holdings, meta, overview
from src.api.routers import demo as demo_routes
from src.core.dashboard_snapshot import prune_orphan_snapshots

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="F8 13F Screener API",
        version="0.1.0",
        description="JSON analytics API backing the F8 13F dashboard.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if demo.is_enabled():
        _install_demo_gate(app)
        demo.stamp_ticker_index()
        _warm_dashboard_snapshot()
        app.include_router(demo_routes.router)
        logger.info(
            "DEMO_MODE on: serving %s behind the shared-password gate.",
            demo.snapshot_db_path(),
        )

    app.include_router(meta.router)
    app.include_router(overview.router)
    app.include_router(exports.router)
    app.include_router(holdings.router)
    app.include_router(funds.router)
    app.include_router(consensus.router)

    # Last, because a mount at "/" matches whatever the routers above did not.
    mount_frontend(app)

    # Each API process writes its own snapshot copy of the DuckDB; without this
    # every restart leaves a few hundred MB behind.
    try:
        from src.api.repository import DASHBOARD_SNAPSHOT_PATH

        prune_orphan_snapshots(DASHBOARD_SNAPSHOT_PATH.parent)
    except Exception as exc:  # never block startup on housekeeping
        logger.warning("Orphan snapshot cleanup skipped: %s", exc)

    return app


def _warm_dashboard_snapshot() -> None:
    """Take the read-only copy of the DuckDB before the first request arrives.

    The API reads through a per-process copy of the database, made on first use.
    The requests that make up one page load arrive together, so on a cold start
    several of them try to make that copy at once and all but one fail -- which
    the dashboard surfaces as a row of 503s that clear on retry.

    Locally that happens once on a machine nobody is watching. A demo container
    is cold for every visitor, so the first thing a stranger would see is the
    error state. Doing the copy at startup costs a second and removes the race
    from the path a visitor is on.
    """
    try:
        from src.api.repository import initialize_dashboard_storage

        initialize_dashboard_storage()
        logger.info("Demo snapshot warmed; first request will not have to copy the DB.")
    except Exception as exc:
        # A demo that cannot read its snapshot should still start and say so on
        # the page, rather than refuse to boot and show nginx's 502 instead.
        logger.warning("Could not warm the demo snapshot: %s", exc)


def _install_demo_gate(app: FastAPI) -> None:
    """Put every /api route behind the demo session cookie.

    A middleware rather than a per-route dependency: a route added later is
    covered by default, which is the direction an accident should fall in.
    """
    # Fail at startup rather than at the first visitor: a demo that cannot
    # mint a session, or cannot send the link that mints one, should not boot.
    demo.session_secret()
    demo.public_base_url()
    demo_mail.require_configured()

    @app.middleware("http")
    async def demo_gate(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        blocked = demo.is_blocked(path)
        if blocked is not None:
            return JSONResponse(
                status_code=403,
                content={"detail": {"code": "demo_unavailable", "message": blocked}},
            )

        if path.rstrip("/") in demo.OPEN_PATHS or path in demo.OPEN_PATHS:
            return await call_next(request)

        if demo.verify_session_token(request.cookies.get(demo.COOKIE_NAME)) is None:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": {
                        "code": "demo_auth_required",
                        "message": "This demo needs an access link. Ask for one on the demo's front page.",
                    }
                },
            )
        return await call_next(request)


app = create_app()
