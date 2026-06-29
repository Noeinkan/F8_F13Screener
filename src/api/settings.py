"""Runtime settings for the F8 dashboard API."""

from __future__ import annotations

import os


DEFAULT_API_PORT = 9001


def cors_origins() -> list[str]:
    raw = (os.getenv("CORS_ORIGINS") or "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
    ]


def api_host() -> str:
    return (os.getenv("API_SERVER_ADDRESS") or "127.0.0.1").strip() or "127.0.0.1"


def api_port() -> int:
    raw = (os.getenv("API_SERVER_PORT") or str(DEFAULT_API_PORT)).strip()
    return int(raw) if raw.isdigit() else DEFAULT_API_PORT


def api_reload_enabled() -> bool:
    return (os.getenv("API_RELOAD") or "").strip().lower() in {"1", "true", "yes", "on"}
