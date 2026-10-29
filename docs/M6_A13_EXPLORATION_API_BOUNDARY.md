# M6-A13 — Exploration API Security Boundary

## Status and entry point

This milestone adds the local ASGI import target `aroman.exploration_api:app`. It is a separate FastAPI application for the exploration catalog. The existing `aroman.main:app` remains the full internal Backend application used by current development and regression tests.

**This milestone does not establish public deployment security by itself and does not authorize public launch.** The original Backend app continues exposing authentication, user, and saved-concept endpoints when accessed directly. A future approved network configuration must make the full Backend listener inaccessible to public clients and prevent bypassing the restricted entry point.

The restricted app has no docs, ReDoc, OpenAPI, health, authentication, user, concept, administration, debug, or OTP fixture routes. It imports and includes only the existing brand, catalog, and fragrance-note routers, preserving their query behavior, schemas, database access, and UUID validation.

## Exact request allowlist

Only these request method and path-template pairs are routed:

| Method | Path template |
| --- | --- |
| GET | `/api/v1/brands` |
| GET | `/api/v1/products` |
| GET | `/api/v1/products/{product_id}/variants` |
| GET | `/api/v1/fragrance-families` |
| GET | `/api/v1/fragrance-notes` |

These endpoints are read-only catalog discovery. Existing query/filter and pagination arguments remain intact. Data and imagery are demonstrative. The API does not make availability, price, purchase, manufacturing, formula, or safety claims.

Every method other than GET is rejected. HEAD and OPTIONS are intentionally rejected with the same generic denial policy as other methods (405 on an otherwise exact path). Trailing slashes are rejected. Repeated separators, encoded path characters, nested suffixes, and unknown paths do not normalize into an allowed path. The variant endpoint retains FastAPI's existing UUID parameter validation; malformed unencoded IDs receive a validation response, and encoded path separators are rejected before routing.

There is no CORS preflight support. The current Frontend client issues simple catalog GET requests with `credentials: 'include'` and no custom request headers, so it does not require preflight. For actual GET responses, the ASGI boundary returns credentialed CORS headers only when the Origin exactly matches a configured `CORS_ORIGINS` value. Wildcard origins are already rejected by Backend settings validation, and production/staging require explicit HTTPS origins. An allowed origin only permits browser JavaScript to read these catalog responses; it does not authorize authentication, expose private data, or add private routes to this app. CORS is not the request security boundary.

## Route drift and errors

At application construction, the route registry is compared with the exact method/template set above. On FastAPI versions that provide the public `fastapi.routing.iter_route_contexts()` API (0.137.2 and later), validation enumerates effective route contexts, including full paths through lazily included routers. On older versions where inclusion is flat, validation uses public `app.routes` entries. FastAPI 0.137.0 and 0.137.1 introduced lazy inclusion before that helper existed; for those versions the restricted app validates the public source-router declarations with the configured `/api/v1` prefix and snapshots the app's include registry to detect later changes. No private FastAPI route internals are used. Validation rejects missing routes, unexpected method/path pairs, duplicate registrations, and methodless or otherwise unsupported registrations such as WebSockets.

The same registry check runs at request time and denies HTTP requests if a route is attached dynamically. A raw-path/method ASGI boundary independently matches only the explicit fixed paths and the single variant path shape. WebSocket scopes are always closed, and registry drift closes them before a newly registered handler can run. Thus an unapproved route added to an included router cannot silently become reachable.

Boundary denials use a generic response and do not invoke a private handler. FastAPI debug mode is disabled, and framework documentation routes are not registered. Operational deployments must also ensure server/proxy error pages and logs do not expose sensitive request data.

## Database and data boundaries

The restricted app reuses the current catalog handlers and `get_db` access layer without changing contracts or schema. A future restricted deployment must use a dedicated least-privilege database identity with catalog-read permissions only. It must not use an administrator or migrator identity. This milestone creates no credentials, migrations, tables, or seed records.

Only public catalog response fields are returned by the approved response schemas. Requests to private endpoints cannot create/rotate auth state, create OTP challenges, trigger SMS, retrieve user profiles, or create/list/update/delete/duplicate concepts through this app. The tests use the existing disposable SQLite fixture and fake SMS provider; no real provider is contacted.

## Local-only verification

From the Backend repository root, with its existing development dependencies installed:

```sh
pytest -q tests/test_exploration_api.py
```

The tests use in-process ASGI/TestClient requests and synthetic migrated fixtures. They prove the restricted application behavior, not a firewall, reverse proxy, deployed listener, or public network boundary. No public host name or listener is specified by this milestone.

The regular Backend CI `checks` job already runs `pytest -q`, so it automatically includes this module. The PostgreSQL OTP, database-role, and backup/restore jobs are unchanged.

## Future ingress and operational acceptance

Before exposure, an approved ingress/API routing design must send public catalog traffic only to `aroman.exploration_api:app`, enforce HTTPS, and deny public access to the full `aroman.main:app` listener at the network boundary. Clients must have no route that bypasses the restricted ASGI entry point. Health checks remain internal unless separately approved. The legacy Go gateway in `services/api-gateway/` is an unused historical scaffold and is not activated or redesigned here.

Public acceptance still requires reviewed network isolation and firewall rules, TLS certificates and renewal, exact-origin CORS values, trusted-proxy behavior, dedicated catalog-read database identity, secret delivery and rotation, safe access/error logging, monitoring and incident ownership, backups and recovery objectives, migration and rollback procedures, and named operational support. Do not log credentials, OTP values, session/CSRF tokens, or unnecessary personal data. Confirm ingress methods and path normalization against the exact allowlist and test that the full listener cannot be reached from public networks.

The M6-A10 infrastructure decisions remain open: hosting/topology; public/private access and DNS; ingress and trusted proxy configuration; database service, identity, backups, and recovery; secret management; monitoring and incident ownership; deployment/migration/rollback; and support responsibilities. Review the Frontend M6-A10 decision brief and readiness matrix before infrastructure approval. Local tests, this boundary module, and the Frontend exploration mode do not authorize public launch.
