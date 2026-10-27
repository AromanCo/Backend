from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.requests import Request

from aroman.authentication.api import aware, client_digest, digest
from aroman.authentication.phone import normalize_mobile
from aroman.authentication.sms import UnconfiguredSMS, get_sms_provider
from aroman.core.config import Settings, get_settings
from aroman.core.db import get_db, get_engine, utcnow
from aroman.main import app
from aroman.models import AuthChallenge, AuthSession, Brand, FragranceNote, Product, User
from aroman.seed import seed
from tests.conftest import login


def test_phone_normalization():
    for value in [
        "09121234567",
        "+989121234567",
        "00989121234567",
        "۹۸۹۱۲۱۲۳۴۵۶۷",
        "٠٩١٢١٢٣٤٥٦٧",
        "+98 (912) 123-4567",
    ]:
        assert normalize_mobile(value) == "+989121234567"
    for value in ["02112345678", "0912123456", "091212345678", "not-a-phone"]:
        try:
            normalize_mobile(value)
        except ValueError:
            pass
        else:
            raise AssertionError(value)


def test_real_environment_rejects_fake_sms():
    for environment in ("staging", "production"):
        with pytest.raises(ValueError):
            Settings(
                environment=environment,
                database_url="postgresql+psycopg://user:password@db/aroman",
                otp_pepper="a" * 32,
                session_pepper="b" * 32,
                sms_provider="fake",
                cors_origins="https://example.com",
                cookie_secure=True,
            )
    with pytest.raises(RuntimeError):
        UnconfiguredSMS().send_otp("+989121234567", "123456")
    with pytest.raises(ValueError, match="explicit opt-in"):
        Settings(fake_sms_enabled=False)


def test_forwarded_address_requires_trusted_proxy():
    settings = Settings(trusted_proxy_cidrs="10.0.0.0/8")

    def request(peer, forwarded="1.2.3.4"):
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "query_string": b"",
                "headers": [(b"x-forwarded-for", forwarded.encode())],
                "client": (peer, 1234),
            }
        )

    assert client_digest(request("10.0.0.2"), settings) == digest("1.2.3.4", settings.otp_pepper)
    assert client_digest(request("9.9.9.9"), settings) == digest("9.9.9.9", settings.otp_pepper)
    assert client_digest(request("10.0.0.2", "forged,invalid"), settings) == digest(
        "10.0.0.2", settings.otp_pepper
    )
    assert client_digest(request("10.0.0.2", "10.1.1.1,10.2.2.2"), settings) == digest(
        "10.2.2.2", settings.otp_pepper
    )


