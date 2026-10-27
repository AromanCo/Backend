from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from aroman.authentication.api import aware, digest
from aroman.authentication.phone import normalize_mobile
from aroman.authentication.sms import SMSDeliveryRejected, get_sms_provider
from aroman.core.config import get_settings
from aroman.core.db import get_engine, utcnow
from aroman.main import app
from aroman.models import AuthChallenge


@pytest.fixture
def isolated_client(request):
    with TestClient(app, client=(request.node.name, 50000)) as value:
        yield value


def challenges(mobile):
    key = digest(normalize_mobile(mobile), get_settings().otp_pepper)
    with Session(get_engine()) as db:
        return list(
            db.scalars(
                select(AuthChallenge)
                .where(AuthChallenge.mobile_digest == key)
                .order_by(AuthChallenge.created_at, AuthChallenge.id)
            )
        )


def pass_cooldown(mobile):
    key = digest(normalize_mobile(mobile), get_settings().otp_pepper)
    with Session(get_engine()) as db:
        newest = db.scalar(
            select(AuthChallenge)
            .where(AuthChallenge.mobile_digest == key)
            .order_by(AuthChallenge.created_at.desc(), AuthChallenge.id.desc())
        )
        newest.created_at = utcnow() - timedelta(seconds=61)
        db.commit()


def provider_override(value):
    return lambda: value


def test_rejected_replacement_preserves_previous_and_limits_overlap(isolated_client, sms):
    mobile = "09128881237"
    assert (
        isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
    )
    old_code = sms.messages[-1][1]
    pass_cooldown(mobile)

    class Rejected:
        def send_otp(self, recipient, code):
            raise SMSDeliveryRejected("synthetic refusal")

    app.dependency_overrides[get_sms_provider] = lambda: Rejected()
    try:
        failed = isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile})
    finally:
        app.dependency_overrides.pop(get_sms_provider, None)
    assert failed.status_code == 503
    assert failed.json() == {"detail": "SMS delivery unavailable"}
    rows = challenges(mobile)
    assert [row.delivery_status for row in rows] == ["accepted", "rejected"]
    assert rows[0].consumed_at is None
    assert (
        isolated_client.post(
            "/api/v1/auth/verify",
            json={
                "mobile": mobile,
                "code": old_code,
            },
        ).status_code
        == 200
    )


def test_uncertain_overlap_shares_budget_and_blocks_full_lifetime(isolated_client, sms):
    mobile = "09128881238"
    assert (
        isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
    )
    old_code = sms.messages[-1][1]
    pass_cooldown(mobile)

    class TimedOut:
        code = None
        sends = 0

        def send_otp(self, recipient, code):
            self.code = code
            self.sends += 1
            raise TimeoutError("synthetic timeout")

    provider = TimedOut()
    app.dependency_overrides[get_sms_provider] = lambda: provider
    try:
        assert (
            isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code
            == 503
        )
        pass_cooldown(mobile)
        assert (
            isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code
            == 429
        )
    finally:
        app.dependency_overrides.pop(get_sms_provider, None)
    assert provider.sends == 1
    rows = challenges(mobile)
    assert len([row for row in rows if row.consumed_at is None]) == 2
    assert rows[-1].delivery_status == "pending"
    assert aware(rows[-1].expires_at) > utcnow() + timedelta(minutes=get_settings().otp_minutes - 1)
    wrong = "999999" if "999999" not in (old_code, provider.code) else "888888"
    for attempt in range(5):
        result = isolated_client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": wrong})
        assert result.status_code == (429 if attempt == 4 else 400)
    rows = challenges(mobile)
    assert rows[0].attempts == rows[-1].attempts == 5
    for code in (old_code, provider.code):
        assert (
            isolated_client.post(
                "/api/v1/auth/verify",
                json={
                    "mobile": mobile,
                    "code": code,
                },
            ).status_code
            == 400
        )


