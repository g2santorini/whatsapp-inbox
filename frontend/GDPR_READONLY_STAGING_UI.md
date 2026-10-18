# GDPR Manager — read-only frontend preview (staging only)

The GDPR Manager preview appears only on the staging frontend (or a local Vite dev server) and only after an authenticated, fresh-MFA GET to the server's `/privacy/requests/tenants` returns at least one authorized tenant. Tenant discovery is **not** derived from Instagram membership, hardcoded company ID, or the global Sendro user role alone.

## Allowed workflow

- Select from the tenant companies returned by the reviewed backend's active owner/admin membership query.
- Manually refresh the first 50 non-identifying privacy cases.
- Select a case to review status, channel, audit-event count, blockers and whether a response was recorded.
- Any 401/403 is displayed as a sign-in/MFA/authorization error without leaking backend response details.
- No background polling, local storage of case data, data export, subject lookup, POST, PATCH, DELETE, case creation or erasure action.

## Backend scope

The only new route is `GET /privacy/requests/tenants`, mounted under the exact pre-existing staging-only environment/service-ID gate. It shares the signed recent-MFA dependency, 30/min per-reviewer limiter, no-store middleware, and Uvicorn privacy-path redaction. Database queries select only owner/admin tenant membership and tenant ID/display name, and use rollback-on-exit. This PR changes neither schema nor data nor production main. Existing case list/detail routes remain unchanged.

## Verification

1. Run synthetic privacy tests, including disabled gating and cross-tenant discovery. Build/lint frontend.
2. With read-only preview enabled **only on staging**, log in via Authenticator, verify GDPR tab appears only for eligible tenant admins/owners and shows company list from backend. Expect empty case register for a company with no cases.
3. Test expired MFA, non-MFA/trusted-device login, operator, disabled member, and an unrelated tenant; no unauthorized record should appear. No sensitive tokens in screenshots/chat.
4. Check mobile nav and switching between Inbox, Instagram, Projects & Tasks, GDPR without breaking existing polling/send behavior.
5. Keep deployment to `dev` subject to explicit approval, and keep production `main` untouched. A staging preview is not production clearance; review Render/Cloudflare request metadata retention and multi-worker rate limiting before SaaS rollout.
