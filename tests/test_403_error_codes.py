from itertools import count

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from aroman.authentication.api import digest
from aroman.authentication.phone import normalize_mobile
from aroman.core.config import Settings, get_settings
from aroman.core.db import get_engine
from aroman.main import app
from aroman.models import AuthChallenge, User
from tests.conftest import login

test_peer_ids = count(1)


@pytest.fixture
def client():
    with TestClient(app, client=(f"192.0.2.{next(test_peer_ids)}", 50000)) as isolated:
        yield isolated


def test_missing_and_incorrect_csrf_do_not_create_concept(client, sms):
    csrf = login(client, sms, "09125550001")
    path = "/api/v1/fragrance-concepts"
    payload = {"name": "Protected concept", "notes": []}

    for headers in ({}, {"X-CSRF-Token": "incorrect"}):
        rejected = client.post(path, json=payload, headers=headers)
        assert rejected.status_code == 403
        assert rejected.json() == {"detail": "CSRF token required", "code": "csrf_invalid"}
        assert client.get(path).json() == []

    created = client.post(path, json=payload, headers={"X-CSRF-Token": csrf})
    assert created.status_code == 201
    assert [item["id"] for item in client.get(path).json()] == [created.json()["id"]]


def test_rotated_csrf_rejects_stale_token_without_revoking_session(client, sms):
    stale = login(client, sms, "09125550002")
    rotated = client.get("/api/v1/auth/csrf")
    assert rotated.status_code == 200
    current = rotated.json()["csrf_token"]
    assert current != stale

    rejected = client.delete("/api/v1/auth/session", headers={"X-CSRF-Token": stale})
    assert rejected.status_code == 403
    assert rejected.json() == {"detail": "CSRF token required", "code": "csrf_invalid"}
    assert client.get("/api/v1/auth/session").status_code == 200

    logged_out = client.delete("/api/v1/auth/session", headers={"X-CSRF-Token": current})
    assert logged_out.status_code == 204
    assert client.get("/api/v1/auth/session").json() == {"detail": "Authentication required"}


def test_denied_origin_has_code_and_does_not_create_challenge(client, sms):
    mobile = "09125550003"
    rejected = client.post(
        "/api/v1/auth/challenges",
        json={"mobile": mobile},
        headers={"Origin": "https://untrusted.example"},
    )
    assert rejected.status_code == 403
    assert rejected.json() == {"detail": "Origin denied", "code": "origin_denied"}
    assert sms.messages == []
    with Session(get_engine()) as db:
        assert db.scalar(
            select(AuthChallenge).where(
                AuthChallenge.mobile_digest
                == digest(normalize_mobile(mobile), get_settings().otp_pepper)
            )
        ) is None


def test_denied_origin_precedes_csrf_on_authenticated_write(client, sms):
    csrf = login(client, sms, "09125550004")
    rejected = client.delete(
        "/api/v1/auth/session",
        headers={"Origin": "https://untrusted.example", "X-CSRF-Token": csrf},
    )
    assert rejected.status_code == 403
    assert rejected.json() == {"detail": "Origin denied", "code": "origin_denied"}
    assert client.get("/api/v1/auth/session").status_code == 200


def test_unavailable_account_has_code_and_does_not_create_session(client, sms):
    mobile = "09125550005"
    with Session(get_engine()) as db:
        db.add(User(mobile_e164=normalize_mobile(mobile), is_active=False))
        db.commit()

    requested = client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    assert requested.status_code == 202
    rejected = client.post(
        "/api/v1/auth/verify", json={"mobile": mobile, "code": sms.messages[-1][1]}
    )
    assert rejected.status_code == 403
    assert rejected.json() == {"detail": "Account unavailable", "code": "account_unavailable"}
    assert "aroman_session" not in client.cookies


def test_unrelated_http_errors_keep_their_response_shapes(client, sms):
    unauthenticated = client.get("/api/v1/auth/session")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json() == {"detail": "Authentication required"}
    invalid = client.post("/api/v1/auth/challenges", json={"mobile": "short"})
    assert invalid.status_code == 422
    assert set(invalid.json()) == {"detail"}
    assert isinstance(invalid.json()["detail"], list)

    mobile = "09125550006"
    assert client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
    limited = client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    assert limited.status_code == 429
    assert limited.json() == {"detail": "Try again later"}

    app.dependency_overrides[get_settings] = lambda: Settings(sms_provider="unconfigured")
    try:
        unavailable = client.post(
            "/api/v1/auth/challenges", json={"mobile": "09125550007"}
        )
        assert unavailable.status_code == 503
        assert unavailable.json() == {"detail": "SMS delivery unavailable"}
    finally:
        app.dependency_overrides.pop(get_settings, None)
