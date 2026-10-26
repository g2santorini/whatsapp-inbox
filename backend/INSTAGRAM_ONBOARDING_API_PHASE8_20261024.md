# Instagram Login Phase 8 — Dormant authenticated start/complete API (2026-10-24)

**UNMOUNTED / DRAFT / ABSOLUTELY NO PRODUCTION, META OR STAGING CHANGES.**
Stacked after Draft PR #90, #89, #88, #87, #86, #85 and #84.

## Actual contribution

The new `backend/app/instagram_onboarding_router.py` implements a **server-only opt-in FastAPI router factory** that uses the already prepared OAuth libraries in the correct transaction order.

- `POST /channels/instagram/oauth/start` accepts **only** `{"tenant_id": integer}`. When the explicit `enabled=True` and ALL reviewed operational gate assertions are present, it reuses real Sendro auth dependencies supplied by the actual app at future mounting time, current JWT version, recent MFA and active tenant owner/admin authorization; commits a 5-minute hashed OAuth state; then returns the authorize URL and expiry.
- The Meta `GET /channels/instagram/oauth/callback` is a **separate** existing *unmounted* route that stores the provider code encrypted. It must **not** be mounted before confirmed reverse-proxy/ASGI access-log redaction and manual restricted DB migration.
- `POST /channels/instagram/oauth/complete` accepts only a tenant ID, channel account ID and the state (never provider code/token). It requires exact staging frontend `Origin`, backend `Host`, a bearer authentication header, and a real current-user injection when actually mounted. Then it atomically burns the encrypted code for the exact tenant and user and **commits** before invoking Meta identity verification; a second committed transaction stores only encrypted long-lived token to the pre-enrolled Instagram account.
- On failure the code must be reacquired by a new authorization; no second Meta call for the same consumed state. Responses redact provider codes, secrets, SQL details and tokens, and use no-store. The intermediate code/token is **briefly present in server memory only**, not in the browser.
- The code is strictly **disabled by default** and is **not mounted in `backend/app/main.py`**. No token/DB calls run on import.
- Isolated in-memory SQLite/FastAPI TestClient tests include the HTTP start + fake encrypted callback capture + HTTP completion + Fernet vault storage flow; invalid user/tenant/CSRF-Origin/expired MFA/duplicates/provider error/replay all fail closed. The suite is included in the existing backend CI job; no extra runner/job/service.

## Important remaining safety and product work

1. **The browser-session/popup bridge is not implemented**. The frontend currently keeps bearer access tokens in its existing localStorage architecture. This PR does not change it. Before using a live Instagram OAuth state, implement an audited frontend workflow that keeps state in volatile memory and validates authenticated Sendro session, with reconnect/reload behavior, no leakage through logs, telemetry, history or Referer.
2. `start` currently returns an authorize URL containing OAuth state to its authenticated caller as required for navigation. It must never be logged, shown to unrelated users, stored with customer conversation data or left accessible by cross-origin callers.
3. The actual `get_current_active_user` and OAuth2 bearer dependencies **must** be injected at a separately reviewed mount site. Test fakes are intentionally not a live authentication integration. Header presence alone is not authentication; the library's signed-JWT/MFA/member checks provide additional protection. Review browser CSRF/session binding and rate-limiting before enable.
4. Render log behavior (ingress proxy access logs, ASGI logs, outgoing Graph query strings and error trackers) has **not** been inspected. Render requires choosing a user-confirmed workspace. Assertions in code cannot attest its infrastructure.
5. Neither `sendro_instagram_oauth_challenges` nor `sendro_instagram_token_vault` is installed. Existing `public.sendro_channel_accounts` must already contain an authorized, unique matching Instagram account in testing or active status for vault save. Future self-service pre-enrollment and conflict-safe account registry remain incomplete.
6. The live staging and main services share PostgreSQL. BEFORE any table install or rollout: fresh independently verified backup/restore, review of actual schema and DB permissions, strictly scoped migration/rollback and explicit user authorization. Do **not** run schema updates by FastAPI startup or a GitHub action.
7. Full Meta authorization verification and long-lived token renewal depend on actual account permissions, current Meta requirements, provider responses, and dedicated vault secrets. No public claims, screencast or Meta App Review submission until a genuine staging onboarding succeeds.
8. Keep Instagram webhook ingestion, workers, subscriptions, outbound DM messaging, Render deployment and WhatsApp production changes OFF.

This closes an **isolated code integration gap**, not the operational release. It does not establish that logs are redacted, schemas exist, a user has connected Instagram, or real incoming DMs work.

## Release HOLD

Do not merge PR #91 or the stacked PRs #84–#90 into `dev` or `main`, do not deploy or change Render/Meta configurations, do not access or modify shared PostgreSQL or actual guests, and do not enable Instagram communication. No new paid service was created.
