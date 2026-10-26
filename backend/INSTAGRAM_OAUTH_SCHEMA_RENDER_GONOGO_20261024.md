# Instagram OAuth launch gate — schema rehearsal & Render log review
Date: 2026-10-24. **DRAFT / NO PRODUCTION OR STAGING MUTATION.**

Stacked after Draft PR #93 → #92 → #91 → #90 → #89 → #88 →
#87 → #86 → #85 → #84. NONE OF THESE SHOULD BE MERGED OR DEPLOYED
before an independently approved rollout.

## Verified from GitHub (NOT Render)

- The existing hand-authored migrations define
  `public.sendro_tenant_users PRIMARY KEY (tenant_id,user_id)` and
  `public.sendro_channel_accounts UNIQUE (id,tenant_id)`.
  The new *design* references these real composite keys.
- Existing Sendro app startup contains user/security column checks and
  automatic schema alterations; any staging deploy deserves independent
  review because staging and production reportedly share PostgreSQL.
- The dormant Phase 3-10 OAuth libraries expect **exactly two new tables**:
  `sendro_instagram_oauth_challenges` and
  `sendro_instagram_token_vault`. Neither is installed here.
- The challenge stores a SHA-256 state hash, exact requesting tenant/user,
  five-minute lifetime, optional Fernet-encrypted short-lived authorization
  code and callback receipt epoch. One-time atomic claims delete the row.
- The vault stores only account-/tenant-/provider-user-bound Fernet token
  ciphertext plus issue/expiry timestamps and an optimistic revision.
  No WhatsApp token or Meta App Secret belongs in the database.

## Files in this draft

1. `step7_oauth_vault_RELEASE_HOLD.sql` — explicit operator-reference
   PostgreSQL DDL with a mandatory RAISE EXCEPTION before the first CREATE.
   **DO NOT RUN on shared Sendro DB** or blindly remove the hold.
2. `step7_oauth_vault_readonly_preflight.sql` — metadata-only SELECT
   catalog checks. **Not executed against Render**. Query actual live
   catalog only after explicit owner approval.
3. `test_instagram_oauth_vault_schema_pg_ci.py` — tests the unmodified
   SQL aborts without creating any tables, then only in the existing
   *strictly allowlisted ephemeral GitHub PostgreSQL* removes the hold in
   memory, creates the proposed tables and tests expected FKs and
   constraints. Cleans up the disposable rows/tables. This test is added
   to the existing Instagram PostgreSQL CI job, no new job or service.

## High-priority prerequisite — incoming GET URL logging

Meta Instagram Login returns an OAuth authorization code via a callback
URL query parameter. This URL reaches Render's edge **before** our
Python/ASGI code. Render documentation says HTTP request log entries can
include the *requested URL*. Whether sensitive query strings are
visible/forwarded for the actual plan and services is **NOT YET VERIFIED**.

References:
- https://render.com/docs/logging
- https://render.com/docs/log-streams
- https://www.rfc-editor.org/rfc/rfc9700

At the read-only Render service inspection, confirm independently:
- Service plan and whether incoming **HTTP request logs** are enabled.
- Server startup command (Uvicorn/Gunicorn flags), access-log settings,
  reverse proxy, full request-target handling and telemetry/exporters.
- Sanitization of inbound callback `code` and `state` query strings
  across Render edge, app logs, trackers and any log streams.
- Outbound `graph.instagram.com/access_token` and
  `refresh_access_token` URL query parameters containing credentials
  are not logged by HTTP client instrumentation or error trackers.
- Confirm only with fake non-sensitive marker requests under a separate
  user-approved test. DO NOT send a real Meta authorization code to
  an endpoint until the log handling is positively established.

**If Render's request logging cannot reliably exclude query secrets,
OAuth callback activation is NO-GO**, even if the code-level boolean
attestations in PR #90 could be manually set to `true`.

## Render workspace must be explicitly selected by the owner

The connector currently lists three candidate workspaces:
`My Workspace`, `Sendro` and `Houses SunsetOia-Canaves`.
The operator must identify the workspace to inspect; no choice has been
made and no services or logs have been read in this step.

## DB/release go/no-go checklist

1. Owner explicitly confirms correct Render workspace. Inspect staging
   configuration *read-only*; never guess service IDs or touch the Houses
   environment.
2. Owner approves a read-only catalog snapshot and verifies a **fresh
   independent backup/restore** before any real write/migration.
3. DB reviewer checks actual catalogs, trigger/constraint conflicts,
   least-privilege role design, foreign keys, index size, table owner,
   schema grants and migration lock behavior.
4. Separate key ownership for short-lived callback encryption and
   long-lived token vault; document rotation and secure retention
   (including backup copies). Do not paste secret key material into
   chat, GitHub, Render logs or test fixtures.
5. Implement a rate limiter and challenge cleanup policy. State is
   only valid for five minutes; do not retain expired codes indefinitely.
   A manual migration **does not** imply an automatic cleanup worker.
6. Ensure account registry identity is verified by Meta, unique across
   tenants and correctly maps the reviewed existing
   `sendro_channel_accounts` record. Do not invent a registered
   connected account in production.
7. Implement server-side session binding, true
   `get_current_active_user` dependency, current MFA, owner/admin
   membership and reviewed CSRF/origin checks in an explicitly
   staging-only mount. Never use synthetic CI fakes.
8. Only after upstream log safety and approved DB rollout:
   stage one test Professional account, perform a supervised
   start → callback → completion → status check. Do not turn on
   Instagram webhooks, DM ingestion, replies or App Review prematurely.
9. Require a separate GO decision before any merge, Render deploy,
   Meta redirect registration or OAuth table installation.
10. Rollback must preserve the production WhatsApp service. Do not
    blindly DROP data-bearing tables; any rollback requires a separate
    backup, impact review and owner approval.

## Current status

- No Render workspace selected or service inspected.
- No live database queried or modified.
- No real token or Meta request sent.
- No merged PR, changed production WhatsApp code or new paid service.
- Only draft GitHub file changes and ephemeral GitHub CI test rehearsal.
