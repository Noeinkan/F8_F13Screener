"""Demo session routes: the email gate in front of the public demo.

Every route here 404s when ``DEMO_MODE`` is off -- that is the kill switch. A
normal deployment therefore has no access endpoint at all, rather than one that
happens to reject everything.

The flow is two steps. ``request-access`` takes an address and mails a signed
link to it; ``redeem`` takes the token out of that link and sets the session
cookie. Neither step stores anything, so there is no table of addresses to
leak, purge or keep in step with a retention promise.

The caps live here rather than in ``demo.py`` because they are properties of
the HTTP request -- who asked, how often, and how many links the whole day has
already spent.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date

from fastapi import APIRouter, HTTPException, Request, Response

from src.api import demo, demo_mail

router = APIRouter(prefix="/api/demo", tags=["demo"])

logger = logging.getLogger(__name__)

_HOUR_SECONDS = 3600

# In memory, and that is the right size for this. The demo is a single process
# behind one hostname; a restart forgiving these counters costs at most a few
# extra emails, and the daily cap below is the limit that actually matters.
_ip_requests: dict[str, list[float]] = {}
_email_last_sent: dict[str, float] = {}
_daily_sent: dict[str, int] = {}
_limits_lock = threading.Lock()


def _require_demo() -> None:
    if not demo.is_enabled():
        raise HTTPException(status_code=404, detail="Not found")


def _client_ip(request: Request) -> str:
    # Behind the shared nginx edge the real address is in X-Forwarded-For; the
    # first hop is the client. Falls back to the socket for a direct run.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _check_and_count(ip: str, email: str) -> None:
    """Spend one access link against every cap, or raise the friendly refusal.

    Order matters: the global cap is checked first, because when the day's
    budget is gone no individual visitor's standing should let a send through.
    """
    now = time.time()
    today = date.today().isoformat()

    with _limits_lock:
        sent_today = _daily_sent.get(today, 0)
        if sent_today >= demo.daily_link_cap():
            raise _refuse(
                429,
                "demo_daily_cap",
                "The demo has handed out its links for today. It resets at "
                "midnight UTC -- or write to andrea.aita@noeinsolutions.com and "
                "I will open it for you now.",
            )

        last_sent = _email_last_sent.get(email)
        cooldown = demo.resend_cooldown_seconds()
        if last_sent is not None and now - last_sent < cooldown:
            wait = int(cooldown - (now - last_sent)) + 1
            raise _refuse(
                429,
                "demo_cooldown",
                f"A link is already on its way to that address. Give it {wait} "
                "more seconds, and check the spam folder before asking again.",
            )

        recent = [t for t in _ip_requests.get(ip, []) if now - t < _HOUR_SECONDS]
        if len(recent) >= demo.links_per_ip_per_hour():
            raise _refuse(
                429,
                "demo_rate_limited",
                "That is a lot of links from one connection. Try again in an "
                "hour, or write to andrea.aita@noeinsolutions.com.",
            )

        recent.append(now)
        _ip_requests[ip] = recent
        _email_last_sent[email] = now
        _daily_sent[today] = sent_today + 1
        # One day's key is all that is ever read; the rest is dead weight.
        for stale in [key for key in _daily_sent if key != today]:
            _daily_sent.pop(stale, None)


def _refund(ip: str, email: str) -> None:
    """Give back the budget a failed send took, so a bounce is not a lockout."""
    today = date.today().isoformat()
    with _limits_lock:
        _daily_sent[today] = max(0, _daily_sent.get(today, 1) - 1)
        _email_last_sent.pop(email, None)
        if _ip_requests.get(ip):
            _ip_requests[ip].pop()


def _set_session_cookie(request: Request, response: Response, email: str) -> int:
    token, expires_at = demo.mint_session_token(email)
    response.set_cookie(
        demo.COOKIE_NAME,
        token,
        max_age=demo.session_ttl_minutes() * 60,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return expires_at


@router.get("/session")
def session(request: Request) -> dict:
    """What the frontend asks on load: am I a demo, and am I let in yet?"""
    _require_demo()
    payload = demo.public_config()
    payload["authenticated"] = (
        demo.verify_session_token(request.cookies.get(demo.COOKIE_NAME)) is not None
    )
    return payload


@router.post("/request-access")
async def request_access(request: Request) -> dict:
    """Take an address, mail it a link. Says the same thing either way.

    The response does not reveal whether the address was already seen, or
    whether the send actually succeeded for a real mailbox -- only that the
    request was accepted. There is nothing to enumerate here.
    """
    _require_demo()

    try:
        body = await request.json()
    except Exception:
        body = {}
    email = demo.normalize_email(str((body or {}).get("email") or ""))
    if email is None:
        raise _refuse(
            400,
            "demo_bad_email",
            "That does not look like an email address. The link has to go somewhere.",
        )

    ip = _client_ip(request)
    _check_and_count(ip, email)

    token, _ = demo.mint_link_token(email)
    try:
        demo_mail.send_access_link(email, demo.access_link(token), demo.link_ttl_minutes())
    except demo_mail.MailError as exc:
        _refund(ip, email)
        logger.warning("Demo access link could not be sent: %s", exc)
        raise _refuse(
            502,
            "demo_mail_failed",
            "The link could not be sent just now. Try again in a minute, or "
            "write to andrea.aita@noeinsolutions.com.",
        ) from exc

    notify = demo.notify_address()
    if notify:
        try:
            demo_mail.send_owner_notice(notify, email)
        except demo_mail.MailError as exc:
            # The visitor already has their link; a missing notice is the
            # owner's problem, not theirs.
            logger.warning("Demo owner notice not sent: %s", exc)

    return {
        "sent": True,
        "linkTtlMinutes": demo.link_ttl_minutes(),
        "message": "Link sent. It is good for the next "
        f"{demo.link_ttl_minutes()} minutes -- check the spam folder if it is slow.",
    }


@router.post("/redeem")
async def redeem(request: Request, response: Response) -> dict:
    """Trade the token out of the emailed link for a session cookie."""
    _require_demo()

    try:
        body = await request.json()
    except Exception:
        body = {}
    email = demo.verify_link_token(str((body or {}).get("token") or ""))
    if email is None:
        raise _refuse(
            401,
            "demo_link_invalid",
            "That link has expired or was not one of ours. Ask for a new one -- "
            "it takes a moment.",
        )

    expires_at = _set_session_cookie(request, response, email)
    payload = demo.public_config()
    payload["authenticated"] = True
    payload["expiresAt"] = expires_at
    return payload


@router.post("/logout")
def logout(response: Response) -> dict:
    _require_demo()
    response.delete_cookie(demo.COOKIE_NAME, path="/")
    return {"ok": True}
