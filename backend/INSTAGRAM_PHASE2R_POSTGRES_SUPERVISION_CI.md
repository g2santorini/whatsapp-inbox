# Sendro Phase 2R — PostgreSQL Instagram supervision, isolated CI rehearsal

## Intent

Safely rehearse how an Instagram background worker will eventually process
encrypted webhooks in PostgreSQL **without provisioning a second paid database
and without using the existing shared production PostgreSQL for test writes**.

The Phase 2P synthetic end-to-end flow passed, while Phase 2Q confirmed the
staging backend tracks `dev` with **auto-deploy ON** and shares its database
with live WhatsApp traffic. Phase 2R must therefore be inert after staging
deployment and must *not* be an accidental Instagram production worker.

## What was built

`backend/app/instagram_postgres_supervision.py` exposes a **library-only,
CI-only** bounded runner `run_ephemeral_postgres_supervised_batch()`.

**No CLI, scheduler, FastAPI route/startup hook, Render worker, Meta network
request, deployed alert service, live data inspection, or schema change.**

Before ANY database connection, it checks all of:
- `GITHUB_ACTIONS=true`
- `SENDRO_INSTAGRAM_PG_CI_APPROVAL=ephemeral-local-service-only`
- `INSTAGRAM_PG_SUPERVISION_CI_ENABLED=true` explicitly supplied in
  the synthetic test's flags (not a Render environment setting)
- SQLAlchemy PostgreSQL engine pointed at exactly `127.0.0.1:55439`,
  user `sendro_ci`, database `sendro_ig_ci`
- a nonempty in-memory test key, callable alert test callback, and
  bounded batch size (1–5).

Other PostgreSQL URLs, Render hosts and all SQLite engines are rejected.
Even someone setting a flag on the actual Render backend would **not**
enable this runner: its DB identity checks reject Render PostgreSQL.

Only after the guard succeeds does it:
- Call the already-tested transactional Instagram delivery worker with
  `FOR UPDATE SKIP LOCKED`, atomic message creation and idempotency.
- On specifically classified transient PostgreSQL failures, schedule the
  next attempt **after transaction rollback** with compare-and-swap;
  exponential backoff and final failed state already exist.
- Halt on unknown errors, retry conflicts, missing queue health or a failed
  alert test callback, without echoing raw exceptions or payloads.
- Return only counters and generic alert codes, and call a **test-only,
  in-process callback** on failed/quarantined/stale queue status.

A callback is **not durable alert delivery**. It can fail after a database
commit; this currently raises a sanitized error but does not guarantee an
operator receives the alert. Production-safe alert transport, supervisor
crash recovery and worker runtime remain unsolved.

## CI testing

The existing disposable PostgreSQL 16 GitHub Actions service automatically
replays pinned original SQL migrations 1–6 and then runs the Phase 2R tests
using fabricated Instagram sender/business IDs and generated Fernet keys.

Coverage:
- Refuse an unapproved CI gate, mismatched engine/host/port/database,
  a missing alert callback, or excessive batch size.
- Process exactly a bounded number of deliveries, dedupe provider IDs and
  preserve unread counters.
- Quarantine unknown businesses and report only aggregate health alerts.
- Inject a genuine PostgreSQL `40001` serialization failure via a
  CI-only trigger; prove transactional rollback, post-rollback CAS retry
  scheduling, backoff and subsequent successful processing.
- Fail closed if a test alert callback raises, preserving committed
  quarantine evidence.
- Halt if the encryption key cannot decrypt the payload rather than
  acknowledging or partially writing a message.
- Detect and report a synthetic committed `processing` row that is
  invisible to the pending-only worker, without modifying its state,
  processing another delivery or revealing any customer identifiers.
  This is a redacted **in-process test alert**, not a durable production
  notification or an automatic recovery.
- Preserve previous Phase 2L/2M/2N/2P suites.

The tests' synthetic TRUNCATEs and trigger CREATE/DROP **only** occur after
the previous Phase 2L/2M exact CI-URL environment gate has approved that
disposable database; there are no Render database connections.

## Remaining gates before any real Instagram DM

1. Verify real staging environment values using separately authorized
   sanitized Phase 2Q manual preflight; do not print secrets.
2. Verify current Meta Instagram app subscription state independently;
   expect subscription OFF. Enabling it may deliver genuine customer DMs,
   not just an individual test DM.
3. Design a truly production-safe, **separately gated PostgreSQL worker**
   with reliable operator alert delivery, capacity limits and a kill switch;
   this Phase 2R CI-only runner cannot be deployed as that worker.
4. Confirm backup/restore, tenant enrollment and routing, quarantine/
   unsupported event disposition and unexpected incoming DM recovery.
5. Get **fresh, separate owner approval** before any change to live Meta
   subscriptions, Render environment variables, Instagram queue records or
   the production-shared PostgreSQL.

**No change to** WhatsApp, `main`, real DB, Render, Meta subscription,
`INSTAGRAM_WEBHOOK_INGESTION_ENABLED` or
`INSTAGRAM_WORKER_MANUAL_ENABLED`. No new recurring costs.

This PR is intended only for review and merge into `dev` with owner
approval, noting that `dev` auto-deploys to Render staging.
