# Instagram Incident Center: real Sendro authentication regression in disposable CI

**Date 2026-10-21. Test-only.** No production/staging database
connection, real staff login, Render env change, Meta webhook, live notification,
actual Instagram DM, new service, API mount or production promotion.

## What this phase verifies

PR #76 built an unmounted Incident Center API in which **fabricated CI JWT
users** were authenticated using the real existing recent-MFA helper,
but the login-to-user look-up was simulated with a simple mapping.

The follow-up `backend/tests/test_instagram_actual_sendro_auth_chain_ci.py`
executes the **exact original function bodies** of
`get_current_user` and `get_current_active_user` from
`backend/app/main.py`, rather than reimplementing those decisions.
An AST extractor compiles **only these two async functions**, deliberately
never importing or initializing `main.py` (which executes database setup
at import). Surrounding dependency names, JWT signing key and database
look-up are injected with synthetic/test-only values.

The test constructs two isolated resources:
- an in-memory SQLite **mock users table** holding synthetic role,
  disabled status, MFA setup, password-change and `auth_version` fields;
- the pre-existing **ephemeral GitHub Actions PostgreSQL 16**
  `127.0.0.1:55439/sendro_ig_ci` for CI-only Incident Center episode,
  dispatch, responder grant and audit fixtures. The mandatory DB URL/
  opt-in allowlist still blocks any Render database.

A FastAPI `TestClient` composes the exact original Sendro
`get_current_user` then `get_current_active_user` functions with the
existing `privacy_mfa_session.require_recent_mfa_token` and the unmounted
PR #76 Incident Center factory. Synthetic JWT signatures/claims and a
fake `get_user` lookup are the **only** replacements. This tests the
actual authentication decisions without invoking the live server.

## Expected denial proofs

- A properly signed synthetic admin JWT with a recent MFA claim
  succeeds **only** if that database user also has a separately
  delegated global incident-responder grant.
- A legitimate `admin` without a grant is denied.
- Forged `role='admin'` inside a valid test JWT **cannot** elevate a
  SQLite-registered `operator` who has a responder grant.
- Incrementing `auth_version` on the synthetic user instantly
  invalidates a previously valid JWT for reads and acknowledgments.
- Demoting admin to operator in the database immediately denies access
  even while the token remains cryptographically valid; deactivated
  accounts are rejected.
- Original Sendro active-user gates reject a required password change,
  absent authenticator setup and project-only roles.
- Missing/expired recent MFA or invalid JWT denies both operations.
- After a synthetic notification is separately transport-accepted,
  a delegated admin can acknowledge its **exact episode** once,
  with the pre-existing CI-only audit, never an unaccepted incident.

## Limitations / rollout STOP

This is an **auth-function source regression**, not live application
integration: the real `main.py` module is deliberately not imported,
no actual persistent Sendro user accounts or Render credentials are read,
the SQLite user lookup is synthetic, and the real Incident Center router
remains **unmounted**. The test can detect source behavior drift but
cannot replace staging end-to-end authentication testing.

No real delivery of notifications to operators or independent automatic
watchdog/cron is active; prior PRs #71-#76 are all isolated rehearsals.
CI-only responder grants and audit tables are not an approved live data
model. In particular, **global** Instagram queue-health incidents must
never be visible to ordinary tenant-scoped Instagram Inbox operators.

Before any activation, perform a separately approved design/backup/
independent-role security review, bind the *already existing production*
authentication and signed MFA dependencies to a reviewed, tenant-safe
Incident Center, implement reliable supervised poll/alert delivery,
and obtain an explicit approval for the exact migration and one-DM pilot.
Do not mount the CI router, configure CI flags in Render, or create real
schema objects by copying test fixtures.
