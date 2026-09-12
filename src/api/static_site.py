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

import anyio
from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

logger = logging.getLogger(__name__)

IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
REVALIDATE_CACHE = "no-cache"


def static_dir() -> Path | None:
    raw = (os.getenv("F8_STATIC_DIR") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not (path / "index.html").exists():
        logger.warning("F8_STATIC_DIR=%s has no index.html; not serving a frontend.", path)
        return None
    return path


def cache_control_for(directory: str | os.PathLike, full_path: str | os.PathLike) -> str | None:
    """The ``Cache-Control`` a served file gets, decided by the file itself.

    * ``assets/*``: Vite puts a content hash in every file name there, so a
      given URL never changes content and the browser may keep it for a year.
    * ``*.html`` (``index.html``, also when served as the SPA fallback): always
      revalidate. It names the current hashed assets, so a stale copy would
      keep a browser on the previous build after a redeploy.
    * anything else (favicon, robots.txt): left to the browser's defaults.

    Keyed on the file served rather than the URL asked for: a missing
    ``/assets/old-chunk.js`` answered with ``index.html`` must not be cached
    for a year.
    """
    root = os.path.realpath(directory)
    served = os.path.realpath(full_path)
    try:
        relative = Path(os.path.relpath(served, root))
    except ValueError:  # different drive on Windows: not ours to label
        return None
    if relative.parts and relative.parts[0] == "assets":
        return IMMUTABLE_CACHE
    if relative.suffix.lower() == ".html":
        return REVALIDATE_CACHE
    return None


class SpaStaticFiles(StaticFiles):
    """Static files with the single-page-app fallback and cache headers.

    React Router owns ``/fund-analysis`` and the rest; on a hard reload the
    browser asks the server for that path, and the server has no such file.
    Answering with ``index.html`` is what lets the router take over -- without
    it, every deep link and every refresh away from ``/`` is a 404.
    """

    def file_response(self, full_path, stat_result, scope: Scope, status_code: int = 200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        # Set on the 304 too, so a revalidation keeps the policy in force.
        policy = cache_control_for(self.directory, full_path)
        if policy:
            response.headers["cache-control"] = policy
        return response

    async def get_response(self, path: str, scope: Scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            full_path, stat_result = await anyio.to_thread.run_sync(self.lookup_path, "index.html")
            if stat_result is None:
                raise
            return self.file_response(full_path, stat_result, scope)


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
