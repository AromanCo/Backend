"""Rehearse a custom-format restore between two test-owned PostgreSQL 17 servers."""

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from aroman.core.db import Base, get_db
from aroman.main import app
from aroman.models import (  # noqa: F401 - registers all tables in Base.metadata
    AuthChallenge,
    AuthSession,
    AuthVerifyAttempt,
    Brand,
    ConceptNote,
    FragranceConcept,
    FragranceFamily,
    FragranceNote,
    Product,
    ProductVariant,
    User,
)
from aroman.seed import BRANDS, FAMILIES, NOTES, PRODUCTS, seed

ROOT = Path(__file__).resolve().parents[1]
INIT_SCRIPT = ROOT / "infrastructure/postgres/01-app-role.sh"
LABEL_KEY = "aroman.backup-restore-gate"


def command(*args: str, env: dict[str, str] | None = None, input_data=None, passwords=()):
    result = subprocess.run(args, env=env, input=input_data, capture_output=True, check=False)
    if result.returncode:
        output = (result.stdout + result.stderr).decode(errors="replace")
        for password in passwords:
            output = output.replace(password, "[REDACTED]")
        pytest.fail(f"Command {args[0]} failed ({result.returncode}): {output}")
    return result.stdout


@dataclass
class Server:
    name: str
    token: str
    passwords: dict[str, str]
    container_id: str
    port: int
    system_id: str

    def url(self, role: str) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username="aroman_migrator" if role == "migrator" else "aroman_app",
            password=self.passwords[role],
            host="127.0.0.1",
            port=self.port,
            database="aroman",
        )


def metadata(container_id: str) -> dict:
    return json.loads(command("docker", "inspect", container_id))[0]


def assert_owned(info: dict, name: str, token: str) -> None:
    assert info["Id"] and len(info["Id"]) == 64
    assert info["Name"] == f"/{name}"
    assert info["Config"]["Labels"].get(LABEL_KEY) == token
    assert "/var/lib/postgresql/data" in info["HostConfig"]["Tmpfs"]
    assert not any(mount["Type"] == "volume" for mount in info["Mounts"])
    binding = info["NetworkSettings"]["Ports"]["5432/tcp"]
    assert len(binding) == 1 and binding[0]["HostIp"] == "127.0.0.1"


def start_server(kind: str, token: str, servers: list[Server]) -> Server:
    name = f"aroman_backup_{kind}_{token}"
    passwords = {role: secrets.token_hex(24) for role in ("postgres", "migrator", "app")}
    env = os.environ.copy()
    env.update(
        POSTGRES_PASSWORD=passwords["postgres"],
        MIGRATOR_DB_PASSWORD=passwords["migrator"],
        APP_DB_PASSWORD=passwords["app"],
    )
    run_args = (
        "docker", "run", "-d", "--rm", "--name", name,
        "--label", f"{LABEL_KEY}={token}",
        "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=256m",
        "--mount", (
            f"type=bind,source={INIT_SCRIPT},"
            "target=/docker-entrypoint-initdb.d/01-app-role.sh,readonly"
        ),
        "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD", "-e", "MIGRATOR_DB_PASSWORD",
        "-e", "APP_DB_PASSWORD", "-e", "POSTGRES_DB=aroman", "postgres:17-alpine",
    )
    started = subprocess.run(run_args, env=env, capture_output=True, check=False)
    if started.returncode:
        # Docker can create a container and still report a startup error.
        leftover = subprocess.run(["docker", "inspect", name], capture_output=True, check=False)
        if leftover.returncode == 0:
            info = json.loads(leftover.stdout)[0]
            assert_owned(info, name, token)
            command("docker", "rm", "-f", info["Id"])
        output = (started.stdout + started.stderr).decode(errors="replace")
        for password in passwords.values():
            output = output.replace(password, "[REDACTED]")
        pytest.fail(f"Disposable PostgreSQL startup failed: {output}")
    container_id = started.stdout.decode().strip()
    assert len(container_id) == 64
    server = Server(name, token, passwords, container_id, 0, "")
    servers.append(server)
    info = metadata(container_id)
    assert_owned(info, name, token)
    port = int(info["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"])
    for _ in range(60):
        probe = subprocess.run(
            ["docker", "exec", container_id, "pg_isready", "-h", "127.0.0.1",
             "-U", "aroman_migrator", "-d", "aroman"],
            capture_output=True, check=False,
        )
        if probe.returncode == 0:
            break
        time.sleep(0.5)
    else:
        pytest.fail(f"Disposable {kind} PostgreSQL did not become ready")
    system_id = command(
        "docker", "exec", container_id, "psql", "-U", "postgres", "-d", "postgres",
        "-At", "-v", "ON_ERROR_STOP=1", "-c", "SELECT system_identifier FROM pg_control_system()",
    ).decode().strip()
    assert system_id.isdigit()
    server.port = port
    server.system_id = system_id
    return server


