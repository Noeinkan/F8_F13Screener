"""Sending the demo's access link.

Plain SMTP through the standard library. No new dependency, and no third-party
API key to keep alive: the demo borrows the same mailbox the rest of the studio
already sends from, configured entirely through environment variables that live
in the server's ``.env`` and never in git.

Configuration, all required for the demo to start:

``DEMO_SMTP_HOST``   host name of the SMTP server
``DEMO_SMTP_PORT``   465 for implicit TLS, 587 for STARTTLS (the default)
``DEMO_SMTP_USER``   the mailbox to authenticate as
``DEMO_SMTP_PASS``   its password
``DEMO_MAIL_FROM``   the From: address (defaults to ``DEMO_SMTP_USER``)

``DEMO_NOTIFY_EMAIL`` is optional: set it and every access request also sends
one line to that address saying who asked. That is the point of asking for an
email at all, so it is worth setting -- but the demo works without it.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from src.api.demo import DemoConfigError

logger = logging.getLogger(__name__)

DEFAULT_PORT = 587
SENDER_NAME = "Noein Solutions"
SUBJECT = "Your link to the 13F Screener demo"


class MailError(RuntimeError):
    """The message could not be handed to the SMTP server."""


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def smtp_host() -> str:
    return _env("DEMO_SMTP_HOST")


def smtp_port() -> int:
    raw = _env("DEMO_SMTP_PORT")
    return int(raw) if raw.isdigit() else DEFAULT_PORT


def smtp_user() -> str:
    return _env("DEMO_SMTP_USER")


def mail_from() -> str:
    return _env("DEMO_MAIL_FROM") or smtp_user()


def is_configured() -> bool:
    return bool(smtp_host() and smtp_user() and _env("DEMO_SMTP_PASS"))


def require_configured() -> None:
    """Refuse to start a demo nobody could get into.

    The deploy's health check only asks whether the server answers, so a demo
    with no working mail would go live looking fine and turn every visitor away
    at the gate. Failing here makes that a deploy failure instead.
    """
    if not is_configured():
        raise DemoConfigError(
            "DEMO_MODE is on but SMTP is not configured, so the access link "
            "could never be sent. Set DEMO_SMTP_HOST, DEMO_SMTP_USER and "
            "DEMO_SMTP_PASS, or unset DEMO_MODE."
        )


def _send(message: EmailMessage) -> None:
    host, port, user, password = smtp_host(), smtp_port(), smtp_user(), _env("DEMO_SMTP_PASS")
    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
                server.login(user, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.starttls(context=context)
                server.login(user, password)
                server.send_message(message)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        # The address is deliberately not logged with the failure: a bounced
        # send is an operational problem, not a reason to keep a stranger's
        # address in a log file the demo has no other use for.
        raise MailError(str(exc)) from exc


def send_access_link(email: str, link: str, ttl_minutes: int) -> None:
    """Mail one visitor the link that opens the demo."""
    message = EmailMessage()
    message["Subject"] = SUBJECT
    message["From"] = formataddr((SENDER_NAME, mail_from()))
    message["To"] = email
    message.set_content(
        "Here is your link to the 13F Screener demo:\n"
        f"\n{link}\n"
        f"\nIt works once you open it and stays good for {ttl_minutes} minutes.\n"
        "\nThe demo is a read-only copy of the dashboard over a frozen snapshot "
        "of SEC 13F filings. Nothing you do in it changes anything, and it does "
        "not refresh.\n"
        "\nIf you did not ask for this, ignore it -- nothing was created and "
        "the address will not be written to again.\n"
        "\n-- Noein Solutions\nhttps://noeinsolutions.com\n"
    )
    _send(message)


def send_owner_notice(to_address: str, visitor_email: str) -> None:
    """One line to the owner: somebody asked for the demo.

    Best effort by design -- a notice that fails must never stop the visitor
    getting in, so the caller logs and carries on.
    """
    message = EmailMessage()
    message["Subject"] = f"13F demo opened by {visitor_email}"
    message["From"] = formataddr((SENDER_NAME, mail_from()))
    message["To"] = to_address
    message["Reply-To"] = visitor_email
    message.set_content(
        f"{visitor_email} requested an access link for the 13F Screener demo.\n"
        "\nReply to this message to reach them directly.\n"
    )
    _send(message)
