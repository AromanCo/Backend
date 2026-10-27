"""Disposable PostgreSQL 17 role and migration integration gate."""

import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import ProgrammingError


def run(*args, env=None, input=None):
    return subprocess.run(args, env=env, input=input, text=True, capture_output=True, check=True)


def migration(url, *args):
    env = os.environ.copy()
    env["DATABASE_URL"] = url.render_as_string(hide_password=False)
    env["OTP_PEPPER"] = "role-gate-otp-pepper-aaaaaaaaaaaaaaaaaaaa"
    env["SESSION_PEPPER"] = "role-gate-session-pepper-bbbbbbbbbbbbbbbbb"
    return subprocess.run(
        [sys.executable, "-m", *args], env=env, text=True, capture_output=True, check=False
    )


def assert_success(result, passwords):
    output = result.stdout + result.stderr
    for password in passwords.values():
        output = output.replace(password, "[REDACTED]")
    assert result.returncode == 0, output


@pytest.fixture(scope="module")
def roles():
    if os.getenv("ROLE_POSTGRES_REQUIRED") != "1":
        pytest.skip("Run with ROLE_POSTGRES_REQUIRED=1 to require disposable PostgreSQL")
    token = uuid.uuid4().hex
    name = f"aroman_role_gate_{token}"
    label = f"aroman.role-gate={token}"
    passwords = {
        role: secrets.token_hex(24) for role in ("postgres", "operator", "migrator", "app")
    }
    container_id = None
    engines = []
    init_script = Path(__file__).resolve().parents[1] / "infrastructure/postgres/01-app-role.sh"
    docker_env = os.environ.copy()
    docker_env.update(
        POSTGRES_PASSWORD=passwords["postgres"],
        MIGRATOR_DB_PASSWORD=passwords["migrator"],
        APP_DB_PASSWORD=passwords["app"],
    )
    try:
        container_id = run(
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--label",
            label,
            "--tmpfs",
            "/var/lib/postgresql/data:rw,noexec,nosuid,size=256m",
            "--mount",
            f"type=bind,source={init_script},target=/docker-entrypoint-initdb.d/01-app-role.sh,readonly",
            "-p",
            "127.0.0.1::5432",
            "-e",
            "POSTGRES_PASSWORD",
            "-e",
            "POSTGRES_DB=aroman",
            "-e",
            "MIGRATOR_DB_PASSWORD",
            "-e",
            "APP_DB_PASSWORD",
            "postgres:17-alpine",
            env=docker_env,
        ).stdout.strip()
        assert len(container_id) == 64
        details = run("docker", "inspect", container_id).stdout
        metadata = json.loads(details)[0]
        assert metadata["Name"] == f"/{name}"
        assert metadata["Config"]["Labels"]["aroman.role-gate"] == token
        assert "/var/lib/postgresql/data" in metadata["HostConfig"]["Tmpfs"]
        assert not any(mount["Type"] == "volume" for mount in metadata["Mounts"])
        assert metadata["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostIp"] == "127.0.0.1"
        port = int(metadata["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"])

        def url(role, database="postgres"):
            return URL.create(
                "postgresql+psycopg",
                username={
                    "operator": "aroman_operator",
                    "migrator": "aroman_migrator",
                    "app": "aroman_app",
                }.get(role, role),
                password=passwords[role],
                host="127.0.0.1",
                port=port,
                database=database,
            )

        bootstrap = create_engine(url("postgres"), isolation_level="AUTOCOMMIT")
        engines.append(bootstrap)
        for _ in range(60):
            try:
                with bootstrap.connect() as conn:
                    assert int(conn.scalar(text("SHOW server_version_num"))) // 10000 == 17
                    assert conn.scalar(text("SELECT current_database()")) == "postgres"
                break
            except Exception:
                time.sleep(0.5)
        else:
            pytest.fail("Disposable PostgreSQL 17 container did not become ready")

        with bootstrap.begin() as conn:
            assert conn.scalar(
                text(
                    "SELECT datdba = 'aroman_migrator'::regrole "
                    "FROM pg_database WHERE datname='aroman'"
                )
            )
            assert (
                conn.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname='aroman_migrator'"))
                is False
            )
            assert conn.scalar(
                text(
                    "SELECT NOT EXISTS (SELECT 1 FROM aclexplode(datacl) "
                    "WHERE grantee = 0 AND privilege_type = 'CONNECT') "
                    "FROM pg_database WHERE datname = 'aroman'"
                )
            )
            assert conn.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM aclexplode(datacl) "
                    "WHERE grantee = 'aroman_app'::regrole AND privilege_type = 'CONNECT') "
                    "FROM pg_database WHERE datname = 'aroman'"
                )
            )
            for role in ("aroman_migrator", "aroman_app"):
                flags = conn.execute(
                    text(
                        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                        "FROM pg_roles WHERE rolname = :role"
                    ),
                    {"role": role},
                ).one()
                assert not any(flags), f"{role} has elevated role attributes"
        operator_sql = (
            "CREATE ROLE aroman_operator LOGIN CREATEDB CREATEROLE "
            f"PASSWORD '{passwords['operator']}';\n"
            "GRANT aroman_migrator TO aroman_operator;\n"
        )
        run(
            "docker",
            "exec",
            "-i",
            container_id,
            "psql",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            input=operator_sql,
        )

        aroman_migrator_url, aroman_app_url = url("migrator", "aroman"), url("app", "aroman")
        aroman_migrator = create_engine(aroman_migrator_url)
        aroman_app = create_engine(aroman_app_url)
        engines.extend((aroman_migrator, aroman_app))
        with aroman_migrator.connect() as conn:
            assert conn.scalar(text("SELECT current_database()")) == "aroman"
            assert conn.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM aclexplode(nspacl) "
                    "WHERE grantee = 'aroman_app'::regrole AND privilege_type = 'USAGE') "
                    "FROM pg_namespace WHERE nspname = 'public'"
                )
            )
            assert conn.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_default_acl d, aclexplode(d.defaclacl) a "
                    "WHERE d.defaclrole = 'aroman_migrator'::regrole "
                    "AND d.defaclnamespace = 'public'::regnamespace "
                    "AND d.defaclobjtype = 'r' AND a.grantee = 'aroman_app'::regrole "
                    "AND a.privilege_type = 'SELECT')"
                )
            )
        with aroman_app.connect() as conn:
            assert conn.scalar(text("SELECT current_database()")) == "aroman"
            assert conn.scalar(text("SELECT current_user")) == "aroman_app"
            assert conn.scalar(text("SELECT has_schema_privilege(current_user, 'public', 'USAGE')"))
            assert not conn.scalar(
                text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
            )
        denied_migration = migration(aroman_app_url, "alembic", "upgrade", "head")
        assert denied_migration.returncode != 0, "Application role unexpectedly applied migrations"
        assert "permission denied" in denied_migration.stderr.lower()
        assert_success(
            migration(aroman_migrator_url, "aroman.administration.check_migrator_role"), passwords
        )
        forbidden_name = f"aroman_forbidden_{token}"
        migrator_ddl = create_engine(aroman_migrator_url, isolation_level="AUTOCOMMIT")
        engines.append(migrator_ddl)
        try:
            with migrator_ddl.connect() as conn:
                with pytest.raises(ProgrammingError, match="permission denied"):
                    conn.execute(text(f'CREATE ROLE "{forbidden_name}"'))
                with pytest.raises(ProgrammingError, match="permission denied"):
                    conn.execute(text(f'CREATE DATABASE "{forbidden_name}"'))
        finally:
            with bootstrap.connect() as conn:
                assert conn.scalar(text("SELECT current_database()")) == "postgres"
                assert forbidden_name == f"aroman_forbidden_{token}"
                conn.execute(text(f'DROP DATABASE IF EXISTS "{forbidden_name}"'))
                conn.execute(text(f'DROP ROLE IF EXISTS "{forbidden_name}"'))
        with bootstrap.begin() as conn:
            conn.execute(text("ALTER ROLE aroman_migrator SUPERUSER"))
        try:
            unsafe = migration(aroman_migrator_url, "aroman.administration.check_migrator_role")
            assert unsafe.returncode != 0, "Preflight accepted a superuser migrator"
            assert "Unsafe migrator role" in unsafe.stderr
            with aroman_migrator.connect() as conn:
                assert conn.scalar(text("SELECT to_regclass('public.alembic_version')")) is None
        finally:
            with bootstrap.begin() as conn:
                conn.execute(text("ALTER ROLE aroman_migrator NOSUPERUSER"))
        assert_success(
            migration(aroman_migrator_url, "aroman.administration.check_migrator_role"), passwords
        )
        assert_success(migration(aroman_migrator_url, "alembic", "upgrade", "head"), passwords)
        with aroman_migrator.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "a4b01"
        for _ in range(2):
            assert_success(
                migration(aroman_migrator_url, "aroman.administration.grant_app_role"), passwords
            )
        operator = create_engine(url("operator"), isolation_level="AUTOCOMMIT")
        engines.append(operator)
        with operator.begin() as conn:
            assert conn.scalar(text("SELECT current_user")) == "aroman_operator"
            assert (
                conn.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))
                is False
            )
            conn.execute(text(f'CREATE DATABASE "{name}" OWNER aroman_migrator TEMPLATE template0'))

        with operator.begin() as conn:
            assert conn.scalar(text("SELECT current_database()")) == "postgres"
            assert conn.scalar(
                text(
                    "SELECT datdba = 'aroman_migrator'::regrole "
                    "FROM pg_database WHERE datname = :name"
                ),
                {"name": name},
            )
            conn.execute(text(f'REVOKE CONNECT ON DATABASE "{name}" FROM PUBLIC'))
            conn.execute(text(f'GRANT CONNECT ON DATABASE "{name}" TO aroman_app'))

        migrator_url, app_url = url("migrator", name), url("app", name)
        migrator = create_engine(migrator_url)
        app = create_engine(app_url)
        engines.extend((migrator, app))
        with migrator.begin() as conn:
            assert conn.scalar(text("SELECT current_database()")) == name
            assert conn.scalar(text("SELECT current_user")) == "aroman_migrator"
            assert (
                conn.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))
                is False
            )
            conn.execute(text("GRANT USAGE ON SCHEMA public TO aroman_app"))
        with app.connect() as conn:
            assert conn.scalar(text("SELECT current_database()")) == name
            assert conn.scalar(text("SELECT current_user")) == "aroman_app"
            assert (
                conn.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))
                is False
            )

        denied_migration = migration(app_url, "alembic", "upgrade", "head")
        assert denied_migration.returncode != 0, "Application role unexpectedly applied migrations"
        assert "permission denied" in denied_migration.stderr.lower()
        applied = migration(migrator_url, "alembic", "upgrade", "head")
        assert_success(applied, passwords)
        with migrator.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "a4b01"
            assert (
                conn.scalar(
                    text(
                        "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' "
                        "AND tableowner = 'aroman_migrator'"
                    )
                )
                == 12
            )
        for _ in range(2):
            granted = migration(migrator_url, "aroman.administration.grant_app_role")
            assert_success(granted, passwords)
        yield migrator, app, aroman_migrator, aroman_app
    finally:
        for engine in reversed(engines):
            engine.dispose()
        if container_id is not None:
            # Remove only the exact container created here, after checking its ownership.
            result = subprocess.run(
                ["docker", "inspect", container_id], text=True, capture_output=True, check=False
            )
            if result.returncode == 0:
                metadata = json.loads(result.stdout)[0]
                assert metadata["Name"] == f"/{name}"
                assert metadata["Config"]["Labels"]["aroman.role-gate"] == token
                run("docker", "rm", "-f", container_id)


