"""Offline transport and deployment configuration checks using synthetic values only."""

import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from aroman.authentication.api import client_digest, digest
from aroman.core.config import Settings, get_settings
from aroman.main import app
from tests.conftest import login

DB_PASSWORD = "SYNTHETIC_DB_PASSWORD_7c8d"
OTP_PEPPER = "SYNTHETIC_OTP_PEPPER_" + "a" * 32
SESSION_PEPPER = "SYNTHETIC_SESSION_PEPPER_" + "b" * 32
TOKEN = "SYNTHETIC_SESSION_TOKEN_9e2f"


def settings(**changes):
    values = {
        "_env_file": None,
        "environment": "staging",
        "database_url": f"postgresql+psycopg://app:{DB_PASSWORD}@db/aroman",
        "otp_pepper": OTP_PEPPER,
        "session_pepper": SESSION_PEPPER,
        "sms_provider": "unconfigured",
        "cors_origins": "https://app.example.test",
        "cookie_secure": True,
    }
    return Settings(**(values | changes))


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize(
    "changes",
    [
        {"sms_provider": "fake", "fake_sms_enabled": True},
        {"sms_provider": "fake"},
        {"database_url": "sqlite:///synthetic.db"},
        {"cookie_secure": False},
        {"cors_origins": "http://app.example.test"},
        {"cors_origins": "https://*.example.test"},
        {"cors_origins": "*"},
        {"cors_origins": "https://app.example.test/path"},
        {"cors_origins": "https://app.example.test:bad"},
        {"cookie_samesite": "none", "cookie_secure": False},
    ],
)
def test_real_environment_rejects_insecure_configuration(environment, changes):
    with pytest.raises(ValidationError):
        settings(environment=environment, **changes)


def test_unconfigured_provider_allowed_and_secret_errors_are_redacted(caplog):
    configured = settings()
    assert configured.sms_provider == "unconfigured"
    assert all(
        secret not in repr(configured) for secret in (DB_PASSWORD, OTP_PEPPER, SESSION_PEPPER)
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ValidationError) as error:
            settings(cookie_secure=False, trusted_proxy_cidrs="SYNTHETIC_BAD_CIDR_" + TOKEN)
    output = str(error.value) + caplog.text
    assert all(secret not in output for secret in (DB_PASSWORD, OTP_PEPPER, SESSION_PEPPER, TOKEN))


@pytest.mark.parametrize("cidrs", ["invalid", "10.0.0.0/99", "10.0.0.1/8", "::1/999"])
def test_invalid_proxy_network_rejected(cidrs):
    with pytest.raises(ValidationError, match="Invalid trusted proxy CIDR"):
        settings(trusted_proxy_cidrs=cidrs)


def request(peer, forwarded, extra=()):
    headers = [(b"x-forwarded-for", forwarded.encode()), *extra]
    return Request(
        {
            "type": "http", "method": "POST", "path": "/api/v1/auth/verify",
            "query_string": b"", "headers": headers, "client": (peer, 50000),
        }
    )


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("192.0.2.9", "198.51.100.8", "192.0.2.9"),
        ("10.0.0.2", "198.51.100.8", "198.51.100.8"),
        ("10.0.0.2", "203.0.113.7, 198.51.100.8, 10.0.0.3", "198.51.100.8"),
        ("10.0.0.2", "invalid, 198.51.100.8", "10.0.0.2"),
        ("10.0.0.2", "198.51.100.8,", "10.0.0.2"),
        ("2001:db8:1::2", "2001:db8:2::8", "2001:db8:2::8"),
        ("2001:db8:1::2", "2001:db8:3::7, 2001:db8:2::8, 2001:db8:1::3", "2001:db8:2::8"),
        ("2001:db8:4::2", "2001:db8:2::8", "2001:db8:4::2"),
    ],
)
def test_forwarded_client_trust(peer, forwarded, expected):
    configured = settings(trusted_proxy_cidrs="10.0.0.0/8,2001:db8:1::/48")
    forged = request(
        peer, forwarded,
        [(b"x-forwarded-proto", b"https"), (b"x-forwarded-host", b"forged.example.test")],
    )
    assert client_digest(forged, configured) == digest(expected, configured.otp_pepper)


def test_untrusted_forwarded_host_and_proto_do_not_change_origin_decision(client, sms):
    headers = {
        "Origin": "https://forged.example.test",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "forged.example.test",
    }
    denied = client.post("/api/v1/auth/challenges", json={"mobile": "09129999101"}, headers=headers)
    assert denied.status_code == 403
    assert denied.headers["Cache-Control"] == "no-store"
    assert sms.messages == []


def test_cors_exact_origin_credentials_and_denial(client):
    path = "/api/v1/auth/session"
    allowed = client.options(path, headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET",
    })
    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert allowed.headers["Access-Control-Allow-Credentials"] == "true"
    for origin in ("http://localhost:3001", "https://localhost:3000", "http://localhost:3000.evil.test"):
        denied = client.options(path, headers={
            "Origin": origin, "Access-Control-Request-Method": "GET",
        })
        assert denied.status_code == 400
        assert denied.headers.get("Access-Control-Allow-Origin") is None


def test_cookie_csrf_origin_no_store_and_no_token_leaks(sms, caplog, monkeypatch):
    # Restore the exact prior override even if an assertion fails.
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: get_settings())
    with TestClient(app, client=("192.0.2.219", 50000)) as client, caplog.at_level(logging.INFO):
        csrf = login(client, sms, "09129999102")
        assert client.get("/api/v1/auth/session").headers["Cache-Control"] == "no-store"
        token = client.cookies.get("aroman_session")
        assert token
        for headers in ({}, {"X-CSRF-Token": "wrong"}):
            denied = client.delete("/api/v1/auth/session", headers=headers)
            assert denied.status_code == 403
            assert denied.headers["Cache-Control"] == "no-store"
            assert token not in denied.text and csrf not in denied.text
        denied = client.delete("/api/v1/auth/session", headers={
            "Origin": "https://forged.example.test", "X-CSRF-Token": csrf,
        })
        assert denied.status_code == 403
        assert client.delete("/api/v1/auth/session", headers={
            "Origin": "http://localhost:3000", "X-CSRF-Token": csrf,
        }).status_code == 204
    assert token not in caplog.text and csrf not in caplog.text


def test_malformed_forwarding_cannot_reset_verify_peer_limit(monkeypatch):
    configured = get_settings().model_copy(update={"trusted_proxy_cidrs": "10.0.0.0/8"})
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: configured)
    with TestClient(app, client=("10.9.8.7", 50000)) as client:
        for attempt in range(30):
            mobile = f"0912888{attempt // 8:04d}"
            response = client.post(
                "/api/v1/auth/verify",
                json={"mobile": mobile, "code": "000000"},
                headers={"X-Forwarded-For": f"spoof-{attempt}, 198.51.100.9"},
            )
            assert response.status_code == 400
        limited = client.post(
            "/api/v1/auth/verify",
            json={"mobile": "09128880004", "code": "000000"},
            headers={"X-Forwarded-For": "another-spoof, 198.51.100.9"},
        )
        assert limited.status_code == 429
        assert limited.headers["Cache-Control"] == "no-store"