def remove_server(server: Server) -> None:
    result = subprocess.run(
        ["docker", "inspect", server.container_id], capture_output=True, check=False
    )
    if result.returncode == 0:
        info = json.loads(result.stdout)[0]
        assert info["Id"] == server.container_id
        assert_owned(info, server.name, server.token)
        command("docker", "rm", "-f", server.container_id)
        assert subprocess.run(
            ["docker", "inspect", server.container_id], capture_output=True, check=False
        ).returncode != 0


def application_command(server: Server, *module_args: str) -> None:
    env = os.environ.copy()
    env.update(
        DATABASE_URL=server.url("migrator").render_as_string(hide_password=False),
        OTP_PEPPER=secrets.token_hex(32),
        SESSION_PEPPER=secrets.token_hex(32),
    )
    result = subprocess.run(
        [sys.executable, "-m", *module_args], cwd=ROOT, env=env,
        capture_output=True, check=False,
    )
    if result.returncode:
        output = (result.stdout + result.stderr).decode(errors="replace")
        for password in server.passwords.values():
            output = output.replace(password, "[REDACTED]")
        pytest.fail(f"Migration/permission command failed: {output}")


def identity(engine: Engine, role: str) -> None:
    with engine.connect() as conn:
        assert conn.scalar(text("SHOW server_version_num"))[:2] == "17"
        assert conn.scalar(text("SELECT current_database()")) == "aroman"
        assert conn.scalar(text("SELECT current_user")) == f"aroman_{role}"
        assert conn.scalar(text(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='aroman'"
        )) == "aroman_migrator"
        assert not any(conn.execute(text(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname=current_user"
        )).one())


def schema_signature(engine: Engine) -> tuple:
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        assert tables == set(Base.metadata.tables) | {"alembic_version"}
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "a4b01"
        assert conn.scalar(text(
            "SELECT count(*) FROM pg_tables WHERE schemaname='public' "
            "AND tableowner='aroman_migrator'"
        )) == len(tables)
        indexes = tuple(conn.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' "
            "ORDER BY indexname"
        )).all())
        raw_constraints = conn.execute(text(
            "SELECT c.conname, c.contype, pg_get_constraintdef(c.oid) "
            "FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace "
            "WHERE n.nspname='public' ORDER BY c.conname"
        )).all()
        constraints = tuple(
            (
                name,
                kind,
                "" if kind == "c" else definition.replace("REFERENCES public.", "REFERENCES "),
            )
            for name, kind, definition in raw_constraints
        )
        assert indexes and constraints
        assert any(row[0] == "uq_challenge_open_pending_mobile" for row in indexes)
        assert any(row[0] == "ck_challenge_delivery_status" for row in constraints)
        assert any(row[0] == "uq_concept_note" for row in constraints)
        assert any(row[1] == "f" for row in constraints)
        return tuple(sorted(tables)), indexes, constraints


def seed_synthetic(migrator: Engine, app_engine: Engine) -> dict[str, uuid.UUID]:
    with Session(migrator) as db:
        seed(db)
    ids = {key: uuid.uuid4() for key in (
        "user", "concept", "concept_note", "challenge", "session", "verify"
    )}
    now = datetime.now(UTC)
    with app_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id,mobile_e164) VALUES (:id,:mobile)"),
                     {"id": ids["user"], "mobile": "+15550000001"})
        conn.execute(text(
            "INSERT INTO fragrance_concepts (id,owner_id,name) "
            "VALUES (:id,:owner,'Backup rehearsal')"
        ), {"id": ids["concept"], "owner": ids["user"]})
        note_id = conn.scalar(text("SELECT id FROM fragrance_notes WHERE slug='rose'"))
        conn.execute(text(
            "INSERT INTO concept_notes (id,concept_id,note_id,layer,position) "
            "VALUES (:id,:concept,:note,'top',0)"
        ), {"id": ids["concept_note"], "concept": ids["concept"], "note": note_id})
        conn.execute(text(
            "INSERT INTO auth_challenges "
            "(id,mobile_digest,code_digest,requester_digest,expires_at,delivery_status,attempts) "
            "VALUES (:id,:mobile,:code,:requester,:expires,'accepted',1)"
        ), {"id": ids["challenge"], "mobile": "a" * 64, "code": "b" * 64,
            "requester": "c" * 64, "expires": now + timedelta(minutes=5)})
        conn.execute(text(
            "INSERT INTO auth_verify_attempts (id,mobile_digest,requester_digest) "
            "VALUES (:id,:mobile,:requester)"
        ), {"id": ids["verify"], "mobile": "a" * 64, "requester": "c" * 64})
        conn.execute(text(
            "INSERT INTO auth_sessions (id,user_id,token_digest,csrf_digest,expires_at,revoked_at) "
            "VALUES (:id,:user,:token,:csrf,:expires,:revoked)"
        ), {"id": ids["session"], "user": ids["user"], "token": "d" * 64,
            "csrf": "e" * 64, "expires": now + timedelta(days=1), "revoked": now})
    return ids


