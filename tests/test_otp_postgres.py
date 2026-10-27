"""Run against a disposable PostgreSQL database via OTP_TEST_POSTGRES_URL."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from aroman.authentication.api import digest
from aroman.authentication.phone import normalize_mobile
from aroman.authentication.sms import get_sms_provider
from aroman.core.config import get_settings
from aroman.core.db import Base, get_db
from aroman.main import app
from aroman.models import AuthChallenge


@pytest.mark.skipif(
    not os.getenv("OTP_TEST_POSTGRES_URL") and os.getenv("OTP_POSTGRES_REQUIRED") != "1",
    reason="disposable PostgreSQL unavailable",
)
def test_independent_connections_respect_committed_pending_reservation():
    if not os.getenv("OTP_TEST_POSTGRES_URL"):
        pytest.fail("OTP_TEST_POSTGRES_URL is required for the PostgreSQL CI gate")
    url = make_url(os.environ["OTP_TEST_POSTGRES_URL"])
    assert url.get_backend_name() == "postgresql"
    assert url.database == "aroman_otp_test", "Only the disposable test database is allowed"
    engine = create_engine(url, pool_size=3, max_overflow=0)
    Base.metadata.create_all(engine)
    pids = []
    pids_lock = Lock()
    entered = Event()
    release = Event()

    def test_db():
        with Session(engine, expire_on_commit=False) as db:
            pid = db.scalar(select(text("pg_backend_pid()")))
            with pids_lock:
                pids.append(pid)
            yield db

    class BlockingSMS:
        code = None
        sends = 0

        def send_otp(self, recipient, code):
            self.code = code
            self.sends += 1
            # Keep the first connection checked out while another worker runs.
            with engine.connect() as connection:
                connection.scalar(select(text("pg_backend_pid()")))
                entered.set()
                assert release.wait(10)

    provider = BlockingSMS()
    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_sms_provider] = lambda: provider
    mobile = "09128889991"

    def request_code(peer):
        with TestClient(app, client=(peer, 50000)) as client:
            return client.post("/api/v1/auth/challenges", json={"mobile": mobile})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request_code, "192.0.2.81")
            assert entered.wait(10)
            second = pool.submit(request_code, "192.0.2.82")
            assert second.result(timeout=10).status_code == 429
            release.set()
            assert first.result(timeout=10).status_code == 202
        assert provider.sends == 1
        assert len(pids) >= 2 and pids[0] != pids[1]
        key = digest(normalize_mobile(mobile), get_settings().otp_pepper)
        with Session(engine) as db:
            rows = list(db.scalars(select(AuthChallenge).where(AuthChallenge.mobile_digest == key)))
            assert len(rows) == 1
            assert rows[0].delivery_status == "accepted"
        with TestClient(app, client=("192.0.2.83", 50000)) as client:
            assert (
                client.post(
                    "/api/v1/auth/verify",
                    json={
                        "mobile": mobile,
                        "code": provider.code,
                    },
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/api/v1/auth/verify",
                    json={
                        "mobile": mobile,
                        "code": provider.code,
                    },
                ).status_code
                == 400
            )
        second_mobile = "09128889993"
        with TestClient(app, client=("192.0.2.84", 50000)) as client:
            assert (
                client.post("/api/v1/auth/challenges", json={"mobile": second_mobile}).status_code
                == 202
            )
        second_code = provider.code

        def verify(peer):
            with TestClient(app, client=(peer, 50000)) as client:
                return client.post(
                    "/api/v1/auth/verify", json={"mobile": second_mobile, "code": second_code}
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(verify, ("192.0.2.85", "192.0.2.86")))
        assert sorted(outcomes) == [200, 400]
    finally:
        release.set()
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_sms_provider, None)
        Base.metadata.drop_all(engine)
        engine.dispose()
