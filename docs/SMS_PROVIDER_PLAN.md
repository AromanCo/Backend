# SMS provider decision and activation plan

**Status: decision pending.** No real SMS provider or adapter is configured. The only current choices are `unconfigured` (challenge requests return HTTP 503) and an explicitly enabled, in-memory `fake` provider for development and tests. Selecting a vendor, approving an OTP template, and authorizing activation require user approval. This document makes no vendor-specific API, price, coverage, or delivery guarantee claims; verify each candidate against its current official documentation and a private sandbox before selection.

## Delivery requirements

- Send a six-digit, short-lived OTP only to a normalized supported Iranian mobile number in `+989` followed by nine digits. Existing input normalization accepts local, `98`, `0098`, and `+98` forms and Arabic/Persian numerals; preserve that validation and the public API shapes.
- Use a provider-approved verification template that communicates the code and expiry without disclosing secrets or adding unrelated content. Confirm template registration, sender identity, Iranian route availability, and any regulatory restrictions with the provider before activation.
- Keep OTP generation, HMAC storage, expiry, attempt limits, per-mobile cooldown, per-mobile and per-peer request limits, replay prevention, and invalidation of older challenges. Keep the challenge response account-neutral and free of the code.
- Require authenticated TLS transport, bounded connection/read timeouts, and a documented way to distinguish definite rejection from uncertain submission. Provider acceptance means the provider accepted a request; it is not proof that a handset received the SMS.
- Define monitoring for acceptance, rejection, timeout, uncertainty, latency, and delivery status where available, using counts and redacted correlation IDs. Do not log the OTP, full mobile, provider token, credential, request body, or unredacted provider response.

## Candidate evaluation and approval gate

Record the following for each candidate using links to **current official provider documentation**, dated sandbox results, and a commercial/compliance review. Mark any undocumented claim **requires verification**. No candidate is endorsed here.

| Criterion | Evidence needed before approval |
|---|---|
| API authentication | Credential type, scope, rotation/revocation, TLS requirements, and permitted IP restrictions. |
| OTP templates | Approved verification template, parameter rules, sender identity, language support, and route restrictions for supported `+98` mobiles. |
| Responses and failures | Exact acceptance/rejection fields, error codes, timeout behavior, status lookup or callback semantics, and whether idempotency is supported. |
| Sandbox | Test credentials and numbers, how acceptance/rejection/timeout can be simulated without live SMS, and separation from live credentials. |
| Operations | Availability evidence, rate limits, incident/support process, and status monitoring. Do not assume an SLA without contract evidence. |
| Costs | Current OTP/template/message charges, failed submission charges, minimums, taxes, and settlement terms. Obtain a quote; no price is assumed. |
| Compliance | Iranian delivery and sender requirements, data handling and retention, consent and anti-abuse duties, and applicable contractual/legal review. |

**Decision needed from the user:** approve a specific provider, verified template/sender, budget, permitted operating environment, and data/compliance terms after the evidence above is collected. Implementation and real delivery remain gated on that decision. Do not add a candidate to `SMS_PROVIDER` or inject credentials until approval.

## Configuration and secrets

Current `.env.example` documents `SMS_PROVIDER=unconfigured` and `FAKE_SMS_ENABLED=false`. Settings permit only `unconfigured` and `fake`; fake requires explicit opt-in in development/test and is rejected in staging/production. Unconfigured can start in staging/production but challenge requests fail closed with 503. No live provider variables exist yet.

After provider approval, define names and validation for a provider selector, API credential, approved template identifier, sender identifier if required, and explicit endpoint/region only if the official API requires them. Add placeholder names to `.env.example` only when the adapter is implemented. Load live values from a private secret manager or equivalent deployment secret injection, with separate sandbox/live credentials and least privilege. Never commit credentials, put them in URLs or logs, return them in HTTP responses, or place them in CI output. Specify rotation, revocation, and access ownership before activation.

## Delivery outcomes and API behavior

The current `SMSProvider.send_otp` returns `None` or raises. A future adapter needs an internally explicit outcome mapping based on verified provider semantics; the public request and response contract should remain unchanged.

