# Instagram OAuth Phase 2: tenant-bound one-time state (23 October 2026)

**DRAFT / NOT DEPLOYED / NOT A WORKING INSTAGRAM ACCOUNT CONNECTION.**

## What's implemented (dormant)

`backend/app/instagram_oauth_state.py` contains two manual-use functions.
They depend on the parent PR #84 protocol adapter and are not imported by
`backend/app/main.py`, not routed, and not callable through staging or Meta.

- Start validates a **real signed Sendro JWT**, current `auth_version`,
  recently verified MFA (10-minute requirement), active user, and an **active
  owner/admin membership** in the specific tenant. It does not accept a
  supplied "is admin" boolean or grant viewer/operator access.
- Only the **SHA-256 digest** of a random 256-bit OAuth state is persisted.
  A nonce lives for at most 300 seconds and is never stored in plaintext.
- Completion repeats JWT/MFA, auth version, active membership and exact
  tenant/user checks, then atomically **DELETE ... RETURNING** the matching
  unexpired challenge to prohibit replay, even across separate workers.
- The functions deliberately make **no Meta API calls** and cannot issue
  Sendro authentication, persist Instagram access tokens, start workers,
  subscribe webhooks or change WhatsApp conversations.
- Synthetic SQLite tests attach an ephemeral `public` schema and model
  only these two new state operations; they do not touch a real database.

## Planned database design; no DDL has been run

The coordinator expects a future manually approved table in the existing
Sendro PostgreSQL schema, **not installed by this PR**:

```sql
-- DESIGN REFERENCE ONLY. DO NOT RUN ON SHARED PRODUCTION/STAGING DB.
CREATE TABLE public.sendro_instagram_oauth_challenges (
  state_hash CHAR(64) PRIMARY KEY,
  tenant_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  created_epoch BIGINT NOT NULL,
  expires_epoch BIGINT NOT NULL,
  CHECK (expires_epoch > created_epoch),
  CHECK (expires_epoch <= created_epoch + 300),
  FOREIGN KEY (tenant_id, user_id)
    REFERENCES public.sendro_tenant_users (tenant_id, user_id)
);
-- Future operator-reviewed expiry cleanup and privileges required.
```

**BEFORE any real DB migration:** a fresh independently tested backup/restore,
SQL role-privilege review, exact existing table/PK verification, tenant
security controls, scoped migration/rollback and separate owner approval.
Staging and production currently share the same PostgreSQL instance.

## Callback architecture blocker

The eventual Meta redirect is a GET to
`https://sendro-backend-staging.onrender.com/channels/instagram/oauth/callback`.
That route **does not exist**. The real flow must not receive code+state
on that URL until an audited bridge to an authenticated Sendro browser
session exists, with short-lived browser binding, hardened cookies, no
Referrer leaks, restricted callback responses, and provider-code handling
that does not expose secrets in logs. The eventual authenticated completion
must call `consume_instagram_oauth` in a committed transaction BEFORE
exchanging a Meta code. This exact session binding/bridge is a separate
design/review step. The current pure function **cannot process Meta's
callback** on its own.

After that: encrypted Instagram token vault, refresh/revocation and manual
disconnect; exact authorized Instagram account-to-tenant binding; review
of App ID versus Instagram Login App ID; account/profile display in a
staging UI; actual authorized end-to-end recording for Meta App Review.

## Rollout/financial/operational boundaries

- Branch is based on unmerged **PR #84**; this stacked PR must stay Draft.
- No merge into dev/main; dev auto-deploys, both environments share DB.
- No new Render service/database/paid plan, no CI PostgreSQL service,
  no Meta credential, no App Review submit/Publish.
- Keep `INSTAGRAM_WEBHOOK_INGESTION_ENABLED`,
  `INSTAGRAM_WORKER_MANUAL_ENABLED` and live Instagram subscriptions OFF.
- Prior safety HOLD applies to one real DM testing.
