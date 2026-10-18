# GDPR Manager — gated read-only preview rollout

**Status (17 Oct 2026): implementation only. Feature flag stays OFF.**

The database migration was independently verified in the live shared Render
PostgreSQL: `sendro_privacy_cases` and `sendro_privacy_case_events` exist,
the lookup index and append-only audit trigger are present, and both tables
are empty immediately after migration. This **does not authorize making the
request-management API available to users**.

## Scope of this PR

- `backend/app/privacy_readonly_preview.py` contains exactly two authenticated
  GET endpoints:
  - `GET /privacy/requests?tenant_id=<integer>`
  - `GET /privacy/requests/{opaque_case_ref}?tenant_id=<integer>`
- All responses are non-identifying case summaries, not customer messages.
  `Cache-Control: no-store, private` and `X-Robots-Tag` are added.
- The existing tenant-role validation in `privacy_case_store.py` runs on
  **every** GET against active `sendro_tenant_users` membership and
  non-disabled `users`; only tenant owners/admins are allowed. Inactive
  users, operators, viewers and cross-tenant requests are denied.
- The mounted router has no POST/PATCH/PUT/DELETE endpoints and never calls
  the case writer. No data retention purge, GDPR deletion, or customer
  lookup has been enabled.
- The **existing** full request-management API factory in
  `privacy_case_api.py` stays **unmounted**.
- The Sendro frontend has **no GDPR Manager tab yet**.

## Fail-closed rollout conditions

By default there is **no /privacy/requests route** in the running app.
For a future separately approved, non-production **read-only preview**, all
three environment variables must match exactly:

```text
SENDRO_PRIVACY_READONLY_PREVIEW=enabled
SENDRO_PRIVACY_READONLY_REVIEWED=reviewed-read-only-tenant-auth
RENDER_SERVICE_ID=srv-d806bq0sfn5c7399akng
```

The last value is the staging backend service ID, not the production ID.
The code **must not modify** `RENDER_SERVICE_ID` and must not treat
user-supplied HTTP headers as service identity. Missing, wrong or incomplete
configuration silently leaves the feature disabled without breaking Sendro.
**No one should set these flags yet.** Staging and production share the
same PostgreSQL database, so even staging activities must follow a separate
review/authorization.

Staging readiness gates before enablement:
1. Review auth and tenant membership using real Sendro roles; confirm
   appropriate privacy officers and MFA policies.
2. Verify direct access cannot bypass the app's existing password/MFA
   requirements, including project-only account restrictions.
3. Review risk of metadata disclosure, CORS, logs, reverse-proxy caches,
   access patterns, monitoring and rate limits.
4. Verify GET-only behavior and no POST routes on the staging service.
5. Obtain an explicit request to enable the staging preview; keep production
   disabled, and never enable the mutating API in this phase.

Synthetic API tests run on local in-memory SQLite, without access to
the shared Render database.

## Local restore copy — cleanup when review finishes

The Windows recovery drill left a **local duplicate of guest data** in:
- `%LOCALAPPDATA%\SendroRestoreTest_20261017\data` (restored test PostgreSQL).
- `%USERPROFILE%\Downloads\SendroBackupCheck_20261017` (extracted backup).

Keep the original `.dir.tar.gz` backup in a private secure location per
retention policy. **Never upload the backup or extracted data to GitHub,
ChatGPT, public folders or shared chat.**

Before deleting the local duplicates, check exact paths on the owner's own
machine and stop the test server bound to 127.0.0.1:55441. Suggested staged
verification, NOT an unattended script:

```powershell
$testDir = "$env:LOCALAPPDATA\SendroRestoreTest_20261017"
$ctl = "$env:LOCALAPPDATA\SendroPG18Extract\bin\pg_ctl.exe"
& $ctl -D "$testDir\data" -m fast stop
& "$env:LOCALAPPDATA\SendroPG18Extract\bin\pg_isready.exe" -h 127.0.0.1 -p 55441
```

The readiness check should report no response. **Only after owner confirms
the exact paths** is it appropriate to remove the two temporary copies.
Do not delete any `C:\Program Files\PostgreSQL` directory or the original
downloaded archive during cleanup. Ordinary file deletion on SSD is not a
certified secure erasure operation; storage encryption/access policy matters.


## Follow-up review (18 Oct 2026): rate limiting, CORS, and logging

- A separate hardening PR proposes an **in-memory** budget of **30 GET requests
  per minute per active reviewer** across both preview routes. Exceeding it
  returns HTTP 429 with `Retry-After`. This is intentionally a lightweight
  single-instance staging mitigation; multiple replicas/worker processes would
  require a shared distributed limiter before real SaaS rollout.
- The hardening adds `Cache-Control: no-store, private`, `Pragma: no-cache`,
  `Expires: 0`, and `X-Robots-Tag` to all privacy HTTP responses, including
  authentication/validation/rate-limit denials. Intermediary CDN/proxy
  behavior still needs verification.
- The existing backend uses `CORS_ALLOWED_ORIGINS` as an origin allowlist,
  with broad allowed methods and headers. Its **effective value on Render is
  not exposed by the read-only service API**: inspect staging manually
  before approving flags. Do not broadly change the global CORS settings
  as part of this GDPR-only feature. CORS does **not** replace JWT and
  tenant authorization.
- Render request access logs might contain privacy URL paths (including opaque
  `case_ref`) and the `tenant_id` query parameter; verify retention, access
  and proxy behavior without dumping live logs or customer data. Do not put
  names, emails, phone numbers, user secrets or tokens into privacy URLs.
- Keep the feature OFF until the remaining review is explicitly approved;
  production remains OFF, and no database changes or GDPR mutation routes
  are authorized.