def denied(engine, sql, params=None):
    with pytest.raises(ProgrammingError) as error, engine.begin() as conn:
        conn.execute(text(sql), params or {})
    assert (
        "permission denied" in str(error.value).lower()
        or "must be owner" in str(error.value).lower()
    )


def test_role_isolation_and_application_operations(roles):
    _, _, migrator, app = roles
    now = datetime.now(UTC)
    user, challenge, session, concept, note = (uuid.uuid4() for _ in range(5))
    family, brand, product, variant = (uuid.uuid4() for _ in range(4))

    with migrator.begin() as conn:
        conn.execute(
            text("INSERT INTO fragrance_families (id,slug,name) VALUES (:id,'family','Family')"),
            {"id": family},
        )
        conn.execute(
            text(
                "INSERT INTO fragrance_notes (id,slug,name,family_id) "
                "VALUES (:id,'note','Note',:family)"
            ),
            {"id": note, "family": family},
        )
        conn.execute(
            text("INSERT INTO brands (id,slug,name) VALUES (:id,'brand','Brand')"), {"id": brand}
        )
        conn.execute(
            text(
                "INSERT INTO products (id,slug,name,brand_id) "
                "VALUES (:id,'product','Product',:brand)"
            ),
            {"id": product, "brand": brand},
        )
        conn.execute(
            text(
                "INSERT INTO product_variants (id,product_id,sku,label) "
                "VALUES (:id,:product,'sku','Variant')"
            ),
            {"id": variant, "product": product},
        )

    with app.begin() as conn:
        for table in (
            "brands",
            "fragrance_families",
            "fragrance_notes",
            "products",
            "product_variants",
        ):
            assert conn.scalar(text(f"SELECT count(*) FROM {table}")) == 1
        conn.execute(
            text(
                "INSERT INTO auth_challenges "
                "(id,mobile_digest,code_digest,requester_digest,expires_at) "
                "VALUES (:id,:mobile,:code,:requester,:expires)"
            ),
            {
                "id": challenge,
                "mobile": "a" * 64,
                "code": "b" * 64,
                "requester": "c" * 64,
                "expires": now + timedelta(minutes=5),
            },
        )
        assert (
            conn.scalar(
                text("SELECT delivery_status FROM auth_challenges WHERE id=:id"), {"id": challenge}
            )
            == "pending"
        )
        conn.execute(
            text(
                "UPDATE auth_challenges SET delivery_status='accepted', "
                "attempts=1, consumed_at=:now WHERE id=:id"
            ),
            {"id": challenge, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO auth_verify_attempts (id,mobile_digest,requester_digest) "
                "VALUES (:id,:mobile,:requester)"
            ),
            {"id": uuid.uuid4(), "mobile": "a" * 64, "requester": "c" * 64},
        )
        conn.execute(
            text("INSERT INTO users (id,mobile_e164) VALUES (:id,'+989121234567')"), {"id": user}
        )
        conn.execute(
            text(
                "INSERT INTO auth_sessions "
                "(id,user_id,token_digest,csrf_digest,expires_at) "
                "VALUES (:id,:user,:token,:csrf,:expires)"
            ),
            {
                "id": session,
                "user": user,
                "token": "d" * 64,
                "csrf": "e" * 64,
                "expires": now + timedelta(days=1),
            },
        )
        conn.execute(
            text("UPDATE auth_sessions SET revoked_at=:now WHERE id=:id"),
            {"id": session, "now": now},
        )
        conn.execute(
            text("INSERT INTO fragrance_concepts (id,owner_id,name) VALUES (:id,:user,'First')"),
            {"id": concept, "user": user},
        )
        conn.execute(
            text(
                "INSERT INTO concept_notes (id,concept_id,note_id,layer,position) "
                "VALUES (:id,:concept,:note,'top',0)"
            ),
            {"id": uuid.uuid4(), "concept": concept, "note": note},
        )
        conn.execute(
            text("UPDATE fragrance_concepts SET name='Second' WHERE id=:id"), {"id": concept}
        )
        conn.execute(text("DELETE FROM concept_notes WHERE concept_id=:id"), {"id": concept})
        conn.execute(text("DELETE FROM fragrance_concepts WHERE id=:id"), {"id": concept})

    for statement in (
        "CREATE TABLE role_gate_forbidden (id int)",
        "ALTER TABLE users ADD COLUMN role_gate_forbidden int",
        "DROP TABLE brands",
        "UPDATE users SET role='admin'",
        "DELETE FROM users",
        "UPDATE auth_verify_attempts SET mobile_digest='x'",
        "DELETE FROM auth_sessions",
        "UPDATE concept_notes SET position=1",
        "INSERT INTO brands (id,slug,name) VALUES (gen_random_uuid(),'forbidden','Forbidden')",
        "UPDATE brands SET name='Forbidden'",
        "DELETE FROM brands",
        "INSERT INTO fragrance_notes (id,slug,name,family_id) "
        "SELECT gen_random_uuid(),'forbidden','Forbidden',id "
        "FROM fragrance_families LIMIT 1",
        "UPDATE products SET name='Forbidden'",
        "DELETE FROM product_variants",
    ):
        denied(app, statement)

    # PostgreSQL can issue a warning instead of an error for a GRANT by a non-owner.
    with app.begin() as conn:
        try:
            with conn.begin_nested():
                conn.execute(text("GRANT UPDATE ON brands TO aroman_app"))
        except ProgrammingError:
            pass
        assert (
            conn.scalar(text("SELECT has_table_privilege(current_user, 'brands', 'UPDATE')"))
            is False
        )
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "a4b01"


def test_additional_database_isolation(roles):
    migrator, app, _, _ = roles
    with migrator.connect() as conn:
        assert conn.scalar(text("SELECT current_database()")) != "aroman"
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "a4b01"
    with app.connect() as conn:
        assert conn.scalar(text("SELECT current_user")) == "aroman_app"
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "a4b01"
    denied(app, "CREATE TABLE role_gate_forbidden (id int)")
