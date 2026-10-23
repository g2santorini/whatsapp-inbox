# Bulk-send delivery-history retention — offline preview (October 23, 2026)

**Owner decision: Ordinary retention of `template_batch_items` is limited to 12 calendar months from each item's `created_at`.**

The history is used **only** to see whether a message was sent and delivered. It is **not** the booking ledger, a billing archive or a legal recordkeeping system. A later delivery/read/status event **must not restart the 12-month clock**.

## What this PR implements (and what it does not)

`app/privacy_batch_delivery_retention.py` is an offline, pure classifier for fabricated `DeliveryHistoryRetentionSnapshot` records. It:
- evaluates 12 **calendar months** rather than a fixed number of days;
- uses the send-history **creation timestamp**, NOT the most recent delivery status;
- treats malformed timestamps, missing hold checks, ownership/controller instructions, related rows and backup plans as fail-closed blockers;
- yields **reason codes and anonymous aggregate counts only**;
- never reads a real database, returns a record ID, changes a record, schedules a job or makes a request.

Unit tests use only fabricated records in CI. The code has **no router mount, worker, integration with Sendro app startup, environment variable, CLI, live query or erasure action**.

## Checked live metadata (read-only, October 23, 2026)

- `template_batch_items`: **27,343** entries, earliest `created_at` date **May 6, 2026**, latest **October 23, 2026**;
- items more than 12 months old at last status: **0**; since earliest creation was May 2026, items created before the present 12-month cutoff are also **0**;
- `template_batch_items` unlinked to any `conversations` or `messages`: **1,543**;
- the entry has `created_at` and optional `whatsapp_status_updated_at`, but no `updated_at` column.

These are aggregate counts, no guest identifiers/messages were accessed. Live staging and production use a **shared database**.

## Step 2: disposable PostgreSQL transaction rehearsal (same PR)

In addition to the pure 12-month classifier, `backend/tests/test_privacy_batch_delivery_postgres_ci.py` models the database's actual **foreign-key direction** on fabricated `template_batch_items`, `template_batches`, `messages` and `conversations`. GitHub Actions starts its **own** short-lived PostgreSQL 16 container at `127.0.0.1:55443/sendro_batch_retention_ci` with a purpose-specific user. A strict allowlist validates host, user, database, port and CI-only approval string **before creating the engine**. It will refuse the shared Render database.

The synthetic-only `ci_verified_batch_scope` table is **invented for tests and does not exist in production**. This makes explicit an unresolved critical dependency: the old WhatsApp batch history cannot yet be safely attributed to tenants. The test never claims its simulated verification establishes real tenant ownership.

The rehearsal uses explicit one-item `DELETE … RETURNING` queries **inside disposable PostgreSQL transactions that are always rolled back**, and verifies:

1. A 12-month-old authorised item is removable even if its delivery-status timestamp is much newer;
2. younger items, other businesses' items, unknown ownership, and legal holds cannot be selected;
3. expiry exactly at the UTC calendar-month boundary;
4. linked messages/conversations and a younger sibling survive deletion of the older history record;
5. parent `template_batches` remain untouched — actual safe orphan-parent disposal is still an unresolved separate step;
6. a simulated failure rolls back the transaction, leaving aggregate row counts unchanged;
7. no application router, worker, live script or release-time migration is added.

**This is NOT production erasure, a production-valid SQL deletion procedure, or authorisation to run SQL on Sendro.** It is evidence that simple child-row deletion *can* preserve selected foreign keys under a designed set of checks. The full schema, legal hold evidence, parent contents, actual ownership and backup process must still be validated before any live cleanup.

## Outstanding implementation gates for real batch erasure

1. Review `template_batch_items`, `template_batches`, `conversations`, `messages` references and any storage outside Postgres. Old UI conversation DELETE currently only nulls links to the batch, **not** the batch's personal fields. Ensure that erasing old batch metadata cannot erase younger linked conversations/messages or unexpectedly break existing Sendro reads.
2. Establish authoritative tenant/controller scope for older legacy WhatsApp records. There is **no independently verified direct tenant ID** on those legacy conversation rows. A simple age filter on a shared multi-customer DB is not authorisation.
3. Verify per-item `created_at` interpretation (creation when send attempt/status row recorded), clock skew, statuses and partial batches. For normal history, a status event does **not** reset the 12-month limit.
4. Define treatment of `template_batches` parent rows that become empty; aggregated labels may still have identifying or operational metadata. Define any strictly lawful exception/hold and minimum encrypted audit metadata.
5. Use only **redacted, aggregate dry-run** queries after separate approval; do not dump customer content to logs.
6. Independently test expiration and deletion against **disposable PostgreSQL** with synthetic data, including foreign keys, transactions, batch sizes, rollback, concurrent WhatsApp callbacks and restore.
7. Obtain owner/controller explicit authorization for production erasure, checked fresh backup and rollback evidence; then roll out a small, supervised, non-destructive rehearsal. Production changes must be separately approved.
8. Build monitoring and verification of regular scheduled cleanup, plus restore-specific reapplication of valid deletions and deletion/expiry of downloaded backups according to verified policy.
9. Update Sendro Privacy Policy **only after** active retention enforcement is objectively confirmed and legal counsel reviews the factual statement. The 12-month policy is a **target today, not an operational promise**.

**No production deletion is implemented, approved or invoked by this PR.**
