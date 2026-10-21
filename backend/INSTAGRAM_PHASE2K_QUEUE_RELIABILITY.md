# Instagram Phase 2K-A — Dormant Retry Backoff & Read-Only Queue Health

## Deployment / safety posture

- The code in this PR is **not** an auto-running worker.
- No scheduler, cron, external alert destination or FastAPI startup hooks.
- No database migration. Existing Instagram queue columns `attempts`,
  `next_attempt_at`, `last_error_code`, `processed_at`, `processing_state`
  are reused; PostgreSQL schema must be independently inspected before any
  operational rollout.
- **Never enable Meta Instagram Webhook Subscription** or ingestion flags
  as part of this PR. Sendro staging and production share PostgreSQL.
- Nothing touches WhatsApp handlers, tables or the production main branch.
- All tests use **in-memory SQLite**, no real guest DMs or Meta tokens.

## What Phase 2K-A adds

1. Worker SELECT skips deferred pending deliveries with a future
   `next_attempt_at`. A pending delivery with NULL or past due is eligible.
2. Pure deterministic exponential retry delays (30s, 60s, 120s, ...)
   capped at one hour; maximum configured retry attempts defaults to five.
3. **Dormant** `schedule_transient_retry(engine, delivery_id,
   expected_attempts, now=...)`: atomically CAS-updates only an Instagram
   row that is still pending with the expected attempt count. On final
   failure it marks `failed`, otherwise leaves `pending` with a later
   `next_attempt_at`. It stores only generic error codes, never payloads.
4. Read-only `read_instagram_queue_health` reports aggregate state counts,
   due vs deferred, oldest due age and machine-readable alert codes. It
   also flags any **committed `processing` row** as
   `unresolved_processing_delivery`: the implemented worker commits
   pending directly to processed/quarantined in one transaction, so an
   orphan processing state is ineligible for work and must not silently
   disappear from queue monitoring. This alert reports aggregates only;
   no automatic state reset or recovery is performed. No customer
   identifiers, payloads, raw messages or tokens are returned.
5. Optional read-only operator CLI:
   `python -m app.instagram_queue_reliability`

## Explicit non-goals (not yet live-ready)

- **No automatic retry invocation.** This is a building block, NOT a live
  retry loop. It must only be called after a transaction has rolled back,
  for a known/locked delivery ID and attempts count, and only for a
  classified transient exception. Cryptographic/configuration failures,
  unknown accounts and unsupported events are not transient retries.
- No reliable supervised process, leader election, process restart or
  controlled runner for persistent retries yet.
- No PostgreSQL concurrent-worker validation or synthetic tests on an
  isolated PostgreSQL instance yet; SQLite is insufficient to prove
  concurrent `FOR UPDATE SKIP LOCKED` behavior.
- No integration with an actual alert transport or operator escalation.
  The alert codes are read-only indicators, not notifications.
- Quarantined / failed deliveries require explicit, reviewed recovery;
  never silently reset or delete them.
- Meta's genuine payload shape and message/event subscription behavior
  for Sendro-IG still require a separately approved live test.

## Deployment gates before enabling real Instagram webhook traffic

1. Isolated PostgreSQL test database, verified migration/schema, backup,
   workers' concurrency and transaction rollback tests.
2. Explicitly gated, supervised worker runner with durable scheduling,
   retries, jitter and failure-classification rules; alerts integrated and
   validated to a real operator destination.
3. Explicit retention, secure credential handling and quarantine/recovery
   runbooks. Demonstrate that actual inbound DMs are not acknowledged until
   durably stored and subsequently retried or alerted if processing fails.
4. Confirm real Instagram Login envelope in a safely isolated test setup.
5. Separately authorize production account testing and Meta webhook
   subscription; never switch on the shared staging DB as an experiment.

## Operator validation now

- GitHub Actions tests are sufficient for this code stage.
- Keep `INSTAGRAM_WEBHOOK_INGESTION_ENABLED` unset/false and
  `INSTAGRAM_WORKER_MANUAL_ENABLED` unset/false.
- The pre-existing `python -m app.instagram_worker_control` is status-only
  by default; the optional new queue health CLI is also read-only.
- **Do not** call `schedule_transient_retry` against Render PostgreSQL
  or manually run a queued delivery yet.
