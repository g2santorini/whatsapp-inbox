# Instagram OAuth Phase 3 — encrypted callback intake, **NOT DEPLOYED**

23 October 2026. Stacked on Draft PR #85, which is stacked on Draft PR #84.
Everything remains **offline and manual-only** until a separate reviewed rollout.

## Scope

- `backend/app/instagram_oauth_callback_inbox.py` is **not imported or mounted** by `backend/app/main.py`. The callback path does **not yet exist** on staging and MUST NOT be configured as a working Meta redirect.
- A future `GET /channels/instagram/oauth/callback?code=...&state=...` can store the short-lived provider **authorization code**, encrypted with a dedicated Fernet key, **at most once** for an existing unexpired hashed state, without returning the code to the browser.
- Only fixed, inline, JavaScript-free HTML is returned. Headers disable caching, referrals, framing and external resources. Duplicate fields, missing/denied authorizations and server errors fail closed without reflecting sensitive query values.
- Local offline TestClient/SQLite tests are synthetic; they do not use Render or Meta.

## Required manual PostgreSQL schema plan (DESIGN ONLY — DO NOT RUN)

The OAuth state table described in PR #85 remains **uncreated**. The final approved table requires at least:

```sql
-- ONLY A SCHEMA DESIGN EXCERPT. DO NOT RUN ON SENDRO SHARED DB.
-- Include in an independently reviewed *new-table* migration:
encrypted_authorization_code BYTEA NULL,
received_epoch BIGINT NULL,
CONSTRAINT ck_ig_oauth_received_consistent
  CHECK ((encrypted_authorization_code IS NULL) = (received_epoch IS NULL))
```

No schema DDL, startup migration, token storage, or query was executed on
the real database. The existing isolated SQLite tests define their own
disposable structures. Expired challenge/code records need an explicitly
reviewed deletion policy and restricted write privileges before enabling.

## Blocking prerequisites before anyone can actually connect Instagram

1. Security review of **reverse proxy, ASGI, access-log and error-monitor query redaction**: a Meta code arrives as a URL query before Python can hide it. No OAuth GET endpoint may be mounted until logs are demonstrably scrubbed.
2. Implement an audited **authenticated POST completion**: require the same Sendro user and tenant owner/admin, recent MFA, CSRF/session binding, compare exact state, and atomically burn/decrypt the stored one-time code. The parent PR #85 `consume_instagram_oauth` is **not yet extended** for the new encrypted-code fields and must not be used as if complete.
3. Authorize the final PostgreSQL schema and restricted DB role only after fresh verified backup/restore and distinct review. Staging and production share their existing DB.
4. Install a **separate encrypted Instagram access-token vault** with provider-code exchange, long-lived token refresh, disconnect/revocation, token ownership and safe deletion. No access token belongs in `sendro_channel_accounts` as plaintext or a browser.
5. Create a real staging UI `Connect Instagram` using a separate tab while keeping the original authenticated session; route all state/code completion through server-only endpoints. No browser-side use of App Secret.
6. Confirm the actual Instagram Login App ID/Secret and exact allowed redirect URI in Meta. Register it only once the real callback is deployed and verified. Keep App Review unsubmitted for now.
7. Only after actual account connectivity, authorized identity verification and a safe profile view may a **real screencast** be recorded for Meta.

## Absolute HOLD

Do not merge this stack to `dev`/`main`, trigger Render deploys,
create paid services, touch the shared PostgreSQL DB, send real Instagram
messages, enable webhook subscriptions, or modify the production WhatsApp
Inbox. The attended first-real-DM GO/NO-GO checklist remains independently
blocking. This code is one intermediate component, not a finished OAuth flow.
