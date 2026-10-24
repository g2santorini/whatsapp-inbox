# Instagram OAuth Phase 7 — HTTP/callback safety gate (24 October 2026)

**DRAFT / UNMOUNTED / NO LIVE ACTIVATION.** Stacked after PR #89 →
#88 → #87 → #86 → #85 → #84. DO NOT MERGE INTO `dev` OR `main`.

## What this PR actually prepares

- A new `instagram_oauth_http_security.py` pure gate checks the *exact*
  expected staging backend Host, callback path, GET method, bounded and
  non-ambiguous query parameter shape; no secret is included in allowed
  audit events or outbound Meta target labels.
- The gate requires **five independent TRUE assertions**, default FALSE:
  ingress proxy URL-query redaction, ASGI access-log redaction, outbound
  Meta token URL-query redaction, incident/telemetry redaction, and
  explicit reviewed release authorization.
- The existing **unmounted** callback router now returns HTTP 503 unless
  a caller explicitly injects a request gate. Existing isolated tests use
  an obvious fake gate; new tests cover missing/partial assertions and
  malformed/foreign callbacks.
- A pure POST completion HTTP policy checks exact staging frontend
  `Origin`, backend `Host`, JSON content type and presence of a Bearer
  authorization header. **It does not validate that header's signature**:
  the real endpoint must separately use Sendro's genuine
  `get_current_active_user`, MFA + tenant owner/admin checks, committed
  one-use state claim, and browser-session/CSRF binding. No completion
  route has been added to the running backend.
- All scenarios use synthetic HTTP and fake provider codes. The test
  modules alone mount a FastAPI app; **Sendro's main app mounts none of
  these routes**.

## Crucial distinction: code guard != verified upstream safety

These five booleans **are NOT a proof**. They are a fail-closed declaration
interface for a separately documented and **independently verified**
infrastructure review. This PR has NOT examined Render ingress/access logs,
Uvicorn startup flags, proxy behavior, reverse-proxy instrumentation,
telemetry, Meta authorization, or actual outbound HTTP client logs.

**The OAuth code arrives in the incoming URL before Python can see it.**
A runtime route may hide it from its own response and STILL leak it at
the hosting edge, browser history or request logging. A Python log filter
cannot retroactively sanitize logs emitted by a proxy. The token-exchange
requests to Meta can also carry credentials in URL query parameters.

### Operator safety checklist BEFORE any real callback deployment

1. Inspect the actual Render staging service topology, trusted proxy,
   reverse proxy and Uvicorn access logging, diagnostics and telemetry
   **read-only**. Confirm exact sanitized request-target handling with
   synthetic fake codes, no real OAuth credentials. Never paste raw logs,
   secrets, codes or customer data into GitHub or chat.
2. Verify outbound Meta HTTP-client instrumentation and error trackers
   never record client secret or access-token query strings. Make the
   staged secretless test fail if this cannot be independently confirmed.
3. Document who approved each of the five attestations, when, and with
   what evidence; NEVER default them to True. A checklist supplied by
   a developer alone does not qualify as independent attestation.
4. Protect the real GET callback and separate authenticated POST
   completion with origin/session binding, verified current Sendro JWT,
   fresh authenticator proof, exact same user + tenant, bounded retries,
   and committed single-use state/code; reject cross-company attempts.
5. Manually review strict callback URL registration and exact Instagram
   Login App identity/permissions in Meta, only AFTER approved live
   staging deployment of the endpoint.
6. Approve the separate OAuth table/token vault schema and restricted
   PostgreSQL privileges only after fresh verified backup/restore and
   separate owner authorization. Staging still shares live production
   PostgreSQL. No automatic startup migration.
7. Keep Instagram webhook subscriptions, ingestion, workers, outbound
   messaging, and Meta App Review submission OFF until the separate
   operational evidence/checkpoints are met.

## No operational changes

Only code/tests/docs in a feature branch. No Render deployment,
environment change, database SQL, backup operation, Meta call, new
service, CI job, or modification to production WhatsApp. Synthetic test
passing does not mean these five operational checks have passed.

References:
- OAuth Security BCP RFC 9700 §4.2 (credential leakage in Referer)
  https://www.rfc-editor.org/rfc/rfc9700
- RFC 6819 §4.4.1.1 and §4.6.7 (request URL and access log leakage)
  https://www.rfc-editor.org/rfc/rfc6819
- OWASP Logging Cheat Sheet (exclude secrets and tokens)
  https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
