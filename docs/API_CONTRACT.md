# AROMAN M1-A API contract

This contract describes the implemented FastAPI endpoints. The local base URL is `http://localhost:8000`; all business routes start with `/api/v1`. The live schema is at `/openapi.json` and interactive docs are at `/docs`. The API serves JSON. UUIDs are lowercase strings. Persian text is UTF-8.

Export the exact OpenAPI document from a running local API container:

```bash
docker compose exec -T api python -m aroman.openapi_export > docs/openapi.json
python3 -m json.tool docs/openapi.json > /dev/null
```

The export command reads the container's configuration and does not connect to PostgreSQL. The generated file is an export artifact; rerun it when routes or schemas change.

## Authentication

| Method and path | Request | Success | Common failures |
|---|---|---|---|
| `POST /api/v1/auth/challenges` | `{"mobile":"<Iranian mobile>"}` | `202 {"message":"If delivery is available, a code has been sent"}` | 403 disallowed Origin, 422 invalid mobile, 429 limit, 503 SMS unavailable |
| `POST /api/v1/auth/verify` | `{"mobile":"<same mobile>","code":"<six received digits>"}` | `200 {"user_id":"<uuid>","csrf_token":"<opaque token>"}` and session cookie | 400 invalid or expired, 403 disallowed Origin or unavailable account, 429 limit |
| `GET /api/v1/auth/session` | Session cookie | `200 {"user_id":"<uuid>","role":"customer"}` | 401 |
| `GET /api/v1/auth/csrf` | Session cookie | `200 {"csrf_token":"<new opaque token>"}` | 401, 403 disallowed Origin |
| `DELETE /api/v1/auth/session` | Session cookie and `X-CSRF-Token` | 204 | 401, 403 |
| `GET /api/v1/users/me` | Session cookie | `200 {"id":"<uuid>","mobile_e164":"<canonical mobile>","role":"customer"}` | 401 |

Mobile input accepts Iranian `09…`, `+989…`, `989…`, and `00989…` forms using Persian, Arabic, or English numerals. The server stores canonical `+989…` values. An SMS provider is not integrated. The unconfigured provider returns 503; the isolated fake provider is explicit test/development tooling and never returns a code over HTTP. Do not treat an accepted challenge as proof of delivery.

The `aroman_session` cookie is HttpOnly, host scoped, path `/api/v1`, SameSite `Lax` by default, and Secure by default. Plain HTTP localhost development may set `COOKIE_SECURE=false`. For a cross-site HTTPS frontend, configure `COOKIE_SAMESITE=none`, keep `COOKIE_SECURE=true`, and list the exact frontend origin in `CORS_ORIGINS`. Session lifetime defaults to seven days without sliding renewal. Authentication, user, and private concept responses send `Cache-Control: no-store`. `DELETE /auth/session` revokes the server record and clears the cookie.

Send `X-CSRF-Token` on every authenticated `POST`, `PUT`, and `DELETE`. Store the token in application memory. After a reload, call `GET /auth/csrf`; it rotates the token and invalidates the previous value. Browser requests must use credentials and a configured Origin.

Relevant HTTP 403 responses retain a string `detail` and add a stable top-level `code`:

```json
{"detail":"CSRF token required","code":"csrf_invalid"}
```

| Code | When returned | Existing detail |
|---|---|---|
| `csrf_invalid` | Missing, expired after rotation, or mismatched `X-CSRF-Token` on an authenticated write | `CSRF token required` |
| `origin_denied` | Request Origin is not permitted on an Origin-checked authentication request or authenticated write | `Origin denied` |
| `account_unavailable` | Existing account is inactive during OTP verification | `Account unavailable` |

An expired or invalid session returns 401 instead of `csrf_invalid`. Other error response shapes are unchanged.

## Public catalog

All list endpoints return JSON arrays, ordered consistently, with `limit` (default 50, range 1–100) and `offset` (default 0, nonnegative). An empty array means there are no more results. No total count or cursor is provided. `q` is a case-insensitive substring of the displayed name and is limited to 100 characters. IDs used as filters must be UUIDs.

