"""Public demo mode: the kill switch, the email gate, and the blocked routes.

Every test builds its own app through ``create_app()`` after setting the
environment, because the gate is installed at app-construction time -- which is
the point: an app built without ``DEMO_MODE`` has no gate and no demo routes to
reach in the first place.

No test sends mail. ``demo_mail`` is replaced with a recorder, so what is
asserted is what the routes decided to send, not what an SMTP server did.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from src.api import demo, demo_mail
from src.api.app import create_app
from src.api.routers import demo as demo_routes

SECRET = "a-long-random-string-for-tests"
PUBLIC_URL = "https://demo.example.com"
VISITOR = "visitor@example.com"


class MailRecorder:
    """Stands in for the SMTP transport and remembers what it was handed."""

    def __init__(self) -> None:
        self.links: list[tuple[str, str, int]] = []
        self.notices: list[tuple[str, str]] = []
        self.fail_links = False

    def send_access_link(self, email: str, link: str, ttl_minutes: int) -> None:
        if self.fail_links:
            raise demo_mail.MailError("transport refused the message")
        self.links.append((email, link, ttl_minutes))

    def send_owner_notice(self, to_address: str, visitor_email: str) -> None:
        self.notices.append((to_address, visitor_email))

    def token_of(self, index: int = -1) -> str:
        return self.links[index][1].split("?t=", 1)[1]


@pytest.fixture(autouse=True)
def clear_limits():
    """The caps are process-wide, so one test's sends must not fund the next."""
    demo_routes._ip_requests.clear()
    demo_routes._email_last_sent.clear()
    demo_routes._daily_sent.clear()
    yield
    demo_routes._ip_requests.clear()
    demo_routes._email_last_sent.clear()
    demo_routes._daily_sent.clear()


@pytest.fixture
def mail(monkeypatch):
    recorder = MailRecorder()
    monkeypatch.setattr(demo_routes.demo_mail, "send_access_link", recorder.send_access_link)
    monkeypatch.setattr(demo_routes.demo_mail, "send_owner_notice", recorder.send_owner_notice)
    return recorder


