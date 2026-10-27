# SMS provider decision and activation plan

**Status: Kavenegar preferred; offline only.** The user prefers Kavenegar. An isolated Lookup adapter prepares parameters and interprets simulated responses, but it is not selected by application runtime and has no live transport. The only current choices are `unconfigured` (challenge requests return HTTP 503) and an explicitly enabled, in-memory `fake` provider for development and tests. No real SMS delivery is authorized.

## Kavenegar offline adapter (M6-A6A)

The [official REST documentation](https://kavenegar.com/rest.html) describes verification Lookup with required `receptor`, `token`, and `template` parameters. The adapter takes AROMAN's normalized `+989...` mobile and maps it to the documented domestic `09...` form only for the simulated request. Its six-digit OTP maps to `token`; a template name must be supplied explicitly. An approved verification template is still required in the user's Kavenegar panel. The adapter makes one call to an injected simulation interface and never retries. It includes no HTTP client, API key, endpoint, or runtime selector.

The simulated `return.status=200` plus one valid message entry with a documented accepted message status means provider acceptance, not handset delivery. Documented, unambiguous refusal statuses such as `424` (template missing or unapproved) raise `SMSDeliveryRejected`. Generic failure (`402`), server unavailable (`409`), unknown codes, contradictory or malformed responses, timeout, and connection failure remain uncertain. The adapter emits only fixed, nonsensitive exception messages and no logs. Offline tests block socket connections.

The official URL format places the API key in the **URL path**, and Lookup places the OTP in request parameters. A future live transport must prevent full URLs, query strings, request bodies, and raw provider exceptions from appearing in logs, traces, proxies, error reports, or client responses. No credentials have been added to source, tests, CI, `.env`, or `.env.example`. Real delivery, pricing, idempotency, and sandbox behavior have not been verified. A separate, explicit activation milestone and authorization are required before **any** provider network call.

## Delivery requirements

- Send a six-digit, short-lived OTP only to a normalized supported Iranian mobile number in `+989` followed by nine digits. Existing input normalization accepts local, `98`, `0098`, and `+98` forms and Arabic/Persian numerals; preserve that validation and the public API shapes.
- Use a provider-approved verification template that communicates the code and expiry without disclosing secrets or adding unrelated content. Confirm template registration, sender identity, Iranian route availability, and any regulatory restrictions with the provider before activation.
- Keep OTP generation, HMAC storage, expiry, attempt limits, per-mobile cooldown, per-mobile and per-peer request limits, replay prevention, and invalidation of older challenges. Keep the challenge response account-neutral and free of the code.
- Require authenticated TLS transport, bounded connection/read timeouts, and a documented way to distinguish definite rejection from uncertain submission. Provider acceptance means the provider accepted a request; it is not proof that a handset received the SMS.
- Define monitoring for acceptance, rejection, timeout, uncertainty, latency, and delivery status where available, using counts and redacted correlation IDs. Do not log the OTP, full mobile, provider token, credential, request body, or unredacted provider response.

## Candidate evaluation and approval gate

Record the following using links to **current official provider documentation**, dated sandbox results, and a commercial/compliance review. Mark any undocumented claim **requires verification**. Provider preference does not imply approval to activate.

| Criterion | Evidence needed before approval |
|---|---|
| API authentication | Credential type, scope, rotation/revocation, TLS requirements, and permitted IP restrictions. |
| OTP templates | Approved verification template, parameter rules, sender identity, language support, and route restrictions for supported `+98` mobiles. |
| Responses and failures | Exact acceptance/rejection fields, error codes, timeout behavior, status lookup or callback semantics, and whether idempotency is supported. |
| Sandbox | Test credentials and numbers, how acceptance/rejection/timeout can be simulated without live SMS, and separation from live credentials. |
| Operations | Availability evidence, rate limits, incident/support process, and status monitoring. Do not assume an SLA without contract evidence. |
| Costs | Current OTP/template/message charges, failed submission charges, minimums, taxes, and settlement terms. Obtain a quote; no price is assumed. |
| Compliance | Iranian delivery and sender requirements, data handling and retention, consent and anti-abuse duties, and applicable contractual/legal review. |

**Activation decision needed from the user:** approve a verified Kavenegar template, budget, permitted operating environment, and data/compliance terms after the evidence above is collected. Real delivery remains gated on that decision. Do not add Kavenegar to `SMS_PROVIDER` or inject credentials until approval.

## Configuration and secrets

Current `.env.example` documents `SMS_PROVIDER=unconfigured` and `FAKE_SMS_ENABLED=false`. Settings permit only `unconfigured` and `fake`; fake requires explicit opt-in in development/test and is rejected in staging/production. Unconfigured can start in staging/production but challenge requests fail closed with 503. No live provider variables exist yet.

In a separate activation milestone, define names and validation for a provider selector, API credential, approved template identifier, and explicit endpoint only if required. Add configuration placeholders only when live activation is authorized. Load live values from a private secret manager or equivalent deployment secret injection, with separate sandbox/live credentials and least privilege. Kavenegar's documented URL path necessarily contains its API key; protect and redact the complete URL everywhere. Never commit credentials, return them in HTTP responses, or place them in CI output. Specify rotation, revocation, and access ownership before activation.

## Delivery outcomes and API behavior

The current `SMSProvider.send_otp` returns `None` or raises. A future adapter needs an internally explicit outcome mapping based on verified provider semantics; the public request and response contract should remain unchanged.

| Outcome | Internal meaning and handling | Public response |
|---|---|---|
| Accepted | Provider explicitly accepted submission. This is not handset delivery proof. Finalize the committed reservation as accepted. | Existing account-neutral 202 message if the request completes. |
| Rejected | Provider definitively refused submission. Mark the committed reservation rejected; preserve the previous code. | Generic 503 `SMS delivery unavailable`. |
| Timeout | No conclusive response before the configured deadline. Submission may have succeeded. Mark as uncertain; never assume safe retry. | Generic 503; keep the pending reservation and its full-lifetime cooldown. |
| Uncertain outcome | Lost connection, malformed/ambiguous response, or status disagreement. Treat as potentially delivered and investigate through safe status lookup if supported. | Generic 503; keep the pending reservation and its full-lifetime cooldown. |
| Provider unavailable | Local configuration missing or verified provider outage. Fail closed; do not use fake as fallback. | Generic 503 `SMS delivery unavailable`. |

Never expose provider exception text, OTP, mobile, tokens, credentials, template parameters, or raw provider responses to clients. The existing database error handler returns a generic 503 `Database unavailable`. Safe internal telemetry should use redacted categories and an opaque request correlation ID. Do not claim delivery in monitoring based solely on HTTP 202.

Authentication field-validation 422 responses retain the field location, error type, and message but omit submitted input and nested error context for challenge and verify requests. The current provider-failure responses are generic and do not include that input.

## Implemented transaction and verification policy

`request_code` takes PostgreSQL transaction advisory locks for the mobile and peer, checks the existing cooldown and rolling request limits, and commits a `pending` challenge containing only HMAC digests and expiry before invoking `send_otp`. A failed or ambiguous reservation commit prevents dispatch. The pending row is verifiable immediately and is a durable guard after the advisory lock is released. A partial unique index permits at most one unconsumed pending row per mobile. Requests observing an unexpired pending row receive the existing generic 429 for its full configured `otp_minutes` lifetime (five minutes by default), even after a timeout, process interruption, or failed finalization. An expired pending row is marked rejected before a new reservation. Neither a worker restart nor a subsequent request automatically resends the reserved code.

The send result is finalized in a second transaction under the mobile advisory lock. On acceptance, the row changes `pending` → `accepted` and previous open challenges are consumed in the same commit. On `SMSDeliveryRejected`, the row changes `pending` → `rejected`; the prior accepted challenge remains usable. Any other provider exception, including timeout, leaves the row pending and returns generic 503. A failed finalization commit also leaves the committed pending row and its code verifiable until expiry. Finalization checks that the row is still pending and unconsumed, so a concurrent successful verification cannot reactivate it. An accepted response means submission was accepted, not that the handset received a message.

Verification considers at most the previous accepted challenge and its pending replacement. Each invalid guess increments the same counter on both active rows; five invalid guesses exhaust both codes. A new reservation inherits the counter of a still-verifiable previous code, so overlap does not refresh that budget. An already exhausted previous code cannot disable a newly delivered replacement. A successful match consumes all open challenges for the mobile in one transaction with session creation. Existing peer and mobile hourly verification limits, origin checks, validation redaction, account-neutral responses, and cookie behavior remain in place.

External delivery and database updates are not atomic. In particular, if the application knows a send was definitively rejected but cannot commit `rejected`, the pending code remains verifiable and blocks new requests until expiry; a code cannot authenticate unless someone obtained it. There is no durable proof of whether an uncertain submission reached the provider and no safe automatic retry. A successful verification during an in-flight send can consume its reservation before delivery completes, so that delivered code will already be unusable. This tradeoff prevents replay. No provider idempotency or delivery-status reconciliation exists. Only `unconfigured` and development/test `fake` providers are selectable; the Kavenegar adapter is offline only and live SMS remains unconfigured.

M6-A4B privacy scope: OTP challenge and delivery-state records store HMAC digests, not plaintext codes or mobile numbers. This change adds no plaintext mobile field to those records and does not log OTPs, full mobiles, provider credentials, or raw provider exceptions. The pre-existing `users.mobile_e164` account identity column stores a full mobile number and is explicitly out of scope; record its privacy and security review separately. This milestone does not remediate that column.

The Alembic migration marks pre-existing challenges `accepted`, reflecting the old committed-send flow, and adds the delivery-state constraint and pending uniqueness index. Downgrade removes these fields and loses delivery-state information; it must not be treated as a risk-free production rollback. The required isolated PostgreSQL 17 CI job tests two independent connections against a disposable test database and fails if its database URL is missing. SQLite tests alone do not establish PostgreSQL concurrency behavior.

## Minimum verification before activation

1. **Offline tests:** use a provider test double to cover accepted, definite rejection, timeout, ambiguous response, unavailable configuration, and raised exceptions. Assert generic HTTP responses, no secret/code/mobile leakage, rollback or durable-state behavior per the approved design, no automatic duplicate send, OTP expiry/replay/attempt limits, request rate limits, and origin restrictions. Run `pytest -q`, `ruff check aroman tests alembic`, `mypy aroman`, and `git diff --check`.
2. **Private sandbox:** with non-live sandbox credentials and provider-approved test destinations, verify authentication, template parameter encoding, rejection codes, timeout behavior, and status lookup or callback claims against official documentation. Keep test artifacts redacted and isolated; do not use real customer numbers.
3. **Private deployment gate:** confirm secret injection/rotation, HTTPS and proxy configuration, PostgreSQL transaction and concurrency behavior, observability redaction, alerting, rate/cost limits, compliance approval, and a manual rollback procedure. Only then seek explicit user approval for live activation and any real SMS testing.

Offline tests cover commit failures, accepted and rejected delivery, uncertainty, overlap, shared attempts, expiry, replay, limits, origin restrictions, and redaction. The PostgreSQL job exercises independent-connection reservation concurrency. None of these tests demonstrate real provider readiness.
