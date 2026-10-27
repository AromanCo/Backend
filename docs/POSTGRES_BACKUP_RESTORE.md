# Disposable PostgreSQL backup and restore rehearsal

Run from this repository with Docker and the Python development dependencies installed:

```sh
BACKUP_RESTORE_POSTGRES_REQUIRED=1 pytest -q -s tests/test_postgres_backup_restore.py
```

The required flag makes a missing or unavailable Docker daemon fail the gate. Without it, the general `pytest -q` suite skips this Docker test. The `postgres-backup-restore` CI job runs it for pull requests to `develop`. The `-s` option displays measured local backup and restore times; these are rehearsal measurements, not production RPO or RTO claims.

The test creates two uniquely named `postgres:17-alpine` containers with distinct synthetic passwords, independent fresh database clusters on Docker tmpfs, and ports bound only to `127.0.0.1`. It uses the real `01-app-role.sh` initialization, checks each cluster's identity and restricted roles, and applies Alembic revision `a4b01` as `aroman_migrator` on the source. It applies the current application grants, seeds the fictional catalog, and inserts synthetic user, concept, challenge, verification, and revoked session rows. No supplied `DATABASE_URL`, persistent volume, external service, SMS provider, or existing database is used.

`pg_dump` runs as the source migrator and writes a custom-format archive to a mode `0600` file in a private temporary directory. `pg_restore` runs as the independent recovery migrator against its already initialized, empty `aroman` database. It uses `--no-owner --no-acl --exit-on-error --single-transaction`, so source role ownership and grants are not carried into recovery. The recovery migrator owns the restored tables; its own bootstrap roles and `grant_app_role` establish application access. Passwords pass through environment variables or SQLAlchemy connections, never command arguments or test output. The archive and its deliberately invalid counterpart are removed when the temporary directory closes.

The test first attempts to restore invalid bytes and requires a nonzero exit with no created tables. For the valid archive, it compares source and recovery table, index, and constraint definitions; checks the Alembic revision and table ownership; verifies catalog counts, synthetic records, joins, authentication state, and foreign key enforcement; and checks read access, denied DDL and catalog writes, and application health/readiness. Cleanup disposes connections and removes only containers whose exact ID, name, and ownership label match the test, after checking that they use tmpfs and no Docker volume. This happens after success or failure.

## Operational limits

A restored production archive could revive unexpired sessions and OTP challenges. A real recovery procedure needs a deliberate decision about revoking sessions, invalidating outstanding challenges, and rotating or retaining digest peppers; it must prevent duplicate sends and replay while services resume. This rehearsal uses only inert synthetic digests and a revoked session.

Before a real backup system exists, operators must choose encryption in transit and at rest, key custody and rotation, retention and secure deletion, off-site storage, access controls, audit logging, and who may initiate a restore. They must set recovery point objective (RPO) and recovery time objective (RTO) targets, then measure them under realistic volume and incident conditions. The local durations here establish neither target.

The archive is verified only against the current PostgreSQL 17 schema and application revision `a4b01`. A future migration may require a different restore ordering, application build, or data conversion. The rehearsal does not test point-in-time recovery, managed service credentials and network policy, storage durability, provider snapshots, large data volume, encryption, or a production rollout. Managed production recovery requires a separate operator-approved runbook and rehearsal in that environment. This milestone creates no production backup schedule or deployment.
