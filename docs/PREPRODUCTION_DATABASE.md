# Preproduction PostgreSQL permissions

The local verification uses PostgreSQL 17 in a disposable Docker container. Its test operator has `CREATEDB` and `CREATEROLE` for initial provisioning but is not a superuser. The `aroman_migrator` role is a non-superuser and owns the test database and application tables. The `aroman_app` role is a non-superuser with `CONNECT` and schema `USAGE`, but no schema creation rights. In local Compose, the PostgreSQL bootstrap `postgres` account is the administrator; the init script creates the separate non-superuser migrator and application roles. Keep its `OPERATOR_DB_PASSWORD` separate from both role passwords. Init scripts run only on a fresh Compose data directory; existing volumes require a separately reviewed role conversion procedure.

After Alembic reaches revision `a4b01`, the migrator runs `python -m aroman.administration.grant_app_role`. That grants the application `SELECT` on all current tables and future tables created by the migrator; `INSERT` on `users` and `auth_verify_attempts`; `INSERT, UPDATE` on `auth_challenges` and `auth_sessions`; `INSERT, UPDATE, DELETE` on `fragrance_concepts`; and `INSERT, DELETE` on `concept_notes`. Catalog tables remain read only for the application. Schema changes, catalog writes, and other table writes belong to the migrator or a separately authorized operator.

## Automated procedure

Run `ROLE_POSTGRES_REQUIRED=1 pytest -q tests/test_postgres_roles.py` with Docker available. The test creates a uniquely named PostgreSQL 17 container with synthetic passwords, a loopback port, and temporary in-memory database storage. It runs the Compose init script, creates a uniquely named test database, verifies the operator and migrator are not superusers, rejects an application-role migration, upgrades as the migrator, applies grants twice, performs authentication and concept writes as the application, and checks denied DDL and DML. The fixture checks the container's exact ID, name, and ownership label before forced removal in `finally`. The CI job `postgres-role-isolation` runs this test for pull requests to `develop`; Docker failure fails the job. Without the opt-in variable, the general test suite skips this gate and retains its existing Docker-free behavior.

The existing `otp-postgres` CI job remains a separate migration and concurrency gate. The role gate does not use an existing `DATABASE_URL`, connect to a shared database, call an SMS provider, or use a persistent Docker volume.

## Limits and remaining work

This proves the checked SQL operations and grants against a locally provisioned PostgreSQL 17 instance. It does not verify a managed production service's role provisioning, ownership, network policy, extension policy, provider configuration, or operational controls. It does not establish production readiness.

Configure `postgres-role-isolation` as a required status check in the `develop` branch protection rules before using it as a merge gate. The workflow defines and runs the job; branch protection is managed separately.

Before deployment, provision and audit equivalent roles on the intended managed service, rehearse migrations with the actual migration identity, and define a rollback or recovery plan for failed migrations. Set backup retention, recovery point and recovery time targets, and demonstrate a timed restore with application validation. A deployment runbook must also cover secrets, network access, rollout checks, monitoring, and rollback decision points.
