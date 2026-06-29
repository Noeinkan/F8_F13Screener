"""FastAPI application factory for the F8 13F dashboard API."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api import settings
from src.api.routers import consensus, exports, funds, holdings, meta, overview


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

    app.include_router(meta.router)
    app.include_router(overview.router)
    app.include_router(exports.router)
    app.include_router(holdings.router)
    app.include_router(funds.router)
    app.include_router(consensus.router)
    return app


app = create_app()