def assert_data(engine: Engine, ids: dict[str, uuid.UUID]) -> None:
    expected = {
        "fragrance_families": len(FAMILIES), "fragrance_notes": len(NOTES),
        "brands": len(BRANDS), "products": len(PRODUCTS),
        "product_variants": len(PRODUCTS), "users": 1, "fragrance_concepts": 1,
        "concept_notes": 1, "auth_challenges": 1, "auth_sessions": 1,
        "auth_verify_attempts": 1,
    }
    with engine.connect() as conn:
        for table, count in expected.items():
            assert conn.scalar(text(f"SELECT count(*) FROM {table}")) == count
        assert conn.execute(text(
            "SELECT u.mobile_e164, c.name, n.slug, cn.layer FROM fragrance_concepts c "
            "JOIN users u ON u.id=c.owner_id JOIN concept_notes cn ON cn.concept_id=c.id "
            "JOIN fragrance_notes n ON n.id=cn.note_id WHERE c.id=:id"
        ), {"id": ids["concept"]}).one() == (
            "+15550000001", "Backup rehearsal", "rose", "top"
        )
        assert conn.execute(text(
            "SELECT delivery_status, attempts, consumed_at IS NULL "
            "FROM auth_challenges WHERE id=:id"
        ), {"id": ids["challenge"]}).one() == ("accepted", 1, True)
        assert conn.execute(text(
            "SELECT s.user_id, s.revoked_at IS NOT NULL FROM auth_sessions s WHERE s.id=:id"
        ), {"id": ids["session"]}).one() == (ids["user"], True)
        assert conn.scalar(text(
            "SELECT count(*) FROM auth_verify_attempts WHERE id=:id AND mobile_digest=:digest"
        ), {"id": ids["verify"], "digest": "a" * 64}) == 1
        assert conn.scalar(text(
            "SELECT count(*) FROM products p JOIN brands b ON b.id=p.brand_id "
            "JOIN fragrance_families f ON f.id=p.family_id"
        )) == len(PRODUCTS)