def test_either_overlapping_code_consumes_both(isolated_client, sms):
    for suffix, use_new in (("39", False), ("40", True)):
        mobile = "091288812" + suffix
        assert (
            isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code
            == 202
        )
        old_code = sms.messages[-1][1]
        pass_cooldown(mobile)

        class Interrupted:
            code = None

            def send_otp(self, recipient, code):
                self.code = code
                raise RuntimeError("synthetic interruption")

        provider = Interrupted()
        app.dependency_overrides[get_sms_provider] = provider_override(provider)
        try:
            assert (
                isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code
                == 503
            )
        finally:
            app.dependency_overrides.pop(get_sms_provider, None)
        first = provider.code if use_new else old_code
        second = old_code if use_new else provider.code
        assert (
            isolated_client.post(
                "/api/v1/auth/verify", json={"mobile": mobile, "code": first}
            ).status_code
            == 200
        )
        assert all(row.consumed_at is not None for row in challenges(mobile))
        assert (
            isolated_client.post(
                "/api/v1/auth/verify", json={"mobile": mobile, "code": second}
            ).status_code
            == 400
        )


def test_expired_pending_reservation_allows_new_request(isolated_client, sms):
    mobile = "09128881242"

    class TimedOut:
        def send_otp(self, recipient, code):
            raise TimeoutError("synthetic timeout")

    app.dependency_overrides[get_sms_provider] = lambda: TimedOut()
    try:
        assert (
            isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code
            == 503
        )
    finally:
        app.dependency_overrides.pop(get_sms_provider, None)
    key = digest(normalize_mobile(mobile), get_settings().otp_pepper)
    with Session(get_engine()) as db:
        pending = db.scalar(select(AuthChallenge).where(AuthChallenge.mobile_digest == key))
        pending.expires_at = utcnow() - timedelta(seconds=1)
        pending.created_at = utcnow() - timedelta(minutes=get_settings().otp_minutes + 1)
        db.commit()
    assert (
        isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
    )
    assert [row.delivery_status for row in challenges(mobile)] == ["rejected", "accepted"]
    assert (
        isolated_client.post(
            "/api/v1/auth/verify",
            json={
                "mobile": mobile,
                "code": sms.messages[-1][1],
            },
        ).status_code
        == 200
    )


def test_finalization_never_reactivates_consumed_reservation(isolated_client):
    mobile = "09128881243"

    class VerifyDuringSend:
        code = None

        def send_otp(self, recipient, code):
            self.code = code
            assert (
                isolated_client.post(
                    "/api/v1/auth/verify",
                    json={
                        "mobile": mobile,
                        "code": code,
                    },
                ).status_code
                == 200
            )

    provider = VerifyDuringSend()
    app.dependency_overrides[get_sms_provider] = lambda: provider
    try:
        assert (
            isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code
            == 202
        )
    finally:
        app.dependency_overrides.pop(get_sms_provider, None)
    assert challenges(mobile)[0].consumed_at is not None
    assert (
        isolated_client.post(
            "/api/v1/auth/verify",
            json={
                "mobile": mobile,
                "code": provider.code,
            },
        ).status_code
        == 400
    )
    pass_cooldown(mobile)
    assert (
        isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 429
    )


def test_exhausted_previous_code_does_not_disable_new_delivery(isolated_client, sms):
    mobile = "09128881244"
    assert (
        isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
    )
    old_code = sms.messages[-1][1]
    wrong = "999999" if old_code != "999999" else "888888"
    for attempt in range(5):
        result = isolated_client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": wrong})
        assert result.status_code == (429 if attempt == 4 else 400)
    pass_cooldown(mobile)
    assert (
        isolated_client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
    )
    new_code = sms.messages[-1][1]
    assert (
        isolated_client.post(
            "/api/v1/auth/verify",
            json={
                "mobile": mobile,
                "code": new_code,
            },
        ).status_code
        == 200
    )
