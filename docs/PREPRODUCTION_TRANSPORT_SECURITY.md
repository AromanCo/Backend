# Preproduction transport and secrets security

## Required topology

Browser → HTTPS reverse proxy → private FastAPI listener → private PostgreSQL. The proxy terminates TLS, and the browser must never reach the API listener directly. The Dockerfile deliberately starts Uvicorn with `--no-proxy-headers`; keep this setting. Proxy supplied scheme and host must not control application security decisions. TLS certificates, public DNS, firewall rules, and network isolation need a later private-environment rehearsal.

## Origins, cookies, and CSRF

Set `CORS_ORIGINS` to a comma-separated list of the browser's exact HTTPS origins, including nondefault ports and without paths or trailing slashes. Staging and production reject HTTP, wildcards, and malformed origins. Credentialed CORS responses are sent only for configured origins. CORS is a browser restriction, not an API access control; protected endpoints also check an incoming `Origin` when present. A missing Origin can occur for nonbrowser clients and is not treated as proof of trust.

Use `COOKIE_SECURE=true` in staging and production. The session cookie is HttpOnly, scoped to `/api/v1`, and has `SameSite=lax` by default. Choose `strict` if the browser flow permits it. If the frontend and API are cross-site, set `COOKIE_SAMESITE=none` with Secure cookies and the exact HTTPS frontend origin. Every authenticated write, including logout, requires the session cookie and `X-CSRF-Token`; an Origin, when sent, must be allowed. The CSRF token is returned in the private verify and rotation responses; keep it in browser memory. Private auth and user responses use `Cache-Control: no-store`. Verify browser behavior at the real hostnames during rehearsal.

## Proxy client identity

Set `TRUSTED_PROXY_CIDRS` to the narrow IP networks of the immediate reverse proxy peers that may connect to FastAPI. An empty setting ignores all `X-Forwarded-For` input. Invalid CIDRs prevent startup. The application accepts forwarded client addresses only when its direct TCP peer is allowlisted, then walks the forwarding chain from the right to the first untrusted address. A malformed chain falls back to the direct peer for OTP rate limits. IPv4 and IPv6 are supported.

The proxy must discard incoming client supplied `X-Forwarded-For`, `X-Forwarded-Host`, and `X-Forwarded-Proto` before constructing its own forwarding metadata. It must append actual client addresses in a documented way and must deny direct public access to FastAPI. Do not allowlist broad networks containing arbitrary clients. Keep Uvicorn's automatic proxy header processing disabled. Test proxy sanitization, network access controls, and the actual hop chain in the private environment before launch.

## Secrets and OTP isolation

Inject distinct, high entropy database passwords, `OTP_PEPPER`, and `SESSION_PEPPER` through a private secret manager at runtime. Restrict read permissions to the service identity, avoid placing values in images, repository files, command lines, access logs, traces, and error reporting, and redact connection URLs and authorization headers before log export. Settings representations and validation exceptions hide secret input values; database exceptions are logged by type only. Treat any accidental exposure as a credential incident: revoke affected database credentials and sessions, rotate both peppers with an explicit session invalidation and OTP expiration plan, then verify downstream logs and backups. Database password rotation must cover application, migrator, and operator roles separately.

`SMS_PROVIDER=unconfigured` permits startup but OTP challenge delivery returns 503. `FakeSMS` requires explicit opt-in and is forbidden in staging and production. Its in-memory code list is test tooling only. Never expose it through an API, admin endpoint, log, or public preproduction instance. A real SMS provider and its credentials are outside this work.

## Verification boundary

`tests/test_transport_security.py` and existing auth tests check configuration rejection, exact CORS responses, cookie and CSRF behavior, secret redaction, forwarded address trust, malformed header fallback, no-store responses, and unconfigured SMS failure. These use synthetic values and local in-process requests. The Python CI `checks` job runs them with the normal test suite. The existing disposable PostgreSQL OTP, role-isolation, and backup/restore jobs remain separate.

No TLS listener or reverse proxy was started in this work. The tests do not verify actual certificate chains, TLS versions, proxy configuration, DNS, firewall isolation, or browser behavior across the intended public origins. Rehearse those items with disposable certificates and isolated infrastructure in a private environment. Before public launch, also provide a real SMS delivery integration, managed secret injection and rotation, monitored rate limits, production database backup and recovery procedures, and an operational incident response process.
