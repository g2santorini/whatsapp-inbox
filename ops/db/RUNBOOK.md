# Sendro PostgreSQL performance indexes — manual rollout only

**Status:** PREPARED / NOT EXECUTED. **Target:** the one database shared by Sendro staging and production. **Owner approval is required before executing any statement from the rollout SQL.**

## Why this exists

On 13 October 2026 a read-only inspection of the real PostgreSQL instance showed:

- 92,385 messages and 25,004 conversations, including 24,865 archived conversations (snapshot values; live totals will change).
- Only the messages primary-key/id indexes existed; no index on `messages.conversation_id` or `messages.whatsapp_message_id`.
- A filtered conversation lookup with `ORDER BY id DESC LIMIT 30` planned a sequential scan across `messages`, and WhatsApp message-id lookup did the same.
- Inbox queries filtered on `status <> 'archived'` and ordered by `updated_at DESC,id DESC`; the PostgreSQL plan scanned `conversations`.
- There are existing duplicate inbound WhatsApp message IDs. Therefore **do not** make the message-id index unique.

Index creation should speed common reads and reduce database work, not change the WhatsApp delivery logic or frontend polling.

## Files

1. `20261013_verify_performance_indexes.sql` — read-only baseline and post-change `EXPLAIN` checks.
2. `20261013_manual_performance_indexes.sql` — four non-unique, concurrently built B-tree indexes. Never imported by the running app.

## Before any execution

1. Get the owner's **explicit approval**, confirming that indexes will be created on the **production-shared database**. Deploying to `dev` alone does NOT create indexes, and executing SQL against staging would still affect production.
2. Confirm the intended DB hostname/database, role, environment, current indexes and absence of conflicting invalid index names. Do not copy credentials into chat, GitHub, or logs.
3. Take a fresh, verified Render PostgreSQL backup/snapshot and verify the restore method. Use a low-traffic period.
4. Save the output of the read-only verification script and the current response-time baseline. A planner estimate is **not** a measured latency improvement.
5. Confirm there are no conflicting long-running transactions or maintenance jobs.

## Execution (DB operator, only after approval)

- Open a direct PostgreSQL session in **autocommit** mode (for example `psql` without `--single-transaction`) to the shared instance. Execute the manual SQL file with stop-on-error enabled: `psql -v ON_ERROR_STOP=1 -f ops/db/20261013_manual_performance_indexes.sql`, after securely setting the connection details in the operator's own terminal.
- **Do not wrap the statements in `BEGIN` / `COMMIT`**: PostgreSQL does not allow `CREATE INDEX CONCURRENTLY` within a transaction block.
- `CONCURRENTLY` permits normal message writes while building indexes but is not free: it uses CPU/IO, can wait for transactions, and can fail. The script uses a short lock timeout to avoid waiting indefinitely.
- Stop immediately on any error. Never silently retry an `IF NOT EXISTS` index whose previous build left it `INVALID`.
- Do **not** launch the rollout from application startup, the GitHub CI workflow, or a Render deploy/build command.

## After execution

1. Re-run the read-only verification SQL. Confirm each index is present with `is_valid=true` AND `is_ready=true`.
2. Compare query plans and measure API performance (especially 30 most recent messages, incremental messages, conversation list, incoming-message lookup).
3. Smoke-test inbound and outbound WhatsApp, contact search, archived conversations, and the live companion panel. Keep polling at **5/15/15 seconds**.
4. Monitor latency, errors, database CPU/IO, connections and inbox behavior; stop before any further change if anything regresses.

## Failure or rollback

A failed concurrent build may leave an index entry with `indisvalid=false`. **Do not infer success from the index name alone.** After inspection and approval, a DB operator can remove an invalid new index with one top-level `DROP INDEX CONCURRENTLY IF EXISTS public.<new_index_name>` statement, then fix the cause before rebuilding. Do not drop legacy indexes.

If a validated new index causes an unexpected regression, dropping that *specific* new index concurrently is the reversible part of this change. Dropping an index does not delete guest data. A separate owner confirmation is required for production-impacting rollback as well.

## What is deliberately out of scope

- No changes to frontend polling frequency, WhatsApp webhook behavior, production code or existing data.
- No deduplication, unique constraints, table rewrite, or data cleanup.
- **Full-text/substring search is not fixed by these B-tree indexes**; `messages.content ILIKE '%...%'` still needs a separately reviewed `pg_trgm` extension + GIN index.
- No auto-migration; the existing `Base.metadata.create_all` is not a substitute for an explicit schema migration system. New instances will need the manual index migration as well.