| Method and path | Query parameters | Response items |
|---|---|---|
| `GET /api/v1/brands` | `q`, `limit`, `offset` | `id`, `slug`, `name`, `description`, `is_demo` |
| `GET /api/v1/products` | `q`, `brand_id`, `family_id`, `limit`, `offset` | Same common fields plus `brand_id`, `family_id` |
| `GET /api/v1/products/{product_id}/variants` | None | `id`, `product_id`, `sku`, `label`, `volume_ml`, `is_demo` |
| `GET /api/v1/fragrance-families` | `q`, `limit`, `offset` | Common fields |
| `GET /api/v1/fragrance-notes` | `q`, `family_id`, `limit`, `offset` | Common fields plus `family_id` |

`description`, `family_id`, and `volume_ml` can be `null`. Variants return an unpaginated array, empty when the product ID has no variants or does not exist. Demo records have `is_demo: true`. They do not represent verified inventory, reviews, longevity metrics, or manufacturer claims.

Example product response shape:

```json
[{"id":"<uuid>","slug":"aroman-garden-demo","name":"باغ آرومان — نمونه","description":"محصول نمایشی؛ موجودی و ادعای عملکرد ندارد.","is_demo":true,"brand_id":"<uuid>","family_id":"<uuid>"}]
```

## Private fragrance concepts

`GET /api/v1/fragrance-concepts` uses `limit` and `offset` with the same bounds. It returns the signed-in user's concepts, newest first. Every route below requires a session; mutating routes also require `X-CSRF-Token`. Other users' concept IDs return 404.

| Method and path | Request | Success |
|---|---|---|
| `POST /api/v1/fragrance-concepts` | Concept payload | 201 concept |
| `GET /api/v1/fragrance-concepts` | None | 200 array of concepts |
| `GET /api/v1/fragrance-concepts/{id}` | None | 200 concept |
| `PUT /api/v1/fragrance-concepts/{id}` | Complete replacement payload | 200 concept |
| `POST /api/v1/fragrance-concepts/{id}/duplicate` | None | 201 new concept |
| `DELETE /api/v1/fragrance-concepts/{id}` | None | 204 |

Create and update payload:

```json
{"name":"باغ من","notes":[{"note_id":"<uuid from /fragrance-notes>","layer":"top","position":0},{"note_id":"<another uuid>","layer":"heart","position":0}]}
```

Responses contain `id`, `name`, and `notes` with `note_id`, `layer`, `position`. Names must contain a non-whitespace character; valid names are saved exactly as supplied. Valid layers are `top`, `heart`, `base`; positions must start at zero and be contiguous within each layer, independently of other layers. A note can occur once per concept. Invalid create and update payloads return HTTP 422. `PUT` replaces the complete name and note selection. The default maximum is six selected notes, configurable by `MAX_CONCEPT_NOTES`. Concurrent PostgreSQL writes are serialized by a row lock; if two valid full replacements are submitted, the later committed update becomes the saved state. There is no revision token in M1-A, so clients should avoid editing the same concept in multiple tabs. This is a user experience rule, not a chemical safety limit. No concept is asserted to be safe, validated, or manufacturable.

## Errors and health

Common errors use `{"detail":"message"}`; the coded 403 errors documented above also include `code`. Pydantic validation returns HTTP 422 with `{"detail":[{"type":"...","loc":["body","field"],"msg":"...","input":"..."}]}`; field locations and messages depend on the invalid input. Domain validation may return 422 with a string `detail`. Use `code` for these 403 cases; do not parse error English as a stable machine code. Handle HTTP status and show a safe generic message when needed.

- 400: invalid or expired OTP.
- 401: no valid session.
- 403: invalid CSRF token, disallowed Origin, or unavailable account during OTP verification.
- 404: concept absent or owned by another user.
- 422: invalid input, unknown note, or note limit.
- 429: OTP rate or attempt limit.
- 503: SMS unavailable or database not ready.

`GET /health/live` returns 200 when the process is alive. `GET /health/ready` returns 200 only when PostgreSQL is accessible and at the current Alembic revision; otherwise it returns 503. These are outside `/api/v1` so infrastructure probes stay stable across API versions.
