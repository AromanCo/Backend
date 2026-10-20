# Next.js integration guide for M1-A

Use the implemented API described in [API_CONTRACT.md](API_CONTRACT.md) and `/openapi.json`. Set the frontend's API base URL by environment; local development typically uses `http://localhost:8000/api/v1`. Add the exact Next.js origin to backend `CORS_ORIGINS` (for example, `http://localhost:3000`). The browser origin and API hostname must be planned together: cookies set for `127.0.0.1` are not sent to `localhost`, and vice versa. Choose one hostname consistently in local development.

## Login flow

1. Collect an Iranian mobile number. Send `POST /auth/challenges` with `{ "mobile": "<user-entered mobile>" }`. Treat 202 as an accepted request, not confirmed delivery. Show a resend timer of at least 60 seconds. The backend has additional hourly limits; handle 429 without rapid retries.
2. Collect the six-digit SMS code. Send `POST /auth/verify` with the same mobile and the entered code. Use `credentials: "include"`. On 200, the browser receives an HttpOnly cookie and the JSON response contains `csrf_token` and `user_id`.
3. Keep the CSRF token in memory. Do not put the session cookie or CSRF token in a URL, analytics event, or browser local storage.
4. On page reload, call `GET /auth/session` with credentials. If it returns 200, call `GET /auth/csrf` and replace the in-memory CSRF token. The latter rotates the token, so older tabs must refresh it before their next write.
5. For logout, call `DELETE /auth/session` with credentials and `X-CSRF-Token`, then clear in-memory user and CSRF state. Treat 401 as already logged out.

Example browser request helper:

```ts
const apiBase = process.env.NEXT_PUBLIC_AROMAN_API_BASE_URL!; // ends in /api/v1

export async function apiFetch(path: string, init: RequestInit = {}) {
  return fetch(`${apiBase}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init.headers },
  });
}
```

For authenticated writes, add `X-CSRF-Token` to that helper using the token currently held in memory. Next.js server-side requests do not inherit the browser cookie automatically; forward it only for authenticated server requests and avoid exposing it to client logs. The backend owns the session; the frontend should not decode or fabricate one.

A real SMS service is not connected. With `SMS_PROVIDER=unconfigured`, the challenge request returns 503. The fake provider is local test tooling and has no public OTP retrieval endpoint. The frontend must not embed a fixed code or rely on the Coming Soon waitlist.

## Catalog and creation screens

- Fetch brands, products, families, and notes directly from `/brands`, `/products`, `/fragrance-families`, and `/fragrance-notes`. Use `q`, `brand_id`, or `family_id` filters as documented. Feed UUIDs from responses into subsequent requests.
- List endpoints return arrays, with `limit=50` and `offset=0` by default. Request the next offset until fewer than `limit` records arrive. Keep the same query filters while paging. Variants are returned at `/products/{id}/variants` as a complete array.
- Show the `is_demo` marker for every demo brand, product, variant, family, or note. The seed catalog is illustrative; there are no inventory, price, purchase, review, or manufacturer-performance endpoints in M1-A.
- Fragrance concepts are private. Before a user signs in, protected endpoints return 401. Use `POST /fragrance-concepts` to save a name and selected notes, `PUT /fragrance-concepts/{id}` to replace the full selection, and `/duplicate` to copy it. Use the `layer` values `top`, `heart`, or `base` and positions starting at zero. Enforce the six-note UX cap in the interface and still handle backend 422.
- A 404 for a concept means either that it does not exist or that it belongs to another user. Do not reveal a distinction in the UI.

## Errors and transport

Read `response.ok` and HTTP status first. FastAPI field errors use a 422 `detail` array; domain errors can use a `detail` string. Display field feedback when the array has a useful `loc`, and otherwise show a concise generic error. Handle 400 OTP errors, 401 session expiry, 403 CSRF errors, 429 cooldown or attempt limits, and 503 service unavailability. A 503 from the SMS challenge flow must not be shown as "SMS sent".

For plain HTTP localhost only, set `COOKIE_SECURE=false`. Deploy with HTTPS and `COOKIE_SECURE=true`. When frontend and API are cross-site, use `COOKIE_SAMESITE=none` together with Secure cookies and an explicit HTTPS CORS origin. A reverse proxy must prevent direct public access to the API and be listed narrowly in `TRUSTED_PROXY_CIDRS` if forwarded client IPs are used for rate limiting.

## Contract verification

After starting the backend, export the current schema with `docker compose exec -T api python -m aroman.openapi_export > docs/openapi.json`. Generate TypeScript types from that JSON with the frontend's selected OpenAPI generator. Keep generated types aligned with the live schema; this guide describes the M1-A behavior and does not define mock-only fields.
