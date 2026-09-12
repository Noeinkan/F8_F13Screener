"""Serve the built React bundle from the API process.

Locally the two halves run separately: Vite on 5173 serves the UI and proxies
``/api`` to FastAPI on 9001. That is the right arrangement for development and
nothing here changes it.

A deployed demo is a different problem. The shared edge on the Hetzner box
proxies one hostname to one container on one port, so the demo has to answer
both the page requests and the API calls from a single process. Setting
``F8_STATIC_DIR`` to the built bundle turns that on; leaving it unset is every
existing deployment, unchanged.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

logger = logging.getLogger(__name__)


def static_dir() -> Path | None:
    raw = (os.getenv("F8_STATIC_DIR") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not (path / "index.html").exists():
        logger.warning("F8_STATIC_DIR=%s has no index.html; not serving a frontend.", path)
        return None
    return path


class SpaStaticFiles(StaticFiles):
    """Static files with the single-page-app fallback.

    React Router owns ``/fund-analysis`` and the rest; on a hard reload the
    browser asks the server for that path, and the server has no such file.
    Answering with ``index.html`` is what lets the router take over -- without
    it, every deep link and every refresh away from ``/`` is a 404.
    """

    async def get_response(self, path: str, scope: Scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return FileResponse(Path(self.directory) / "index.html")


class ApiPassThrough:
    """Let ``/api`` 404s stay 404s instead of being answered with the app shell.

    Mounted at ``/``, the SPA fallback would otherwise hand a React page to a
    mistyped API path, and a client would parse HTML as JSON and report
    something unrelated to what went wrong.
    """

    def __init__(self, app, spa) -> None:
        self.app = app
        self.spa = spa

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "http" and scope.get("path", "").startswith("/api"):
            raise StarletteHTTPException(status_code=404, detail="Not Found")
        await self.spa(scope, receive, send)


def mount_frontend(app: FastAPI) -> Path | None:
    """Mount the built bundle at ``/`` if one is configured. Returns its path."""
    directory = static_dir()
    if directory is None:
        return None
    spa = SpaStaticFiles(directory=str(directory), html=True)
    app.mount("/", ApiPassThrough(app, spa), name="frontend")
    logger.info("Serving the built frontend from %s", directory)
    return directory