| Outcome | Internal meaning and handling | Public response |
|---|---|---|
| Accepted | Provider explicitly accepted submission. This is not handset delivery proof. Persist only after the transaction design is reviewed. | Existing account-neutral 202 message if the request completes. |
| Rejected | Provider definitively refused submission. Do not mark a challenge sendable; record a redacted reason category. | Generic 503 `SMS delivery unavailable`. |
| Timeout | No conclusive response before the configured deadline. Submission may have succeeded. Mark as uncertain; never assume safe retry. | Generic 503, subject to approved transaction design. |
| Uncertain outcome | Lost connection, malformed/ambiguous response, or status disagreement. Treat as potentially delivered and investigate through safe status lookup if supported. | Generic 503, subject to approved transaction design. |
| Provider unavailable | Local configuration missing or verified provider outage. Fail closed; do not use fake as fallback. | Generic 503 `SMS delivery unavailable`. |

Never expose provider exception text, OTP, mobile, tokens, credentials, template parameters, or raw provider responses to clients. The existing database error handler returns a generic 503 `Database unavailable`. Safe internal telemetry should use redacted categories and an opaque request correlation ID. Do not claim delivery in monitoring based solely on HTTP 202.

Authentication field-validation 422 responses retain the field location, error type, and message but omit submitted input and nested error context for challenge and verify requests. The current provider-failure responses are generic and do not include that input.

## Transaction and retry risk requiring design review

Current request flow adds and flushes a challenge, calls `sms.send_otp`, invalidates older challenges, then commits. A definite provider exception triggers `db.rollback()` and generic 503; the test suite verifies that no challenge persists and a later request can retry. A timeout or other ambiguous exception follows the same rollback path even if the provider actually accepted the message. The recipient may then receive an OTP that cannot verify, while the rolled-back request consumes no persisted cooldown and a repeat request may send another SMS.

If the provider accepts the message and the later database commit fails, the provider cannot be rolled back. The recipient can receive an unusable code and the API returns a generic database 503. If a commit outcome itself is ambiguous, the application must inspect durable state before concluding whether the challenge exists. No automatic resend should follow an exception or timeout without a reviewed idempotency and reconciliation design; otherwise duplicate sends and charges are possible. An ordinary request retry can also duplicate delivery after an uncertain result.

Before real integration, review and approve transaction ordering, persistence of attempt/outcome state, idempotency keys where the provider supports them, recovery after process loss, reconciliation of uncertain outcomes, cooldown policy, and handling of an old valid challenge when a new send fails. Any refactor must preserve current authentication behavior and the pinned public API contract. This preparation does not change transaction semantics.

## Minimum verification before activation

1. **Offline tests:** use a provider test double to cover accepted, definite rejection, timeout, ambiguous response, unavailable configuration, and raised exceptions. Assert generic HTTP responses, no secret/code/mobile leakage, rollback or durable-state behavior per the approved design, no automatic duplicate send, OTP expiry/replay/attempt limits, request rate limits, and origin restrictions. Run `pytest -q`, `ruff check aroman tests alembic`, `mypy aroman`, and `git diff --check`.
2. **Private sandbox:** with non-live sandbox credentials and provider-approved test destinations, verify authentication, template parameter encoding, rejection codes, timeout behavior, and status lookup or callback claims against official documentation. Keep test artifacts redacted and isolated; do not use real customer numbers.
3. **Private deployment gate:** confirm secret injection/rotation, HTTPS and proxy configuration, PostgreSQL transaction and concurrency behavior, observability redaction, alerting, rate/cost limits, compliance approval, and a manual rollback procedure. Only then seek explicit user approval for live activation and any real SMS testing.

Existing tests cover unconfigured 503, fake-provider protection, provider exception rollback, generic provider error responses, OTP expiry/replay/limits, and origin restrictions. The focused regression test also demonstrates that a post-send database commit failure leaves a code accepted by the fake provider unusable. These tests do not demonstrate real provider readiness.