def test_health_and_validation(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.post("/api/v1/auth/challenges", json={"mobile": "bad"}).status_code == 422
    assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize(
    ("path", "body", "field", "error_type", "marker"),
    [
        (
            "/api/v1/auth/challenges",
            {"mobile": "SYNTHETIC_MOBILE_MARKER_" * 2},
            "mobile",
            "string_too_long",
            "SYNTHETIC_MOBILE_MARKER_",
        ),
        (
            "/api/v1/auth/verify",
            {"mobile": "SYNTHETIC_MOBILE_MARKER_" * 2, "code": "123456"},
            "mobile",
            "string_too_long",
            "SYNTHETIC_MOBILE_MARKER_",
        ),
        (
            "/api/v1/auth/verify",
            {"mobile": "09120000000", "code": "SYNTHETIC_CODE_MARKER"},
            "code",
            "string_pattern_mismatch",
            "SYNTHETIC_CODE_MARKER",
        ),
    ],
)
def test_auth_validation_does_not_echo_submitted_values(
    client, path, body, field, error_type, marker
):
    response = client.post(path, json=body)
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert marker not in response.text
    errors = response.json()["detail"]
    assert len(errors) == 1
    assert errors[0]["loc"] == ["body", field]
    assert errors[0]["type"] == error_type
    assert errors[0]["msg"]
    assert set(errors[0]) == {"loc", "type", "msg"}


@pytest.mark.parametrize("path", ["/api/v1/auth/challenges", "/api/v1/auth/verify"])
def test_auth_malformed_json_does_not_echo_submitted_values(client, path):
    marker = "SYNTHETIC_JSON_MARKER"
    response = client.post(
        path,
        content=f'{{"mobile":"{marker}",',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert marker not in response.text
    errors = response.json()["detail"]
    assert len(errors) == 1
    assert errors[0]["loc"][0] == "body"
    assert errors[0]["type"] == "json_invalid"
    assert errors[0]["msg"]
    assert set(errors[0]) == {"loc", "type", "msg"}


def test_auth_multiple_invalid_fields_are_redacted(client):
    mobile_marker = "SYNTHETIC_MOBILE_MARKER_"
    code_marker = "SYNTHETIC_CODE_MARKER"
    response = client.post(
        "/api/v1/auth/verify",
        json={"mobile": mobile_marker * 2, "code": code_marker},
    )
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert mobile_marker not in response.text
    assert code_marker not in response.text
    errors = response.json()["detail"]
    assert {(tuple(error["loc"]), error["type"]) for error in errors} == {
        (("body", "mobile"), "string_too_long"),
        (("body", "code"), "string_pattern_mismatch"),
    }
    assert all(error["msg"] and set(error) == {"loc", "type", "msg"} for error in errors)


def test_auth_validation_keeps_valid_flow_and_other_validation_unchanged(client, sms):
    mobile = "09128881236"
    requested = client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    assert requested.status_code == 202
    verified = client.post(
        "/api/v1/auth/verify", json={"mobile": mobile, "code": sms.messages[-1][1]}
    )
    assert verified.status_code == 200

    unrelated = client.get("/api/v1/fragrance-notes", params={"limit": "UNRELATED_MARKER"})
    assert unrelated.status_code == 422
    assert unrelated.json()["detail"][0]["input"] == "UNRELATED_MARKER"


def test_cors_preflight_is_origin_restricted(client):
    allowed = client.options(
        "/api/v1/products",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    denied = client.options(
        "/api/v1/products",
        headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "GET"},
    )
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_readiness_requires_migration(caplog):
    with TemporaryDirectory() as folder:
        engine = create_engine(f"sqlite:///{Path(folder) / 'unmigrated.db'}")

        def empty_db():
            with Session(engine) as db:
                yield db

        app.dependency_overrides[get_db] = empty_db
        try:
            with TestClient(app) as isolated:
                assert isolated.get("/health/live").status_code == 200
                response = isolated.get("/health/ready")
                assert response.status_code == 503
                assert response.json()["detail"] == "Database migration required"
                failed_catalog = isolated.get("/api/v1/brands?q=private-query")
                assert failed_catalog.status_code == 503
                assert "private-query" not in caplog.text
        finally:
            app.dependency_overrides.clear()
            engine.dispose()


def test_sql_parameters_are_hidden():
    assert get_engine().hide_parameters


def test_unconfigured_sms_fails_safely(client, sms):
    unconfigured = Settings(sms_provider="unconfigured")
    app.dependency_overrides[get_settings] = lambda: unconfigured
    try:
        result = client.post("/api/v1/auth/challenges", json={"mobile": "09120000012"})
        assert result.status_code == 503
        assert sms.messages == []
    finally:
        app.dependency_overrides.clear()


def test_uncertain_sms_delivery_reserves_challenge_and_blocks_retry(sms, caplog):
    mobile = "09128881234"

    class FailingSMS:
        attempted_code: str | None = None

        def send_otp(self, recipient: str, code: str) -> None:
            self.attempted_code = code
            raise RuntimeError(
                f"carrier private failure recipient={recipient} otp={code} "
                "credential=SMS_API_SECRET_SENTINEL"
            )

    failing_sms = FailingSMS()
    had_previous_override = get_sms_provider in app.dependency_overrides
    previous_override = app.dependency_overrides.get(get_sms_provider)

    app.dependency_overrides[get_sms_provider] = lambda: failing_sms
    try:
        with TestClient(app, client=("192.0.2.45", 50002)) as isolated:
            failed = isolated.post("/api/v1/auth/challenges", json={"mobile": mobile})
            assert failed.status_code == 503
            assert failed.json() == {"detail": "SMS delivery unavailable"}
            assert failing_sms.attempted_code is not None
            assert failing_sms.attempted_code not in failed.text
            assert mobile not in failed.text
            assert "carrier private failure" not in failed.text
            assert "SMS_API_SECRET_SENTINEL" not in failed.text
            assert failing_sms.attempted_code not in caplog.text
            assert mobile not in caplog.text
            assert normalize_mobile(mobile) not in caplog.text
            assert "SMS_API_SECRET_SENTINEL" not in caplog.text

            mobile_key = digest(normalize_mobile(mobile), get_settings().otp_pepper)
            with Session(get_engine()) as db:
                challenge = db.scalar(
                    select(AuthChallenge).where(AuthChallenge.mobile_digest == mobile_key)
                )
                assert challenge is not None
                assert challenge.delivery_status == "pending"
                assert aware(challenge.expires_at) > utcnow()
            again = isolated.post("/api/v1/auth/challenges", json={"mobile": mobile})
            assert again.status_code == 429
            assert len(sms.messages) == 0
    finally:
        if had_previous_override:
            app.dependency_overrides[get_sms_provider] = previous_override
        else:
            app.dependency_overrides.pop(get_sms_provider, None)

    with TestClient(app, client=("192.0.2.45", 50002)) as recovered:
        assert (
            recovered.post(
                "/api/v1/auth/verify", json={"mobile": mobile, "code": failing_sms.attempted_code}
            ).status_code
            == 200
        )


def test_reservation_commit_failure_prevents_sms(sms):
    mobile = "09128881235"

    class FailingCommitSession(Session):
        def commit(self) -> None:
            raise SQLAlchemyError("simulated commit failure")

    def failing_db():
        with FailingCommitSession(get_engine()) as db:
            yield db

    app.dependency_overrides[get_db] = failing_db
    try:
        with TestClient(app, client=("192.0.2.46", 50003)) as isolated:
            result = isolated.post("/api/v1/auth/challenges", json={"mobile": mobile})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert result.status_code == 503
    assert result.json() == {"detail": "Database unavailable"}
    assert len(sms.messages) == 0
    assert mobile not in result.text
    with Session(get_engine()) as db:
        assert (
            db.scalar(
                select(AuthChallenge).where(
                    AuthChallenge.mobile_digest
                    == digest(normalize_mobile(mobile), get_settings().otp_pepper)
                )
            )
            is None
        )


def test_accepted_send_survives_failed_finalization_commit(sms):
    mobile = "09128881241"

    class FailingSecondCommitSession(Session):
        commits = 0

        def commit(self) -> None:
            self.commits += 1
            if self.commits == 2:
                raise SQLAlchemyError("simulated finalization failure")
            super().commit()

    def failing_db():
        with FailingSecondCommitSession(get_engine()) as db:
            yield db

    app.dependency_overrides[get_db] = failing_db
    try:
        with TestClient(app, client=("192.0.2.47", 50004)) as isolated:
            result = isolated.post("/api/v1/auth/challenges", json={"mobile": mobile})
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert result.status_code == 503
    assert len(sms.messages) == 1
    with Session(get_engine()) as db:
        challenge = db.scalar(
            select(AuthChallenge).where(
                AuthChallenge.mobile_digest
                == digest(normalize_mobile(mobile), get_settings().otp_pepper)
            )
        )
        assert challenge.delivery_status == "pending"
    with TestClient(app, client=("192.0.2.47", 50004)) as isolated:
        assert (
            isolated.post(
                "/api/v1/auth/verify", json={"mobile": mobile, "code": sms.messages[-1][1]}
            ).status_code
            == 200
        )


def test_otp_expiry_replay_and_attempt_limit(client, sms):
    mobile = "09120000001"
    client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    code = sms.messages[-1][1]
    with Session(get_engine()) as db:
        challenge = db.scalar(
            select(AuthChallenge).where(
                AuthChallenge.mobile_digest
                == digest(normalize_mobile(mobile), get_settings().otp_pepper)
            )
        )
        challenge.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert (
        client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": code}).status_code == 400
    )

    mobile = "09120000002"
    client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    code = sms.messages[-1][1]
    for attempt in range(5):
        result = client.post(
            "/api/v1/auth/verify",
            json={"mobile": mobile, "code": "999999" if code != "999999" else "888888"},
        )
        assert result.status_code == (429 if attempt == 4 else 400)
    assert (
        client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": code}).status_code == 400
    )
    mobile = "09120000003"
    client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    code = sms.messages[-1][1]
    assert (
        client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": code}).status_code == 200
    )
    assert (
        client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": code}).status_code == 400
    )


def test_otp_resend_invalidates_old_code_and_hides_secrets(client, sms):
    mobile = "09120000013"
    first = client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    assert first.status_code == 202
    assert first.headers["Cache-Control"] == "no-store"
    first_code = sms.messages[-1][1]
    assert first_code not in first.text
    with Session(get_engine()) as db:
        challenge = db.scalar(
            select(AuthChallenge).where(
                AuthChallenge.mobile_digest
                == digest(normalize_mobile(mobile), get_settings().otp_pepper)
            )
        )
        assert challenge.code_digest != first_code
        assert challenge.mobile_digest != "+989120000013"
        challenge.created_at = utcnow() - timedelta(seconds=61)
        db.commit()
    second = client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    assert second.status_code == 202
    second_code = sms.messages[-1][1]
    assert second_code not in second.text
    assert (
        client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": first_code}).status_code
        == 400
    )
    assert (
        client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": second_code}).status_code
        == 200
    )


def test_challenge_response_does_not_enumerate_accounts(client, sms):
    with Session(get_engine()) as db:
        db.add(User(mobile_e164="+989120000014"))
        db.commit()
    known = client.post("/api/v1/auth/challenges", json={"mobile": "09120000014"})
    unknown = client.post("/api/v1/auth/challenges", json={"mobile": "09120000015"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()


def test_request_limit_session_logout(client, sms):
    mobile = "09120000004"
    assert client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
    assert client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 429
    csrf = login(client, sms, "09120000005")
    assert client.cookies.get("aroman_session")
    assert client.get("/api/v1/auth/session").status_code == 200
    assert client.get("/api/v1/users/me").json()["mobile_e164"] == "+989120000005"
    csrf_response = client.get("/api/v1/auth/csrf")
    assert csrf_response.headers["Cache-Control"] == "no-store"
    fresh_csrf = csrf_response.json()["csrf_token"]
    assert fresh_csrf != csrf
    assert client.delete("/api/v1/auth/session").status_code == 403
    assert client.delete("/api/v1/auth/session", headers={"X-CSRF-Token": csrf}).status_code == 403
    assert (
        client.delete("/api/v1/auth/session", headers={"X-CSRF-Token": fresh_csrf}).status_code
        == 204
    )
    assert client.get("/api/v1/auth/session").status_code == 401


def test_cookie_scope_and_attributes(client, sms):
    mobile = "09120000016"
    client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    result = client.post(
        "/api/v1/auth/verify", json={"mobile": mobile, "code": sms.messages[-1][1]}
    )
    cookie = result.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/api/v1" in cookie
    assert "secure" not in cookie  # TestClient uses plain HTTP; real environments require Secure.


def test_secure_cookie_configuration(client, sms):
    app.dependency_overrides[get_settings] = lambda: Settings(cookie_secure=True)
    try:
        mobile = "09120000018"
        assert client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
        response = client.post(
            "/api/v1/auth/verify",
            json={"mobile": mobile, "code": sms.messages[-1][1]},
        )
        assert response.status_code == 200
        assert "secure" in response.headers["set-cookie"].lower()
    finally:
        app.dependency_overrides.clear()


def test_verify_rate_limit_and_origin(client, sms):
    assert (
        client.post(
            "/api/v1/auth/challenges",
            json={"mobile": "09120000009"},
            headers={"Origin": "https://unexpected.example"},
        ).status_code
        == 403
    )
    mobile = "09120000010"
    for _ in range(10):
        result = client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": "000000"})
        assert result.status_code == 400
    assert (
        client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": "000000"}).status_code
        == 429
    )


def test_request_peer_limit(sms):
    with TestClient(app, client=("isolated-request-peer", 50000)) as other:
        for suffix in range(20):
            mobile = f"0912777{suffix:04d}"
            assert other.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
        assert (
            other.post("/api/v1/auth/challenges", json={"mobile": "09127779999"}).status_code == 429
        )


def test_request_mobile_hourly_limit(sms):
    mobile = "09120000017"
    mobile_key = digest(normalize_mobile(mobile), get_settings().otp_pepper)
    with TestClient(app, client=("isolated-mobile-peer", 50001)) as other:
        for _ in range(5):
            assert other.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
            with Session(get_engine()) as db:
                newest = db.scalar(
                    select(AuthChallenge)
                    .where(AuthChallenge.mobile_digest == mobile_key)
                    .order_by(AuthChallenge.created_at.desc(), AuthChallenge.id.desc())
                )
                newest.created_at = utcnow() - timedelta(seconds=61)
                db.commit()
        assert other.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 429


def test_catalog_and_concepts(client, sms):
    brands = client.get("/api/v1/brands?q=آرومان").json()
    assert len(brands) == 1 and brands[0]["is_demo"]
    products = client.get("/api/v1/products", params={"brand_id": brands[0]["id"]}).json()
    assert len(products) == 1
    assert client.get(f"/api/v1/products/{products[0]['id']}/variants").json()[0]["is_demo"]
    notes = client.get("/api/v1/fragrance-notes").json()
    assert len(notes) == 24
    assert client.get("/api/v1/fragrance-notes", params={"limit": 2}).json() == notes[:2]
    assert (
        client.get("/api/v1/fragrance-notes", params={"limit": 2, "offset": 2}).json() == notes[2:4]
    )
    assert client.get("/api/v1/fragrance-notes", params={"limit": 101}).status_code == 422
    assert (
        len(
            client.get(
                "/api/v1/fragrance-notes", params={"family_id": notes[0]["family_id"]}
            ).json()
        )
        > 0
    )
    csrf = login(client, sms, "09120000006")
    headers = {"X-CSRF-Token": csrf}
    payload = {"name": "باغ", "notes": [{"note_id": notes[0]["id"], "layer": "top", "position": 0}]}
    assert client.post("/api/v1/fragrance-concepts", json=payload).status_code == 403
    created = client.post("/api/v1/fragrance-concepts", json=payload, headers=headers)
    assert created.status_code == 201, created.text
    id = created.json()["id"]
    assert len(client.get("/api/v1/fragrance-concepts").json()) == 1
    assert len(client.get("/api/v1/fragrance-concepts", params={"limit": 1}).json()) == 1
    payload["name"] = "باغ نو"
    assert (
        client.put(f"/api/v1/fragrance-concepts/{id}", json=payload, headers=headers).json()["name"]
        == "باغ نو"
    )
    duplicate = client.post(f"/api/v1/fragrance-concepts/{id}/duplicate", headers=headers)
    assert duplicate.status_code == 201
    duplicate_id = duplicate.json()["id"]
    assert (
        client.delete(f"/api/v1/fragrance-concepts/{duplicate_id}", headers=headers).status_code
        == 204
    )
    assert client.get(f"/api/v1/fragrance-concepts/{duplicate_id}").status_code == 404
    bad_layer = {
        "name": "bad",
        "notes": [{"note_id": notes[0]["id"], "layer": "middle", "position": 0}],
    }
    assert (
        client.post("/api/v1/fragrance-concepts", json=bad_layer, headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/fragrance-concepts",
            json={
                "name": "زیاد",
                "notes": [
                    {"note_id": n["id"], "layer": "top", "position": i}
                    for i, n in enumerate(notes[:7])
                ],
            },
            headers=headers,
        ).status_code
        == 422
    )
    seven_notes = {
        "name": "seven",
        "notes": [
            {"note_id": n["id"], "layer": "top", "position": i} for i, n in enumerate(notes[:7])
        ],
    }
    assert (
        client.put(
            f"/api/v1/fragrance-concepts/{id}", json=seven_notes, headers=headers
        ).status_code
        == 422
    )
    assert client.get(f"/api/v1/fragrance-concepts/{id}").json()["name"] == "باغ نو"
    assert (
        client.post(
            "/api/v1/fragrance-concepts",
            json={
                "name": "unknown",
                "notes": [
                    {
                        "note_id": "00000000-0000-0000-0000-000000000001",
                        "layer": "top",
                        "position": 0,
                    }
                ],
            },
            headers=headers,
        ).status_code
        == 422
    )
    other_csrf = login(client, sms, "09120000007")
    assert client.get("/api/v1/fragrance-concepts").json() == []
    assert client.get(f"/api/v1/fragrance-concepts/{id}").status_code == 404
    assert (
        client.post(
            f"/api/v1/fragrance-concepts/{id}/duplicate",
            headers={"X-CSRF-Token": other_csrf},
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/v1/fragrance-concepts/{id}", json=payload, headers={"X-CSRF-Token": other_csrf}
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/fragrance-concepts/{id}", headers={"X-CSRF-Token": other_csrf}
        ).status_code
        == 404
    )
    client.cookies.clear()


def test_session_expiry(client, sms):
    login(client, sms, "09120000008")
    with Session(get_engine()) as db:
        token = client.cookies.get("aroman_session")
        session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_digest == digest(token, get_settings().session_pepper)
            )
        )
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/auth/session").status_code == 401


def test_seed_is_idempotent():
    with Session(get_engine()) as db:
        counts_before = [
            db.scalar(select(func.count()).select_from(model))
            for model in (Brand, FragranceNote, Product)
        ]
        seed(db)
        counts_after = [
            db.scalar(select(func.count()).select_from(model))
            for model in (Brand, FragranceNote, Product)
        ]
    assert counts_before == counts_after == [3, 24, 3]