@pytest.fixture
def demo_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_SESSION_SECRET", SECRET)
    monkeypatch.setenv("DEMO_PUBLIC_URL", PUBLIC_URL)
    monkeypatch.setenv("F8_DASHBOARD_DB", str(tmp_path / "snapshot.duckdb"))
    # Enough SMTP settings for the startup check; nothing is actually sent.
    monkeypatch.setenv("DEMO_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("DEMO_SMTP_USER", "demo@example.com")
    monkeypatch.setenv("DEMO_SMTP_PASS", "not-a-real-password")
    for name in (
        "DEMO_SESSION_TTL_MINUTES",
        "DEMO_LINK_TTL_MINUTES",
        "DEMO_LINKS_PER_IP_PER_HOUR",
        "DEMO_RESEND_COOLDOWN_SECONDS",
        "DEMO_DAILY_LINK_CAP",
        "DEMO_NOTIFY_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture
def demo_client(demo_env, mail):
    with TestClient(create_app()) as client:
        client.mail = mail
        yield client


@pytest.fixture
def normal_client(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    with TestClient(create_app()) as client:
        yield client


def _ask(client: TestClient, email: str = VISITOR):
    return client.post("/api/demo/request-access", json={"email": email})


def _enter(client: TestClient, email: str = VISITOR):
    """Walk the whole gate: ask for a link, then redeem the one that was sent."""
    assert _ask(client, email).status_code == 200
    return client.post("/api/demo/redeem", json={"token": client.mail.token_of()})


# --- the kill switch -------------------------------------------------------


def test_demo_routes_are_absent_without_the_env_var(normal_client):
    """DEMO_MODE off: there is no gate to find, not a locked one."""
    assert normal_client.post("/api/demo/request-access", json={"email": VISITOR}).status_code == 404
    assert normal_client.post("/api/demo/redeem", json={"token": "x"}).status_code == 404
    assert normal_client.get("/api/demo/session").status_code == 404


def test_normal_mode_does_not_gate_the_api(normal_client):
    assert normal_client.get("/api/health").status_code == 200
    # An ordinary analytics route answers without any cookie at all.
    assert normal_client.get("/api/db/state").status_code in {200, 500}


def test_demo_mode_refuses_to_start_without_a_secret(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.delenv("DEMO_SESSION_SECRET", raising=False)
    with pytest.raises(demo.DemoConfigError):
        create_app()


def test_demo_mode_refuses_to_start_without_a_public_url(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_SESSION_SECRET", SECRET)
    monkeypatch.delenv("DEMO_PUBLIC_URL", raising=False)
    with pytest.raises(demo.DemoConfigError):
        create_app()


def test_demo_mode_refuses_to_start_without_working_mail(monkeypatch):
    """A demo nobody could be let into should fail the deploy, not pass it."""
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_SESSION_SECRET", SECRET)
    monkeypatch.setenv("DEMO_PUBLIC_URL", PUBLIC_URL)
    monkeypatch.delenv("DEMO_SMTP_HOST", raising=False)
    with pytest.raises(demo.DemoConfigError):
        create_app()


# --- the gate --------------------------------------------------------------


def test_api_needs_the_cookie(demo_client):
    response = demo_client.get("/api/db/state")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "demo_auth_required"


def test_health_stays_open_for_the_deploy_probe(demo_client):
    assert demo_client.get("/api/health").status_code == 200


def test_session_reports_unauthenticated_before_the_link_is_used(demo_client):
    payload = demo_client.get("/api/demo/session").json()
    assert payload["demo"] is True
    assert payload["authenticated"] is False


def test_requesting_a_link_mails_one(demo_client):
    response = _ask(demo_client)
    assert response.status_code == 200
    assert response.json()["sent"] is True
    assert len(demo_client.mail.links) == 1
    email, link, ttl = demo_client.mail.links[0]
    assert email == VISITOR
    assert link.startswith(f"{PUBLIC_URL}/?t=")
    assert ttl == demo.link_ttl_minutes()


def test_the_emailed_link_opens_the_api(demo_client):
    assert _enter(demo_client).status_code == 200
    assert demo_client.get("/api/demo/session").json()["authenticated"] is True
    assert demo_client.get("/api/db/state").status_code == 200


def test_a_junk_address_is_refused_before_anything_is_sent(demo_client):
    response = _ask(demo_client, "not-an-address")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "demo_bad_email"
    assert demo_client.mail.links == []


def test_a_forged_token_does_not_open_anything(demo_client):
    response = demo_client.post("/api/demo/redeem", json={"token": "l.abc.9999999999.deadbeef"})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "demo_link_invalid"
    assert demo_client.get("/api/db/state").status_code == 401


def test_logout_closes_the_session(demo_client):
    _enter(demo_client)
    assert demo_client.post("/api/demo/logout").status_code == 200
    assert demo_client.get("/api/db/state").status_code == 401


def test_the_owner_is_notified_when_an_address_is_configured(demo_env, monkeypatch, mail):
    monkeypatch.setenv("DEMO_NOTIFY_EMAIL", "owner@example.com")
    with TestClient(create_app()) as client:
        client.mail = mail
        assert _ask(client).status_code == 200
    assert mail.notices == [("owner@example.com", VISITOR)]


def test_a_failed_notice_does_not_cost_the_visitor_their_link(demo_env, monkeypatch, mail):
    monkeypatch.setenv("DEMO_NOTIFY_EMAIL", "owner@example.com")

    def boom(to_address: str, visitor_email: str) -> None:
        raise demo_mail.MailError("owner mailbox full")

    monkeypatch.setattr(demo_routes.demo_mail, "send_owner_notice", boom)
    with TestClient(create_app()) as client:
        client.mail = mail
        assert _ask(client).status_code == 200
        assert client.post("/api/demo/redeem", json={"token": mail.token_of()}).status_code == 200


# --- tokens ----------------------------------------------------------------


def test_a_session_token_expires(demo_env):
    token, _ = demo.mint_session_token(
        VISITOR, now=time.time() - demo.session_ttl_minutes() * 60 - 1
    )
    assert demo.verify_session_token(token) is None


def test_a_link_token_expires(demo_env):
    token, _ = demo.mint_link_token(VISITOR, now=time.time() - demo.link_ttl_minutes() * 60 - 1)
    assert demo.verify_link_token(token) is None


def test_a_link_token_is_not_a_session_token(demo_env):
    """Kinds are signed in, so the short-lived one cannot be presented as a cookie."""
    link_token, _ = demo.mint_link_token(VISITOR)
    assert demo.verify_session_token(link_token) is None
    session_token, _ = demo.mint_session_token(VISITOR)
    assert demo.verify_link_token(session_token) is None


def test_the_signature_is_checked(demo_env):
    token, _ = demo.mint_session_token(VISITOR)
    kind, encoded, expiry, signature = token.split(".")
    assert demo.verify_session_token(token) == VISITOR
    assert demo.verify_session_token(f"{kind}.{encoded}.{expiry}.deadbeef") is None
    # Extending the expiry invalidates the signature it was minted with.
    assert demo.verify_session_token(f"{kind}.{encoded}.{int(expiry) + 10_000}.{signature}") is None


def test_rotating_the_secret_invalidates_outstanding_sessions(demo_env, monkeypatch):
    token, _ = demo.mint_session_token(VISITOR)
    monkeypatch.setenv("DEMO_SESSION_SECRET", "a-different-secret")
    assert demo.verify_session_token(token) is None


# --- the caps --------------------------------------------------------------


def test_the_same_address_cannot_be_mailed_twice_in_a_row(demo_client):
    assert _ask(demo_client).status_code == 200
    second = _ask(demo_client)
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "demo_cooldown"
    assert len(demo_client.mail.links) == 1


def test_one_connection_is_capped_per_hour(demo_env, monkeypatch, mail):
    monkeypatch.setenv("DEMO_LINKS_PER_IP_PER_HOUR", "2")
    monkeypatch.setenv("DEMO_RESEND_COOLDOWN_SECONDS", "1")
    with TestClient(create_app()) as client:
        client.mail = mail
        assert _ask(client, "one@example.com").status_code == 200
        assert _ask(client, "two@example.com").status_code == 200
        capped = _ask(client, "three@example.com")
        assert capped.status_code == 429
        assert capped.json()["detail"]["code"] == "demo_rate_limited"
    assert len(mail.links) == 2


def test_the_whole_day_has_a_ceiling(demo_env, monkeypatch, mail):
    """The one cap that stops a scripted afternoon becoming a mail-reputation problem."""
    monkeypatch.setenv("DEMO_DAILY_LINK_CAP", "1")
    monkeypatch.setenv("DEMO_LINKS_PER_IP_PER_HOUR", "50")
    monkeypatch.setenv("DEMO_RESEND_COOLDOWN_SECONDS", "1")
    with TestClient(create_app()) as client:
        client.mail = mail
        assert _ask(client, "one@example.com").status_code == 200
        capped = _ask(client, "two@example.com")
        assert capped.status_code == 429
        assert capped.json()["detail"]["code"] == "demo_daily_cap"
    assert len(mail.links) == 1


def test_a_send_that_fails_is_refunded_not_charged(demo_env, mail):
    """A bounce must not spend the visitor's one try and lock them out."""
    with TestClient(create_app()) as client:
        client.mail = mail
        mail.fail_links = True
        failed = _ask(client)
        assert failed.status_code == 502
        assert failed.json()["detail"]["code"] == "demo_mail_failed"

        mail.fail_links = False
        assert _ask(client).status_code == 200
    assert len(mail.links) == 1


# --- what stays shut even once you are in ----------------------------------


def test_refresh_is_refused_in_demo_mode(demo_client):
    _enter(demo_client)
    response = demo_client.post("/api/cache/refresh")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "demo_unavailable"


def test_full_export_is_refused_in_demo_mode(demo_client):
    _enter(demo_client)
    response = demo_client.get("/api/overview/exports/full")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "demo_unavailable"


def test_blocked_routes_are_shut_before_the_session_check(demo_client):
    """A visitor with no cookie gets the same refusal, not a 401 that hints."""
    assert demo_client.post("/api/cache/refresh").status_code == 403
