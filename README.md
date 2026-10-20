# AROMAN Backend — M1-A foundation

FastAPI modular monolith for a Persian-first fragrance catalog and private fragrance concepts. Python 3.12+, PostgreSQL, SQLAlchemy 2, Alembic. `/docs` and `/openapi.json` expose the versioned REST contract.

## Local setup

1. `cp .env.example .env` and replace every placeholder with independent random values. Example: `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`. Keep `.env` private.
2. Set `COOKIE_SECURE=false` only for plain HTTP on localhost. Set `SMS_PROVIDER=fake` and `FAKE_SMS_ENABLED=true` only for isolated local development. Fake messages are held in the API process memory and never returned over HTTP. There is no fixed code. For normal use leave SMS unconfigured; auth requests then return 503.
3. `docker compose up -d db`
4. `docker compose --profile tools run --build --rm migrate`
5. `docker compose up -d --build api`
6. `docker compose --profile tools run --rm migrate aroman-seed`
7. Open `http://localhost:8000/docs` and check `/health/live` and `/health/ready`.

The database has no host port binding. Compose uses separate migrator and limited application roles. The initialization script runs only on a fresh volume; the migration service then applies table grants. The application role can read catalog tables but cannot change them. Run demonstration seeding through the migration role. Production should provision equivalent roles and use an external managed PostgreSQL service. Deploy the API behind a trusted HTTPS proxy. Configure `TRUSTED_PROXY_CIDRS` with only its network ranges so per-client rate limits use the first untrusted forwarded address. Block direct access to the API from outside that proxy. Do not publish port 8000 or enable fake SMS on a reachable staging deployment. A real SMS adapter has not been selected or built.

For host based development with an existing PostgreSQL: `python3 -m venv .venv`, `.venv/bin/pip install -e '.[dev]'`, set `DATABASE_URL`, then `.venv/bin/alembic upgrade head`, provision role grants for that environment, `.venv/bin/aroman-seed` using an operator database role, `.venv/bin/uvicorn aroman.main:app --reload --no-access-log --no-proxy-headers`. Run `.venv/bin/pytest -q`, `.venv/bin/ruff check aroman tests alembic`, and `.venv/bin/mypy aroman`.


The frontend contract is in [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) and [`docs/FRONTEND_INTEGRATION.md`](docs/FRONTEND_INTEGRATION.md). Export the current OpenAPI JSON with `docker compose exec -T api python -m aroman.openapi_export > docs/openapi.json`.

## API examples

`GET /api/v1/brands?q=آرومان`, `GET /api/v1/products?brand_id=<uuid>`, `GET /api/v1/products/<uuid>/variants`, `GET /api/v1/fragrance-families`, `GET /api/v1/fragrance-notes?family_id=<uuid>&q=رز`.

`POST /api/v1/auth/challenges` with `{"mobile":"<Iranian mobile>"}`. The response never includes a code. `POST /api/v1/auth/verify` with `{"mobile":"<same mobile>","code":"<received code>"}` sets an HttpOnly session cookie and returns a CSRF token. Send `X-CSRF-Token` for `POST`, `PUT`, and `DELETE` concept or logout requests. `GET /api/v1/auth/session` checks a session; `GET /api/v1/auth/csrf` issues a fresh CSRF token after a page reload; `DELETE /api/v1/auth/session` revokes it. Frontends must enable credentials and use an origin listed in `CORS_ORIGINS`.

`POST /api/v1/fragrance-concepts` with `{"name":"باغ من","notes":[{"note_id":"<uuid>","layer":"top","position":0}]}`. `GET`, `PUT`, `DELETE` on `/api/v1/fragrance-concepts/<uuid>`; `POST /api/v1/fragrance-concepts/<uuid>/duplicate`. The six note cap is a configurable UX rule only. Concepts are not safe, validated, or manufacturable formulas.

Seed data contains six conceptual families, 24 conceptual notes, three fictional/demo brands and products, and no prices, inventory, reviews, longevity metrics, or manufacturer claims. The seed command is idempotent by slug.

## Migration and legacy notes

The original Go scaffold is kept in Git history and its files under `services/` and `shared/` remain for reference. The old product table and new products table have incompatible IDs and fields; this migration is for a fresh database. Backfill and cutover require a separately reviewed data mapping and backups. Old Compose volumes should not be attached to the new stack. The old tracked config included a default database password and publicly bound services; rotate credentials if they were ever deployed. The old Go service configuration is not used by this app.