def assert_restricted(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        assert conn.scalar(text("SELECT current_user")) == "aroman_app"
        assert conn.scalar(text("SELECT has_schema_privilege(current_user,'public','USAGE')"))
        assert not conn.scalar(text("SELECT has_schema_privilege(current_user,'public','CREATE')"))
        for statement in (
            "CREATE TABLE backup_rehearsal_forbidden (id int)",
            "ALTER TABLE users ADD COLUMN backup_rehearsal_forbidden int",
            "UPDATE brands SET name='forbidden'",
            "DELETE FROM fragrance_notes",
            "INSERT INTO brands (id,slug,name) VALUES (gen_random_uuid(),'forbidden','Forbidden')",
            "UPDATE users SET mobile_e164='+15550000002'",
        ):
            with pytest.raises(ProgrammingError) as error, conn.begin_nested():
                conn.execute(text(statement))
            assert error.value.orig.sqlstate == "42501"
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(text(
                "INSERT INTO concept_notes (id,concept_id,note_id,layer,position) "
                "VALUES (gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),'top',0)"
            ))
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(text(
                "INSERT INTO auth_challenges "
                "(id,mobile_digest,code_digest,requester_digest,expires_at,delivery_status) "
                "VALUES (gen_random_uuid(),:mobile,:code,:requester,now(),'invalid')"
            ), {"mobile": "f" * 64, "code": "f" * 64, "requester": "f" * 64})


def assert_health(app_engine: Engine) -> None:
    def recovered_db():
        with Session(app_engine) as db:
            yield db

    previous_override = app.dependency_overrides.get(get_db)
    had_override = get_db in app.dependency_overrides
    app.dependency_overrides[get_db] = recovered_db
    try:
        with TestClient(app) as client:
            assert client.get("/health/live").json() == {"status": "ok"}
            assert client.get("/health/ready").json() == {"status": "ok"}
            products = client.get("/api/v1/products")
            assert products.status_code == 200
            assert len(products.json()) == len(PRODUCTS)
    finally:
        if had_override:
            app.dependency_overrides[get_db] = previous_override
        else:
            app.dependency_overrides.pop(get_db, None)


def test_disposable_postgres_backup_restore():
    if os.getenv("BACKUP_RESTORE_POSTGRES_REQUIRED") != "1":
        pytest.skip("Run with BACKUP_RESTORE_POSTGRES_REQUIRED=1 for the disposable Docker gate")
    token = uuid.uuid4().hex
    servers: list[Server] = []
    engines: list[Engine] = []
    with tempfile.TemporaryDirectory(prefix="aroman-backup-rehearsal-") as archive_dir:
        assert os.stat(archive_dir).st_mode & 0o077 == 0
        try:
            source = start_server("source", token, servers)
            recovery = start_server("recovery", token, servers)
            assert source.container_id != recovery.container_id
            assert source.port != recovery.port
            assert source.system_id != recovery.system_id
            assert source.passwords != recovery.passwords
            wrong_credentials = create_engine(
                recovery.url("app").set(password=source.passwords["app"]),
                hide_parameters=True,
            )
            try:
                with pytest.raises(OperationalError), wrong_credentials.connect():
                    pass
            finally:
                wrong_credentials.dispose()
            source_migrator = create_engine(source.url("migrator"), hide_parameters=True)
            source_app = create_engine(source.url("app"), hide_parameters=True)
            recovery_migrator = create_engine(recovery.url("migrator"), hide_parameters=True)
            recovery_app = create_engine(recovery.url("app"), hide_parameters=True)
            engines.extend((source_migrator, source_app, recovery_migrator, recovery_app))
            for engine, role in ((source_migrator, "migrator"), (source_app, "app"),
                                 (recovery_migrator, "migrator"), (recovery_app, "app")):
                identity(engine, role)
            with recovery_migrator.connect() as conn:
                assert inspect(conn).get_table_names() == []
            application_command(source, "aroman.administration.check_migrator_role")
            application_command(source, "alembic", "upgrade", "head")
            application_command(source, "aroman.administration.grant_app_role")
            ids = seed_synthetic(source_migrator, source_app)
            signature = schema_signature(source_migrator)
            assert_data(source_app, ids)

            archive = Path(archive_dir) / "source.dump"
            fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            started = time.perf_counter()
            with os.fdopen(fd, "wb") as output:
                result = subprocess.run(
                    ["docker", "exec", source.container_id, "pg_dump", "-U", "aroman_migrator",
                     "-d", "aroman", "-Fc", "--no-owner", "--no-acl"],
                    stdout=output, stderr=subprocess.PIPE, check=False,
                )
            assert result.returncode == 0, result.stderr.decode(errors="replace")
            backup_seconds = time.perf_counter() - started
            assert archive.stat().st_size > 0
            assert archive.stat().st_mode & 0o077 == 0

            invalid = Path(archive_dir) / "invalid.dump"
            invalid.write_bytes(b"invalid PostgreSQL custom archive\n")
            invalid.chmod(0o600)
            with invalid.open("rb") as stream:
                failed = subprocess.run(
                    ["docker", "exec", "-i", recovery.container_id, "pg_restore", "-U",
                     "aroman_migrator", "-d", "aroman", "--no-owner", "--no-acl",
                     "--exit-on-error", "--single-transaction"],
                    stdin=stream, capture_output=True, check=False,
                )
            assert failed.returncode != 0
            with recovery_migrator.connect() as conn:
                assert inspect(conn).get_table_names() == []

            started = time.perf_counter()
            with archive.open("rb") as stream:
                restored = subprocess.run(
                    ["docker", "exec", "-i", recovery.container_id, "pg_restore", "-U",
                     "aroman_migrator", "-d", "aroman", "--no-owner", "--no-acl",
                     "--exit-on-error", "--single-transaction"],
                    stdin=stream, capture_output=True, check=False,
                )
            assert restored.returncode == 0, restored.stderr.decode(errors="replace")
            recovery_seconds = time.perf_counter() - started
            application_command(recovery, "aroman.administration.check_migrator_role")
            application_command(recovery, "aroman.administration.grant_app_role")
            recovered_signature = schema_signature(recovery_migrator)
            assert recovered_signature[:2] == signature[:2]
            assert recovered_signature[2] == signature[2], (
                set(recovered_signature[2]) - set(signature[2]),
                set(signature[2]) - set(recovered_signature[2]),
            )
            assert_data(recovery_app, ids)
            assert_restricted(recovery_app)
            assert_health(recovery_app)
            print(f"Disposable backup: {backup_seconds:.3f}s; restore: {recovery_seconds:.3f}s")
        finally:
            for engine in reversed(engines):
                engine.dispose()
            for server in reversed(servers):
                remove_server(server)
