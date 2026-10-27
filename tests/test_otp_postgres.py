"""PostgreSQL migration and concurrency checks in databases owned by this test."""

import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, Lock

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aroman.authentication.api import digest
from aroman.authentication.phone import normalize_mobile
from aroman.authentication.sms import get_sms_provider
from aroman.core.config import get_settings
from aroman.core.db import Base, get_db
from aroman.main import app
from aroman.models import AuthChallenge


@pytest.fixture(scope="module")
def postgres_url():
    raw = os.getenv("OTP_TEST_POSTGRES_URL")
    if not raw:
        if os.getenv("OTP_POSTGRES_REQUIRED") == "1":
            pytest.fail("OTP_TEST_POSTGRES_URL is required for the PostgreSQL CI gate")
        pytest.skip("disposable PostgreSQL unavailable")
    url = make_url(raw)
    assert url.get_backend_name() == "postgresql"
    assert url.drivername == "postgresql+psycopg"
    assert url.host in {"localhost", "127.0.0.1", "::1"}
    assert url.database == "aroman_otp_test"
    assert url.username == "aroman_test"
    assert not url.query, "Connection options are not allowed in the PostgreSQL test URL"
    assert os.getenv("OTP_POSTGRES_DISPOSABLE") == "1", (
        "Set OTP_POSTGRES_DISPOSABLE=1 only for a local disposable PostgreSQL service"
    )
    return url


@contextmanager
def disposable_database(url):
    """Create and remove only a uniquely named database created by this call."""
    name = f"aroman_otp_ci_{uuid.uuid4().hex}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    engine = None
    created = False
    try:
        with admin.connect() as connection:
            assert connection.scalar(text("SELECT current_database()")) == "aroman_otp_test"
            connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
            created = True
        test_url = url.set(database=name)
        engine = create_engine(test_url, pool_size=3, max_overflow=0)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT current_database()")) == name
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
                )
                == 0
            )
        yield test_url, engine
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                assert connection.scalar(text("SELECT current_database()")) == "aroman_otp_test"
                assert name.startswith("aroman_otp_ci_") and len(name) == 46
                connection.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()


def upgrade(url, revision):
    env = os.environ.copy()
    env["DATABASE_URL"] = url.render_as_string(hide_password=False)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def check_head(engine):
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "a4b01"
        inspector = inspect(connection)
        columns = {column["name"]: column for column in inspector.get_columns("auth_challenges")}
        assert columns["delivery_status"]["nullable"] is False
        assert columns["delivery_status"]["default"] == "'pending'::character varying"
        constraints = {
            item["name"]: item for item in inspector.get_check_constraints("auth_challenges")
        }
        assert "ck_challenge_delivery_status" in constraints
        indexes = {item["name"]: item for item in inspector.get_indexes("auth_challenges")}
        pending = indexes["uq_challenge_open_pending_mobile"]
        assert pending["unique"] is True
        assert pending["column_names"] == ["mobile_digest"]
        predicate = pending["dialect_options"]["postgresql_where"]
        assert "delivery_status" in predicate and "'pending'" in predicate
        assert "consumed_at IS NULL" in predicate
        drift = compare_metadata(
            MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata
        )
        assert drift == []


def test_fresh_alembic_upgrade(postgres_url):
    with disposable_database(postgres_url) as (url, engine):
        upgrade(url, "head")
        check_head(engine)
        with engine.begin() as connection:
            row_id = uuid.uuid4()
            expires = datetime.now(UTC) + timedelta(minutes=5)
            values = {
                "id": row_id,
                "mobile": "a" * 64,
                "code": "b" * 64,
                "requester": "c" * 64,
                "expires": expires,
            }
            insert = text("""INSERT INTO auth_challenges
                (id, mobile_digest, code_digest, requester_digest, expires_at)
                VALUES (:id, :mobile, :code, :requester, :expires)""")
            connection.execute(insert, values)
            assert (
                connection.scalar(
                    text("SELECT delivery_status FROM auth_challenges WHERE id = :id"),
                    {"id": row_id},
                )
                == "pending"
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text("""INSERT INTO auth_challenges
                    (id, mobile_digest, code_digest, requester_digest, expires_at, delivery_status)
                    VALUES (:id, :mobile, :code, :requester, :expires, 'invalid')"""),
                    {**values, "id": uuid.uuid4(), "mobile": "d" * 64},
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(insert, {**values, "id": uuid.uuid4()})


def test_legacy_challenge_upgrades_as_accepted(postgres_url):
    with disposable_database(postgres_url) as (url, engine):
        upgrade(url, "d9670763b00d")
        row_id = uuid.uuid4()
        with engine.begin() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == "d9670763b00d"
            )
            connection.execute(
                text("""INSERT INTO auth_challenges
                (id, mobile_digest, code_digest, requester_digest, expires_at)
                VALUES (:id, :mobile, :code, :requester, :expires)"""),
                {
                    "id": row_id,
                    "mobile": "e" * 64,
                    "code": "f" * 64,
                    "requester": "1" * 64,
                    "expires": datetime.now(UTC) + timedelta(minutes=5),
                },
            )
        upgrade(url, "head")
        check_head(engine)
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT delivery_status FROM auth_challenges WHERE id = :id"),
                    {"id": row_id},
                )
                == "accepted"
            )


def test_independent_connections_respect_committed_pending_reservation(postgres_url):
    with disposable_database(postgres_url) as (url, engine):
        upgrade(url, "head")
        check_head(engine)
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
                rows = list(
                    db.scalars(select(AuthChallenge).where(AuthChallenge.mobile_digest == key))
                )
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
                    client.post(
                        "/api/v1/auth/challenges", json={"mobile": second_mobile}
                    ).status_code
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
