# Instagram Connect — staging-only UI preparation (24 October 2026)

**STATUS: DRAFT / READ-ONLY SETUP PREVIEW / LIVE CONNECT DISABLED.**
Stacked after Draft PR #91 → #90 → #89 → #88 → #87 → #86 → #85 → #84.
Nothing in this branch is merged to `dev` or `main` or deployed.

## What is now ready for review

- A compact **Instagram account connection** panel is integrated into
  `InstagramInboxPage.jsx`, **only** when the frontend browser hostname
  is exactly `sendro-frontend-staging.onrender.com`.
- It is deliberately passed `enabled={false}`, `channelAccountId={null}`,
  and **no start/finish API handlers**. Therefore Connect Instagram is
  visibly disabled even on staging. The panel truthfully says Instagram
  authorization is not active; it does not claim an account is connected.
- `InstagramConnectPreview.jsx` is a reusable dormant UI with future
  start/complete controls, allowing the browser to open the validated Meta
  authorization in a separate window, then return to the original Sendro
  tab to complete. No automatic API calls, polling or browser storage on
  render. No connection can start without several **independent** guards.
- `instagramConnectFlow.js` verifies strict staging-only hostname,
  required account/tenant/user and MFA plus explicitly enabled adapters,
  an exact Instagram Login authorization destination, requested
  permissions, the pinned staging callback, state format and 5-minute
  expiry. In-memory state is discarded on cancel/user/company/account
  change, unmount or failure; **not** localStorage, sessionStorage, URL
  fragments, analytics or clipboard.
- Future `/complete` payload uses only tenant ID, authorized registry
  account ID and state. The provider authorization `code`, access
  token and App Secret **never** reach this UI. One failed completion
  requires a new authorization; don't replay previously consumed state.
- Mobile-responsive visual styling and Node tests are included in the
  **existing** frontend CI job (no extra runner/service).

## Current blockers before enabling the button

1. There is **no reviewed live onboarding deployment**: backend router
   from PR #91 is still UNMOUNTED and disabled by default, and Meta
   callback is not active. Without these, the UI must never offer
   functional login.
2. The browser currently cannot reliably fetch a signed, tenant-scoped
   **pre-enrolled Instagram channel account ID**: no reviewed read-only
   account-status/registry API has been deployed. The UI therefore uses
   `channelAccountId={null}` intentionally. Never accept an
   arbitrary user-entered account ID.
3. Need an actual staging API adapter with current Sendro bearer/MFA,
   reviewed CORS and session binding, anti-replay, consent lifecycle,
   bounded errors and identity check; `startConnection` and
   `finishConnection` are **not wired** here.
4. Existing Sendro login uses a bearer token in localStorage; this PR
   does not modify that authentication architecture. Keep OAuth state
   only in volatile memory and separately review popup/mobile
   tab handoff, login changes and refresh/logout behavior.
5. Verify Render proxy/ASGI logs and outbound Meta query logs/telemetry
   never capture OAuth codes, provider tokens or app secrets. Code-level
   PR #90 booleans do **not** prove infrastructure safety.
6. Confirm the final OAuth and vault PostgreSQL schema/roles and
   approved migrations with an independently verified fresh
   backup/restore. Dev staging shares production WhatsApp PostgreSQL.
   Nothing may be installed automatically at startup.
7. Meta Instagram Professional Login App ID/Secret, reviewer
   permissions, redirect registration and the test Professional
   account must be verified before a genuine end-to-end connection.
8. The server must expose an independently authorized, **token-free**
   connected-account status API after reload before calling the
   connection permanently active. The current panel does not infer
   previous connections or claim durable status from browser memory.
9. Real DMs, webhooks, worker delivery, Meta App Review submission,
   token auto-refresh, revoke and audit remain OFF.

## Safety HOLD

- No merge of #84–#92 to `dev`/`main`, and NO Render deploy.
- No production WhatsApp code, settings, data, Meta subscriptions,
  shared PostgreSQL changes, real provider credentials or paid services.
- In a future reviewed staging deployment **with the button still
  disabled**, the card may be displayed as a truthful preparation
  preview, not a working connection.
