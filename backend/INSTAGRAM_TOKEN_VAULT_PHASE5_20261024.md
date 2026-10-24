# Instagram Login Phase 5 — encrypted long-lived token vault (2026-10-24)

**STATUS: DRAFT, DORMANT, NOT DEPLOYED.** Stacked on PR #87, then #86, #85, #84. No real Meta credentials, calls, or customer data have been used.

## What is prepared

- `backend/app/instagram_token_vault.py`: a **library-only**, tenant-scoped Fernet vault that encrypts the *long-lived* Instagram Login token in a purpose-, company-, channel account-, and Instagram user ID-bound envelope.
- Every admin call reuses Sendro signed JWT/auth_version and recent MFA checks, plus actual active **owner/admin** tenant membership. The channel account must be a matching enrolled Instagram account in `testing` or `active`; WhatsApp and other companies cannot read or register credentials.
- First token install is **insert-only** (no silent replacement). Refresh uses optimistic compare-and-swap with `revision`, denies premature (<24h) or expired refreshes, and keeps tokens encrypted. Wrong decryption key or swapped-company ciphertext fails closed. Only fixed, redacted errors and a server-only secret holder are returned.
- Local disconnect **deletes the token from Sendro's vault only**. It does **not** revoke the user's authorization at Meta, turn off their subscriptions, delete Instagram conversations, or prove the account has been fully disconnected in the UI. These further actions need reviewed integration and auditing.
- `backend/app/instagram_token_lifecycle.py`: manual-call-only adapter for Meta Instagram Login long-lived exchange (`ig_exchange_token`) and refresh (`ig_refresh_token`), with pinned HTTPS Graph endpoints, bounded timeout, no redirects, response validation, and sanitized errors. No automatic scheduling and **no network calls unless deliberately invoked in future audited runtime code**.
- Two new isolated synthetic test suites, included in the **existing** GitHub CI backend job (no additional job). The Python implementation is unmounted and inert.

## Proposed schema — DESIGN ONLY; DO NOT RUN

The separate vault table does **not** exist on Render. This example must be reviewed against the actual PostgreSQL catalog and privileges before the **owner** approves a manual migration.

```sql
-- DESIGN REFERENCE ONLY — DO NOT RUN AGAINST THE SHARED SENDRO DB.
CREATE TABLE public.sendro_instagram_token_vault (
    tenant_id BIGINT NOT NULL,
    channel_account_id BIGINT NOT NULL,
    provider_user_id VARCHAR(128) NOT NULL,
    encrypted_token BYTEA NOT NULL,
    issued_epoch BIGINT NOT NULL,
    expires_epoch BIGINT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (tenant_id, channel_account_id),
    CONSTRAINT fk_ig_vault_account_tenant FOREIGN KEY
      (channel_account_id, tenant_id)
      REFERENCES public.sendro_channel_accounts (id, tenant_id)
      ON DELETE RESTRICT,
    CHECK (revision >= 1),
    CHECK (expires_epoch - issued_epoch BETWEEN 86400 AND 5356800),
    CHECK (provider_user_id ~ '^[0-9]{1,128}$')
);
-- Final version: restricted separate runtime role/privileges, audit,
-- encryption-key ownership, backups, deletion/retention plan.
```

**No SQL was executed on production/staging.** The existing production/staging backends share the same database. Installation needs an independently verified fresh backup/restore, the real-role ACL review, operator approval and stop/rollback instructions.

## Critical prerequisites for a REAL connection

1. Confirm Meta **Instagram Login** App ID/Secret (distinct from the general Meta App identifiers where applicable), exact provider scopes, and official current token responses. Do not share credentials in chat, GitHub, or browser scripts.
2. Complete the **unmounted** authenticated OAuth callback/session bridge with access-log and telemetry URL-query redaction. Meta authorization codes and Graph token exchange query strings may contain secrets: **do not enable** until logging/instrumentation is verified safe.
3. Make the server validate both the short-lived token subject and the profile ID from Meta, then verify the enrolled channel account belongs to the same tenant; do **not trust a browser-supplied Instagram ID**.
4. Explicitly authorize a reviewed **separate encrypted vault** migration, limited DB privileges and a dedicated `INSTAGRAM_TOKEN_VAULT_KEY` separate from the webhook-encryption key. Plan key rotation, backup security, restoration and incident response.
5. Integrate authorized, error-safe exchange to long-lived token **server-side**, durable save, and a confirmed status screen. Never return the token to React or log URLs carrying it.
6. Build automated renewal with a separately scoped worker/service role, redacted alerts, retry limits and revocation/re-auth flows. The present helper requires a fresh human admin MFA; it **does not provide unattended token refresh**.
7. Implement proper local disconnect/disable plus Meta revocation guidance and audit, then consent-driven staging Connect Instagram UI. Only after real testing can we record a genuine Meta App Review screencast.

## Absolute HOLD

- Draft PR only; **do not merge to dev or main**, and do not trigger Render deploys. The existing dev branch auto-deploys and its DB is production-shared.
- No Instagram webhook subscription, message ingestion, real send/receive, Meta app Publish/Review submission, environment/secrets change, or new paid services.
- No WhatsApp webhook, polling, business data, schema or main branch modification.
- Passing local or GitHub CI checks is synthetic proof of isolated code behavior, not a real live connection or independent operational readiness certification.

## External protocol pointers

Meta's Instagram Login uses the Instagram professional account, not Facebook Login. The short token is exchanged via `https://graph.instagram.com/access_token` with `ig_exchange_token` and the long-lived token is refreshed via `https://graph.instagram.com/refresh_access_token` with `ig_refresh_token`. Validate final integration against the current official Meta developer documentation prior to activation.
