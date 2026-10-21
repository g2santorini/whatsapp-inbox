# Instagram Incident Center — unmounted in-app preview and recent-MFA authorization contract

**2026-10-21 — SYNTHETIC/GITHUB CI ONLY.** The in-app Incident
Center is a *prototype*, **not an enabled production feature**.

## Existing Sendro implementation inspected

- The normal login path in `backend/app/main.py` gets the active
  Sendro user from a verified JWT and actual `public.users` record.
  `User.role` in `backend/app/models.py` uses the `admin` label.
- A separate existing `privacy_mfa_session.require_recent_mfa_token`
  checks signed, time-bounded `mfa_verified_at` claims, with a ten-minute
  maximum age; setting `mfa_enabled` alone **does not** prove
  recent MFA. Its real dependency currently applies to privacy functions.
- The `instagram_inbox_api` lists normal DMs by **tenant membership**.
  By contrast, the prototype alert outbox codes are *global aggregate*
  Instagram queue-health incidents. An Instagram operator or admin
  of one tenant must not receive those unrestricted global aggregates.

## Prototype components (not mounted or imported into the live app)

- `backend/app/instagram_incident_center_ci_api.py`: router **factory**
  which requires two explicitly injected dependencies: a server-verified,
  **recent MFA** current-user dependency and a database engine supplier.
  The module has no FastAPI startup hook, no real endpoint registration,
  no scheduler, no Meta calls and no connection to real staff identities.
- Both read and acknowledgment operations use the previously verified
  **exact GitHub CI PostgreSQL-only** gate before any database connection,
  including `127.0.0.1:55439`, `sendro_ig_ci`, user `sendro_ci`,
  CI approval flags and Instagram episode/dispatch/ack flags.
  Injecting a Render engine is denied before DB access.
- Reads and acknowledgments additionally require the
  authenticated current user to be enabled, `role='admin'`,
  MFA-enabled, and to have a still-valid **separate global responder
  grant** from the synthetic incident responder table.
  The gate is **server-side** and does not accept a client-provided
  actor ID, user ID or tenant ID. Invalid authentication does not
  reveal alerts.
- GET returns only a fixed set of generic issue codes, numeric
  episode/observation values, boolean active state and dispatch state.
  POST accepts only a strict exact episode and literal synthetic
  confirmation phrase, then invokes the CI-only transactional audited
  responder acknowledgment. Invalid state, actor, expired grant,
  redundant confirmation or unsupported fields are rejected.
- `frontend/src/instagramIncidentRows.js`: presentation adapter that
  rejects unexpected incident codes/states/versions and never spreads
  raw server JSON into the UI. An intentionally small cap of 20 rows
  is enforced.
- `frontend/src/InstagramIncidentCenterPreview.jsx` and CSS:
  responsive, presentational **NOT LIVE** panel. It makes **no HTTP
  requests**, accesses **no live user data**, starts **no timers**, and
  is **not imported/mounted from `App.jsx`**, `WorkspaceTabs.jsx`
  or `InstagramInboxPage.jsx`. The optional injected acknowledgment
  callback is therefore not wired to any production endpoint.
  There are no real operator notifications or read markers yet.

## CI coverage and explicit limitations

The new disposable-PostgreSQL HTTP tests use a separate synthetic
JWT signing key and the **real** `require_recent_mfa_token` helper.
They verify:
- a signed, recent MFA admin with a separate global responder grant
  sees redacted incident summary, and can acknowledge only after the
  fake dispatch has been marked transport-accepted;
- a legitimate admin without separate grant, operator, viewer,
  disabled user, admin without MFA, expired grant, developer, and a
  global-grant candidate scoped to a single tenant are DENIED;
- invalid/missing/stale MFA tokens are denied; bogus JWT signatures
  cannot read or acknowledge;
- nonexistent/old episode, duplicate review, incorrect confirmation,
  and unexpected PII fields are rejected;
- a successful test action stores the audited synthetic responder ID
  exactly once, without leaking names, message payloads or secrets;
- CI-only Render-lookalike/wrong database engine fails before queries;
  a code assertion confirms the router is **absent from `main.py`**.
- Browser-side pure JS tests validate only whitelisted display
  fields and role-independent redaction, and the CI job separately
  syntax-builds the dormant JSX component without app import.

**Test identity disclaimer:** The CI authentication stub maps fabricated
actor records from signed synthetic tokens. No live Sendro JWT, MFA device,
customer data or operator account was accessed. The role/MFA logic
is designed to match the current system, but full integration with the
actual production dependencies and a reviewed live ACL store remains
unfinished. Rendering the panel for a browser user by itself does not
authorize data access.

## What must be true before any real activation

1. Independently scoped and authorized private PostgreSQL incident
   storage/ACL design, including tenant-vs-global incident semantics,
   migration privileges, backed-up restore point, and Render owner-role
   resolution. No new shared-db table authorized now.
2. Wire through real `get_current_active_user` **and** the existing
   signed recent-MFA dependency on the backend. A frontend permission
   flag is not enough. Keep **global** incident visibility restricted
   to separately delegated responders, not all tenant operators.
3. Operationally supervised health sampling with durable alert
   persistence and real email/in-app delivery/ack escalation that
   survives worker crashes, without customer PII.
4. Product sign-off on placement (potentially bell in global header,
   or admin-only Incident Center tab), the named staffed responders,
   UX, throttling and re-review policy.
5. A fresh, explicit owner approval for any live DB schema/grant/env
   mutation, real Meta subscription, or incoming DM pilot.

**Non-goals:** No real Instagram receipt/reply, notification
subscription, webhooks, login change, production service restart, Render
DDL/DML, user entitlement change or promotion to `main` is performed
by this synthetic task. Staging auto-deploy may copy the unused files,
but the router remains unmounted and the panel unreachable.
