"""Public demo mode: the email gate and the frozen-snapshot settings.

Demo mode turns the dashboard into something a stranger can be handed a link
to. It is off unless ``DEMO_MODE`` is set, and when it is off nothing in this
module runs: no gate, no demo routes, no change to how the app reads its data.

What it changes when on:

* the API reads the frozen snapshot in ``demo/fixtures/`` instead of the live
  DuckDB (via ``F8_DASHBOARD_DB``, which the service file sets);
* every ``/api`` route needs a session cookie, and the only way to get one is to
  give an email address and follow the link sent to it;
* the routes that spend the server's time or touch the live pipeline -- the
  historical refresh, the full CSV export -- answer with a friendly refusal
  even to a visitor who is through the gate.

**The gate proves someone can read an inbox, and nothing more.** It is not
protecting secrets: every figure on the demo comes from filings the SEC
publishes. It exists so that entry is deliberate and attributable to an
address. What makes the demo safe to expose is underneath it -- a read-only
copy of a frozen snapshot, and no route that writes anything.

Two token kinds, both stateless HMACs over ``<kind>.<email>.<expiry>``:

* a **link token**, short-lived, mailed to the visitor;
* a **session token**, minted when a link token is redeemed, kept in a cookie.

Stateless on purpose: no session table, nothing to purge, and rotating
``DEMO_SESSION_SECRET`` invalidates every outstanding link and session at once.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT_DB = REPO_ROOT / "demo" / "fixtures" / "13f_demo.duckdb"
SNAPSHOT_META_NAME = "13f_demo.meta.json"

COOKIE_NAME = "f8_demo"
DEFAULT_SESSION_TTL_MINUTES = 240
DEFAULT_LINK_TTL_MINUTES = 30
DEFAULT_LINKS_PER_IP_PER_HOUR = 5
DEFAULT_RESEND_COOLDOWN_SECONDS = 60
DEFAULT_DAILY_LINK_CAP = 200

_TRUTHY = {"1", "true", "yes", "on"}

# Deliberately permissive. This is a demo gate, not a billing system: the proof
# that an address is real is the visitor following the link sent to it, so the
# only job here is to reject what could not possibly be an address.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


class DemoConfigError(RuntimeError):
    """Demo mode is on but misconfigured; the app must not start half-open."""


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _int_env(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw.isdigit() and int(raw) > 0 else default


def is_enabled() -> bool:
    return _env("DEMO_MODE").lower() in _TRUTHY


def session_secret() -> str:
    """The HMAC key behind both token kinds.

    Deliberately has no default. A demo that falls back to a built-in secret is
    a demo whose links anybody holding this source can forge, and nothing in the
    logs would say so.
    """
    value = _env("DEMO_SESSION_SECRET")
    if not value:
        raise DemoConfigError(
            "DEMO_MODE is on but DEMO_SESSION_SECRET is unset. Set it to a long "
            "random string, or unset DEMO_MODE to run the dashboard normally."
        )
    return value


def public_base_url() -> str:
    """Where the emailed link points. Must be the address visitors use."""
    value = _env("DEMO_PUBLIC_URL")
    if not value:
        raise DemoConfigError(
            "DEMO_MODE is on but DEMO_PUBLIC_URL is unset. The emailed link has "
            "nowhere to point. Set it to the demo's public address."
        )
    return value.rstrip("/")


def snapshot_db_path() -> Path:
    raw = _env("F8_DASHBOARD_DB")
    return Path(raw).expanduser() if raw else DEFAULT_SNAPSHOT_DB


def session_ttl_minutes() -> int:
    return _int_env("DEMO_SESSION_TTL_MINUTES", DEFAULT_SESSION_TTL_MINUTES)


def link_ttl_minutes() -> int:
    return _int_env("DEMO_LINK_TTL_MINUTES", DEFAULT_LINK_TTL_MINUTES)


def links_per_ip_per_hour() -> int:
    return _int_env("DEMO_LINKS_PER_IP_PER_HOUR", DEFAULT_LINKS_PER_IP_PER_HOUR)


def resend_cooldown_seconds() -> int:
    return _int_env("DEMO_RESEND_COOLDOWN_SECONDS", DEFAULT_RESEND_COOLDOWN_SECONDS)


def daily_link_cap() -> int:
    """Global circuit breaker across every visitor.

    This endpoint sends mail to an address a stranger typed. Without a ceiling
    on the whole day, one scripted afternoon turns the demo into a way of
    mailing arbitrary inboxes from this domain, and the cost lands on the
    sending reputation of every other address at it.
    """
    return _int_env("DEMO_DAILY_LINK_CAP", DEFAULT_DAILY_LINK_CAP)


def notify_address() -> str:
    """Where the one-line "somebody opened the demo" note goes, if anywhere."""
    return _env("DEMO_NOTIFY_EMAIL")


def normalize_email(raw: str) -> str | None:
    """Trimmed and lowercased, or ``None`` if it could not be an address."""
    candidate = (raw or "").strip().lower()
    if len(candidate) > 254 or not _EMAIL_RE.match(candidate):
        return None
    return candidate


# --- snapshot metadata -----------------------------------------------------


@lru_cache(maxsize=1)
def _snapshot_meta_cached(meta_path_str: str, mtime_ns: int) -> dict:
    try:
        return json.loads(Path(meta_path_str).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Demo snapshot metadata unreadable at %s: %s", meta_path_str, exc)
        return {}


def snapshot_meta() -> dict:
    """Row counts and the capture date, for the banner. ``{}`` if unreadable.

    An unreadable manifest must not take the demo down -- the banner then says
    less, which is better than a 500 on every page.
    """
    meta_path = snapshot_db_path().parent / SNAPSHOT_META_NAME
    try:
        mtime_ns = meta_path.stat().st_mtime_ns
    except OSError:
        return {}
    return _snapshot_meta_cached(str(meta_path), mtime_ns)


def stamp_ticker_index() -> None:
    """Re-key the shipped ticker index to this copy of the snapshot.

    ``src.web.ticker_index`` treats its cache as stale when the DuckDB's mtime
    differs from the one recorded inside the JSON -- and a git clone or a docker
    build gives the snapshot a fresh mtime every time. Left alone, the demo
    would decide the index was stale and rebuild it, which means calling SEC for
    the ticker reference on the one code path that is supposed to touch nothing.

    Rewriting the recorded mtime is the whole fix. If it cannot be written the
    demo still works: the rebuild fails closed to an empty index and search
    falls back to matching issuer names and CUSIPs.
    """
    index_path = snapshot_db_path().parent / "holdings_ticker_index.json"
    try:
        mtime_ns = snapshot_db_path().stat().st_mtime_ns
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Demo ticker index not stamped (%s); search falls back to names.", exc)
        return
    if payload.get("source_mtime_ns") == mtime_ns:
        return
    payload["source_mtime_ns"] = mtime_ns
    try:
        index_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        logger.warning("Demo ticker index is read-only (%s); search falls back to names.", exc)


# --- tokens ----------------------------------------------------------------

_KIND_LINK = "l"
_KIND_SESSION = "s"


def _signing_key() -> bytes:
    return hashlib.sha256(("f8-demo/" + session_secret()).encode("utf-8")).digest()


def _b64(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _unb64(raw: str) -> str:
    padded = raw + "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def _sign(payload: str) -> str:
    return hmac.new(_signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _mint(kind: str, email: str, ttl_minutes: int, now: float | None = None) -> tuple[str, int]:
    expires_at = int((now if now is not None else time.time()) + ttl_minutes * 60)
    payload = f"{kind}.{_b64(email)}.{expires_at}"
    return f"{payload}.{_sign(payload)}", expires_at


def _verify(kind: str, token: str | None, now: float | None = None) -> str | None:
    """Return the email the token was minted for, or ``None`` if it is no good."""
    if not token or token.count(".") != 3:
        return None
    got_kind, encoded_email, expiry, signature = token.split(".")
    if got_kind != kind or not expiry.isdigit():
        return None
    payload = f"{got_kind}.{encoded_email}.{expiry}"
    try:
        expected = _sign(payload)
    except DemoConfigError:
        return None
    if not hmac.compare_digest(expected, signature):
        return None
    if int(expiry) <= (now if now is not None else time.time()):
        return None
    try:
        return _unb64(encoded_email)
    except (ValueError, UnicodeDecodeError):
        return None


def mint_link_token(email: str, now: float | None = None) -> tuple[str, int]:
    return _mint(_KIND_LINK, email, link_ttl_minutes(), now)


def verify_link_token(token: str | None, now: float | None = None) -> str | None:
    return _verify(_KIND_LINK, token, now)


def mint_session_token(email: str, now: float | None = None) -> tuple[str, int]:
    return _mint(_KIND_SESSION, email, session_ttl_minutes(), now)


def verify_session_token(token: str | None, now: float | None = None) -> str | None:
    return _verify(_KIND_SESSION, token, now)


def access_link(token: str) -> str:
    return f"{public_base_url()}/?t={token}"


# --- what the gate lets through -------------------------------------------

# Reachable without a session: the health probe the deploy uses, and the routes
# a visitor needs before they have a cookie.
OPEN_PATHS = frozenset(
    {
        "/api/health",
        "/api/demo/session",
        "/api/demo/request-access",
        "/api/demo/redeem",
    }
)

# Refused even with a valid session. The refresh spawns a real SEC download on
# the server; the full export streams every row of the snapshot.
BLOCKED_PATHS: dict[str, str] = {
    "/api/cache/refresh": (
        "The demo reads a frozen snapshot, so there is nothing to refresh. "
        "The live screener re-reads SEC EDGAR on a schedule."
    ),
    "/api/cache/refresh/status": (
        "The demo reads a frozen snapshot, so no refresh ever runs here."
    ),
    "/api/overview/exports/full": (
        "The full export is off in the demo -- it is every row of the snapshot. "
        "The per-view CSV downloads all work."
    ),
}


def is_blocked(path: str) -> str | None:
    """Return the refusal message for a path the demo will not serve, else None."""
    return BLOCKED_PATHS.get(path.rstrip("/") or "/")


def public_config() -> dict:
    """What the frontend is told about the demo it is running inside."""
    meta = snapshot_meta()
    return {
        "demo": True,
        "snapshot": {
            "latestFilingDate": meta.get("latestFilingDate"),
            "capturedAt": meta.get("capturedAt"),
            "quarters": meta.get("quarters", []),
            "rows": meta.get("rows"),
            "funds": meta.get("funds"),
            "filings": meta.get("filings"),
        },
        "limits": {
            "sessionTtlMinutes": session_ttl_minutes(),
            "linkTtlMinutes": link_ttl_minutes(),
            "refreshDisabled": True,
            "fullExportDisabled": True,
        },
    }
