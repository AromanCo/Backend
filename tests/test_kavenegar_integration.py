"""Offline Lookup simulations through the real OTP routes and test database."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from aroman.authentication.api import COOKIE_NAME, digest
from aroman.authentication.kavenegar import KavenegarSMS
from aroman.authentication.phone import normalize_mobile
from aroman.authentication.sms import FakeSMS, get_sms_provider
from aroman.core.config import Settings, get_settings
from aroman.core.db import get_engine, utcnow
from aroman.main import app
from aroman.models import AuthChallenge, AuthSession

TEMPLATE = "SyntheticTestTemplate"


class LookupSimulator:
    def __init__(self, response: object = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict[str, str]] = []

    def lookup(self, parameters):
        self.calls.append(dict(parameters))
        if self.error is not None:
            raise self.error
        return self.response


def accepted_response():
    return {"return": {"status": 200}, "entries": [{"messageid": 123, "status": 1}]}


def rows_for(mobile):
    mobile_key = digest(normalize_mobile(mobile), get_settings().otp_pepper)
    with Session(get_engine()) as db:
        return list(
            db.scalars(
                select(AuthChallenge)
                .where(AuthChallenge.mobile_digest == mobile_key)
                .order_by(AuthChallenge.created_at, AuthChallenge.id)
            )
        )


def pass_cooldown(mobile):
    with Session(get_engine()) as db:
        row = db.get(AuthChallenge, rows_for(mobile)[-1].id)
        assert row is not None
        row.created_at = utcnow() - timedelta(seconds=61)
        db.commit()


@pytest.fixture
def lookup_client(monkeypatch, request):
    def install(simulator):
        monkeypatch.setitem(
            app.dependency_overrides,
            get_sms_provider,
            lambda: KavenegarSMS(template=TEMPLATE, transport=simulator),
        )

    with TestClient(app, client=(request.node.name, 50000)) as client:
        yield client, install
    # monkeypatch restores any prior override even when a test assertion fails.


def test_accepted_lookup_creates_session_and_consumes_code(lookup_client, caplog):
    client, install = lookup_client
    mobile = "09128881301"
    simulator = LookupSimulator(accepted_response())
    install(simulator)

    challenge = client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    assert challenge.status_code == 202
    assert len(simulator.calls) == 1
    parameters = simulator.calls[0]
    assert parameters["receptor"] == mobile
    assert parameters["template"] == TEMPLATE
    code = parameters["token"]
    assert len(code) == 6 and code.isascii() and code.isdigit()
    assert [row.delivery_status for row in rows_for(mobile)] == ["accepted"]

    verified = client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": code})
    assert verified.status_code == 200
    assert COOKIE_NAME in client.cookies
    assert "httponly" in verified.headers["set-cookie"].lower()
    token = client.cookies[COOKIE_NAME]
    with Session(get_engine()) as db:
        session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_digest == digest(token, get_settings().session_pepper)
            )
        )
        assert session is not None and session.revoked_at is None
    assert client.get("/api/v1/auth/session").status_code == 200
    csrf = verified.json()["csrf_token"]
    assert client.delete("/api/v1/auth/session").status_code == 403
    assert client.delete("/api/v1/auth/session", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/v1/auth/session").status_code == 401
    assert (
        client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": code}).status_code == 400
    )
    assert rows_for(mobile)[0].consumed_at is not None

    public_text = challenge.text + verified.text
    logs = caplog.text
    for secret in (code, mobile, normalize_mobile(mobile), TEMPLATE, str(parameters)):
        assert secret not in public_text
        assert secret not in logs


def test_definitive_rejection_preserves_previous_accepted_code(lookup_client, caplog):
    client, install = lookup_client
    mobile = "09128881302"
    accepted = LookupSimulator(accepted_response())
    install(accepted)
    assert client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
    old_code = accepted.calls[0]["token"]
    pass_cooldown(mobile)

    provider_text = "synthetic-provider-refusal-secret"
    rejected = LookupSimulator({"return": {"status": 400, "message": provider_text}, "entries": []})
    install(rejected)
    response = client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    assert response.status_code == 503
    assert response.json() == {"detail": "SMS delivery unavailable"}
    assert len(rejected.calls) == 1
    assert [row.delivery_status for row in rows_for(mobile)] == ["accepted", "rejected"]
    assert rows_for(mobile)[0].consumed_at is None
    assert (
        client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": old_code}).status_code
        == 200
    )
    for secret in (old_code, rejected.calls[0]["token"], mobile, TEMPLATE, provider_text):
        assert secret not in response.text + caplog.text


@pytest.mark.parametrize("outcome", ["timeout", "connection", "ambiguous"])
def test_uncertain_lookup_stays_pending_without_resend(lookup_client, caplog, outcome):
    client, install = lookup_client
    mobile = {"timeout": "09128881303", "connection": "09128881304", "ambiguous": "09128881305"}[
        outcome
    ]
    provider_text = "synthetic-uncertain-provider-secret"
    if outcome == "timeout":
        simulator = LookupSimulator(error=TimeoutError(provider_text))
    elif outcome == "connection":
        simulator = LookupSimulator(error=ConnectionError(provider_text))
    else:
        simulator = LookupSimulator({"return": {"status": 402, "message": provider_text}})
    install(simulator)
    response = client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    assert response.status_code == 503
    assert response.json() == {"detail": "SMS delivery unavailable"}
    assert len(simulator.calls) == 1
    code = simulator.calls[0]["token"]
    assert rows_for(mobile)[0].delivery_status == "pending"
    pass_cooldown(mobile)
    repeated = client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    assert repeated.status_code == 429
    assert len(simulator.calls) == 1
    assert len(rows_for(mobile)) == 1
    assert (
        client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": code}).status_code == 200
    )
    assert rows_for(mobile)[0].consumed_at is not None
    for secret in (code, mobile, TEMPLATE, provider_text, str(simulator.calls[0])):
        assert secret not in response.text + repeated.text + caplog.text


def test_overlapping_lookup_codes_share_attempts_and_are_consumed(lookup_client):
    client, install = lookup_client
    mobile = "09128881306"
    accepted = LookupSimulator(accepted_response())
    install(accepted)
    assert client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
    old_code = accepted.calls[0]["token"]
    pass_cooldown(mobile)
    pending = LookupSimulator(error=TimeoutError("synthetic timeout"))
    install(pending)
    assert client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 503
    new_code = pending.calls[0]["token"]
    wrong = next(
        value for value in ("999999", "888888", "777777") if value not in (old_code, new_code)
    )
    for _ in range(2):
        assert (
            client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": wrong}).status_code
            == 400
        )
    assert [row.attempts for row in rows_for(mobile)] == [2, 2]
    assert (
        client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": new_code}).status_code
        == 200
    )
    assert all(row.consumed_at is not None for row in rows_for(mobile))
    for code in (old_code, new_code):
        assert (
            client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": code}).status_code
            == 400
        )


def test_overlapping_lookup_codes_share_the_five_attempt_limit(lookup_client):
    client, install = lookup_client
    mobile = "09128881308"
    accepted = LookupSimulator(accepted_response())
    install(accepted)
    assert client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
    old_code = accepted.calls[0]["token"]
    pass_cooldown(mobile)
    pending = LookupSimulator(error=TimeoutError("synthetic timeout"))
    install(pending)
    assert client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 503
    new_code = pending.calls[0]["token"]
    wrong = next(
        value for value in ("999999", "888888", "777777") if value not in (old_code, new_code)
    )
    for attempt in range(5):
        response = client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": wrong})
        assert response.status_code == (429 if attempt == 4 else 400)
    assert [row.attempts for row in rows_for(mobile)] == [5, 5]
    for code in (old_code, new_code):
        assert (
            client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": code}).status_code
            == 400
        )


def test_override_restores_previous_provider_even_after_failure(monkeypatch):
    original = app.dependency_overrides.get(get_sms_provider)
    with pytest.raises(AssertionError, match="synthetic test failure"):
        with monkeypatch.context() as override:
            override.setitem(
                app.dependency_overrides,
                get_sms_provider,
                lambda: KavenegarSMS(template=TEMPLATE, transport=LookupSimulator()),
            )
            raise AssertionError("synthetic test failure")
    assert app.dependency_overrides.get(get_sms_provider) is original


def test_runtime_selection_stays_fake_and_unconfigured_fails_closed(lookup_client, monkeypatch):
    client, install = lookup_client
    assert get_settings().sms_provider == "fake"
    assert isinstance(get_sms_provider(), FakeSMS)
    with pytest.raises(ValidationError):
        Settings(sms_provider="kavenegar")  # type: ignore[arg-type]
    simulator = LookupSimulator(accepted_response())
    install(simulator)
    monkeypatch.setitem(
        app.dependency_overrides,
        get_settings,
        lambda: get_settings().model_copy(update={"sms_provider": "unconfigured"}),
    )
    response = client.post("/api/v1/auth/challenges", json={"mobile": "09128881307"})
    assert response.status_code == 503
    assert response.json() == {"detail": "SMS delivery unavailable"}
    assert simulator.calls == []
    assert rows_for("09128881307") == []
