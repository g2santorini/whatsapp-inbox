# Instagram Login Phase 6 — Verified Account Link (24 October 2026)

**STATUS: PREPARED ONLY — NOT ROUTED, NOT DEPLOYED, NO REAL META SESSION.**
Stacked Draft after PR #88 → #87 → #86 → #85 → #84.

## What changed

- New `backend/app/instagram_account_link.py`: manual-call-only **trusted
  server** coordination between the committed single-use OAuth-code claim,
  Meta Instagram Login short-lived exchange, read-only professional account
  identity, Meta long-lived exchange, identity **reverification** with that
  long-lived token, and the previously prepared Fernet encrypted vault.
- Both short- and long-lived token profiles must have the same exact
  Instagram **user ID**; each must be a BUSINESS or CREATOR account, with
  matching account type. Fail closed on identity/permission/provider errors.
- The returned intermediate VerifiedInstagramLink contains a plaintext
  credential ONLY briefly in trusted server memory; its `repr` and `str`
  redact contents. It must never be serialized, logged, saved in a browser,
  or exposed to tenant-facing read APIs.
- Saving rechecks actual signed Sendro JWT+fresh MFA, the **same user and
  tenant** as the committed one-use claim, and the exact pre-enrolled
  Instagram channel account before installing ciphertext. The vault also
  rejects duplicate/overwriting installs. The return object includes
  **only** a boolean connection status and expiry epoch.
- The earlier `InstagramShortToken` now redacts its `repr` and `str`,
  so an incidental object log cannot reveal this sensitive credential.
- Adds isolated SQLite and mocked Meta HTTP tests plus an entry in the
  **existing** backend CI test job — no new CI service or runner.

## Critical responsibilities NOT implemented

1. The callback route is still **not mounted** in FastAPI. Before enabling it,
   confirm external proxy, ASGI and monitoring log redaction of URL query
   strings: Meta sends a sensitive OAuth code on a GET callback URL.
2. An authenticated tenant-admin completion route with recent MFA,
   origin/session/CSRF binding and a **committed** one-time claim remains to
   be built. The committed claim is passed server-side to this coordinator;
   **never initiate Meta calls inside the SQL transaction**.
3. The `sendro_instagram_oauth_challenges` and
   `sendro_instagram_token_vault` tables are **NOT CREATED**. Staging
   currently shares PostgreSQL with live WhatsApp. A separate manual
   migration and scoped database roles require fresh independently verified
   backup/restore and explicit operator approval.
4. Configure real Instagram Login App ID/Secret only in the authorized
   staging runtime after security review; never paste into chat/GitHub/logs.
   The `graph.instagram.com/access_token` URL for token exchange can carry
   secrets as query params — verify upstream logs and telemetry redaction
   for **both** callback AND outbound Meta queries.
5. A reviewer-visible `Connect Instagram` UI, audited subscription and
   token refresh worker, local+Meta disconnect guidance, key rotation,
   incident handling, token deletion, and live account enrollment are all
   missing. A full live onboarding test remains blocked.
6. The real Meta App Review must not claim these components are live.
   A genuine screencast may be recorded only after the actual test account
   is connected and correctly displayed in staging.

## Absolute HOLD

- Do not merge this Draft stack to `dev` or `main`; dev auto-deploys.
- No shared database read/write/migration, no Meta settings modification,
  no live webhook subscription, no Instagram DM ingest/send, no production
  WhatsApp code changes, no new paid services.
- Passing synthetic tests is **not** live authorization proof.

References for current Instagram Login permission scope in Meta's own
Postman workspace: https://www.postman.com/meta/instagram/folder/6raa77c/instagram-api-with-instagram-login

Meta scopes remain `instagram_business_basic` and
`instagram_business_manage_messages`; unrelated publishing, comments
and Facebook Login permissions are not requested.
