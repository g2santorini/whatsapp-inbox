# Instagram Business Login — dormant foundation (23 October 2026)

**Status: prepared for isolated review only, NOT a connected Instagram account.**

This branch adds a standalone server-side protocol adapter and mocked tests. Nothing is mounted in FastAPI and no Meta call happens automatically. This is not an Instagram login button, not an operational token vault, and is not sufficient for the App Review screencast.

## Prepared

- Instagram Login, NOT Facebook Login. Only scopes: instagram_business_basic, instagram_business_manage_messages.
- Strictly pinned *future* staging callback:
  https://sendro-backend-staging.onrender.com/channels/instagram/oauth/callback
  **It is not mounted or registered in Meta yet; do not enter this URL until the actual protected endpoint exists.**
- Random OAuth state and constant-time comparator. A real flow MUST store the state, bind it to an authorized tenant user, expire it, and consume it once; a comparator alone does NOT protect against CSRF or replay.
- Server-side POST to api.instagram.com/oauth/access_token and read-only GET to graph.instagram.com/me, with bounded timeouts, no redirects and errors that do not reflect tokens or secrets.
- Fully mocked, no-network tests.

## Must be finished before a real connection or screencast

1. Build authenticated, MFA-aware, tenant-admin-only onboarding endpoints and a real callback; enforce one-time state, expiry, account-to-tenant mapping and rate limits.
2. Prepare reviewed encrypted access-token persistence, long-lived exchange/refresh, token revocation and disconnect, privacy erasure and audit. Do NOT alter the shared staging/production database until backup/restore evidence and approval.
3. Configure correct Instagram Login App ID and Secret on the *staging backend only*. Do not assume the general Meta App ID is the Instagram Login App ID; never paste secrets into chat or GitHub.
4. Register the exact live callback with Meta **only after** that endpoint is deployed and verified.
5. Add a real Connect Instagram UI and read-only professional-account details, then record a genuine login and profile display for the App Review reviewer. No fabricated screen recording.
6. Keep Instagram webhook subscription and message ingestion/worker/send flags OFF. The separate attended-pilot HOLD checklist still applies.

**Hard boundaries:** no main/production merge, no dev deploy from this draft branch, no Render environment changes, no Meta Publish/App Review submission, no webhook subscription, no live message data, no WhatsApp edits and no database migration.
