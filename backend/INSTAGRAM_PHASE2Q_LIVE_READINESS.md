# Phase 2Q — Instagram staging live-readiness audit (NO rollout)

**Audit date:** 2026-10-16. This document records read-only Render metadata
and a zero-network, zero-database-connection **configuration preflight**.
It is NOT approval to enable Meta subscriptions or process real guest DMs.

## Verified Render service topology (READ-ONLY)

Render workspace: Sendro (Frankfurt).

| Service | Render branch | Latest inspected LIVE deploy | Auto-deploy |
|---|---|---|---|
| `sendro-backend-staging` | `dev` | `e74e01fb1e05be3b111b2225893a83ca3cb95190` — PR #33, 2026-10-16 | **ON** |
| `sendro-frontend-staging` | `dev` | `201accc6dbfa082defcbbb8cb659f0b95a6bed64` (earlier UI commit) | **ON** |
| `sendro-backend` production | `main` | `0eb61c1e232d91fac6d10d52448d7799751444bb` | ON |
| `sendro-frontend` production | `main` | `f30168db31d3efe82af6c99880ef115ade572ec6` | ON |

**IMPORTANT:** Merging a PR to `dev` can trigger automatic Render staging
deployment without another click. An earlier statement that PR #33 had not
deployed was outdated: Render reports its staging backend deployment as LIVE.
This does **not** mean Instagram intake/worker is enabled. Production's
`main` branch is different, **but both backends share PostgreSQL**.

The staging frontend commit predates recent backend-only merges; its older
commit alone does not prove the frontend lacks the Instagram read-only UI.
A real authenticated UI check is still needed.

## Shared PostgreSQL queue snapshot

Using Render's built-in server-wrapped read-only SQL action, aggregate query
`SELECT processing_state, COUNT(*) ... WHERE provider='instagram' GROUP BY ...`
returned **zero rows across all states** at audit time. No payloads, tenants,
conversation IDs, customer IDs or contact data were selected. This is a
one-time snapshot, not monitoring or a guarantee of future queue emptiness.

Read-only schema/security audits Phases 2N and 2O previously found:
- Six Instagram SaaS tables and primary constraints match the reviewed
  SQL migration fixture manifest.
- No invalid indexes, invalid constraints, or custom triggers were found.
- No Row-Level Security policies are enabled on these tables.
- The app database owner has broad rights, and the Render database IP
  allowlist is `0.0.0.0/0`. Do not change permissions/network settings
  without inventorying WhatsApp production dependencies.

## What is NOT verifiable through available read-only Render metadata

The Render service/deploy inspection does **not** expose safe, verified
effective values for Instagram environment variables. Therefore do not
claim they are OFF based only on code defaults, prior operator intention,
or an empty queue. Likewise the real Meta App's Instagram Webhook
Subscription status, credentials validity, and backup restoration readiness
have **not been independently re-verified** in this phase.

## Operator-only offline preflight (not executed on Render)

A pure config inspector is available:

```bash
# Run only when authorized on the correct Render *staging* backend shell,
# never as a startup hook or on the production backend.
cd backend
python -m app.instagram_live_readiness
```

- Does **not import the database engine**, connect to Render/Postgres or
  Meta, start a worker, or alter the environment.
- Outputs only booleans and descriptive gate names in JSON, **never**
  app secrets, verification tokens, encryption keys, URLs or user data.
- Checks that `INSTAGRAM_WEBHOOK_INGESTION_ENABLED`,
  `INSTAGRAM_WORKER_MANUAL_ENABLED`,
  `INSTAGRAM_SUPERVISOR_TEST_ENABLED`,
  `INSTAGRAM_ISOLATED_DB_APPROVED`, and (since the 2026-10-21
  hardening) `INSTAGRAM_PILOT_ONE_DM_ENABLED` are all disabled.
  A one-DM pilot flag set to `true` must never be reported as safe
  standby, even while the separate manual worker gate is disabled.
- Checks presence (not live validity with Meta) of Instagram App Secret
  and separate verification token, plus syntactic validity of the
  encryption key without printing any secret values.
- Returns exit code **2** if any intake/worker/test gate isn't safely OFF;
  otherwise 0. Missing secret configuration is separately flagged even if
  safe standby is confirmed.
- **Always returns `pilot_ready: false`**: an offline config inspection
  cannot authorize real live subscriptions, worker execution or DB writes.

This utility is **not automatically run** by Render and cannot retroactively
confirm the true staging environment without an authorized operator run.

## Why the real DM test is still blocked

- Meta Instagram Webhook Subscription is **intended to remain OFF**.
  Turning it ON for `@sunsetoiasailing` may deliver other, real customer
  DMs immediately — not only the planned tester message.
- `instagram_supervision.py` remains a **SQLite-only prototype** and
  refuses PostgreSQL; no safe production-shared, supervised Instagram
  worker process, alert transport, recovery workflow or guaranteed
  event-type coverage is deployed.
- Inbound Inbox routes are read-only; **Instagram replies are not live**.
- No new backup/restore drill was performed or confirmed here.
- Render's auto-deploy ON requires deliberately avoiding unexpected merges
  to `dev` during operational trial windows.

## Next controlled step

Phase 2R should prepare a **bounded, fail-closed PostgreSQL-compatible
supervision strategy** with alerting, shutdown and event quarantine
semantics, and test the strategy only on disposable CI PostgreSQL.
Do not grant it live DB access without a fresh, explicit owner approval.
Use existing hosting where feasible; no second persistent paid DB required.

**No actions in Phase 2Q:** No new Render services, no paid database,
no staging or production configuration changes, no deployment trigger,
no migration, no real customer data reads, no Meta API calls,
no Instagram worker run, no Instagram webhook subscription.
