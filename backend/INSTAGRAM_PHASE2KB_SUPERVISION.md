# Sendro Instagram Phase 2K-B — Supervision prototype (2026-10-15)

## Current status

**TEST-ONLY PROTOTYPE. NOT A PRODUCTION SUPERVISED SERVICE.**

Nothing in this PR starts a process, registers a cron, adds a Render worker,
changes the shared PostgreSQL or subscribes Meta's webhooks.

The `run_isolated_supervised_batch` entrypoint in
`backend/app/instagram_supervision.py` is a **library function**, not CLI.
It rejects operation unless ALL conditions hold:
- `INSTAGRAM_SUPERVISOR_TEST_ENABLED=true` supplied to the function;
- `INSTAGRAM_ISOLATED_DB_APPROVED=true` supplied to the function;
- SQLAlchemy engine is **SQLite only** (PostgreSQL, including staging's
  shared-production PostgreSQL, cannot be processed);
- a valid encryption key and operational `on_alert` callback are supplied;
- requested batch count is between 1 and 25.

Never set these test flags on Render. They exist solely for local/CI tests.

## What this prototype proves

1. The existing worker's transaction rolls back before a recoverable
   database error becomes a redacted, ID-scoped retry signal.
2. The retry classifier only recognizes a lost DB connection, PostgreSQL
   SQLSTATE class 08 (connection exception), 40001 (serialization failure),
   40P01 (deadlock), 55P03 (lock-not-available).
   Programming/schema errors, malformed events, decrypt failures, unknown
   accounts and unexpected failures are *not* auto-retried.
3. The CAS retry scheduler from Phase 2K-A applies a bounded backoff to
   that specific pending Instagram delivery. Failed scheduling **aborts**
   rather than acknowledging success. After 5 attempts the row is terminal.
4. A bounded loop can process/quarantine multiple deliveries. Duplicate
   provider IDs and queue-lock isolation remain covered in existing tests.
5. Read-only queue-health aggregates are emitted to an **injected test
   callback**; no guest messages, phone numbers, tokens, URLs or tenant IDs
   are included. A callback exception aborts the batch.

## Explicit limitations

- **There is NO actual Render supervisor/background worker process.**
  No monitoring process, restarts, heartbeats or operational deployment.
- **There is NO real alert delivery integration yet.** The test callback
  is a contract, not working Email/Slack/Telegram alerts. Do not claim live
  notifications have been enabled.
- No schema changes and no genuine PostgreSQL worker/concurrency tests;
  SQLite cannot establish safe PostgreSQL row-lock behavior.
- No recovery policy for permanently failed/quarantined batches, and no
  message-retention/cleanup process.
- Real Instagram event formats and all subscribed event types must be
  validated in a separate isolated pipeline before enabling Meta callbacks.
- The current `schedule_transient_retry` helper intentionally has no
  public API; do not call it manually on Render's shared PostgreSQL.

## Next acceptance gates (separate approval / PR)

1. Provision **fully separate** staging/test PostgreSQL, not the shared
   production DB; review actual schema, indices, and migration state.
2. Integration tests for PostgreSQL concurrent workers, crash recovery,
   lock/transaction semantics and failure-injection.
3. Add a restricted service account and a genuine supervised Render worker,
   with startup kill switches and alert transport + operator acknowledgement
   and escalation. Explicitly test email/notification delivery.
4. Define unsupported-event handling, encrypted payload retention and
   reprocessing/incident runbook; run a controlled Meta account test.
5. Only after all gates and **separate user approval**, consider activating
   Instagram webhook subscription. Until then keep it OFF.

## Forbidden production side effects

- No modification to `main`, WhatsApp messages, routes, tokens or workers.
- No live Instagram API calls or token upload to GitHub.
- No writes to the Render staging / production shared PostgreSQL.
- No enabling `INSTAGRAM_WEBHOOK_INGESTION_ENABLED` or
  `INSTAGRAM_WORKER_MANUAL_ENABLED`.
