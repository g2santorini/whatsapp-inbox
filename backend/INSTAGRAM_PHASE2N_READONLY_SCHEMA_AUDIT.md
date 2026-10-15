# Sendro Instagram Phase 2N — Read-Only Schema Drift Audit

## Purpose and boundary

This PR prepares **metadata-only**, **read-only** schema comparison for
the six Instagram SaaS tables in Sendro's operator-authored PostgreSQL
migrations (the pinned steps 1–6 from PRs #12–#17).

**No connection to Render or the shared staging/production database was made.**
This PR does not contain credentials, a database URL, CLI, startup hook,
migration executor, background job or production deployment.

## New audit module

`backend/app/instagram_schema_audit.py` provides:

- `INSTAGRAM_CATALOG_SQL`: one fixed SELECT-only query against **pg_catalog**,
  constrained to exactly the six `public.sendro_*` tables. It retrieves
  **only definitions of tables, columns, constraints and indexes**. It does
  not inspect table rows, message text, tenant members, DMs, Fernet ciphertext,
  contact identifiers, tokens, DB sessions or secret values.
- `read_catalog_only(connection)`: read-only SELECT via an **already-open**
  connection supplied by the caller. It never opens its own connection.
  Any future real database caller must first be explicitly authorized and
  enforce a least-privilege role and **server-side read-only transaction**.
- `compare_instagram_catalog_rows(rows)`: deterministic, **offline** drift
  comparison against a reviewed manifest of expected column names/types/
  nullability and required named keys, checks, and explicit indexes.
  Critical tenant-scope FK, uniqueness and Instagram-only queue constraints
  additionally have definition-fragment checks.
- Output is only schema names and generic drift codes; no constraint
  definitions, database rows, credentials or user content appear in reports.

The manifest covers core structural compatibility, not every possible
semantic difference (e.g. some index expressions, default values, RLS policy,
grants or trigger definitions). A `compatible` report is **NOT** a go-live
authorization; it is one technical prerequisite.

## Testing in isolated GitHub Actions

The Phase 2L/2M GitHub Actions PostgreSQL 16 service still uses a disposable
localhost-only database `sendro_ig_ci`, port 55439, with the strict
`GITHUB_ACTIONS` / independent CI approval guard. Nothing can use Render.

1. Replay the six pinned SQL migrations in the ephemeral database.
2. For the Phase 2N audit, start a transaction and execute
   `SET TRANSACTION READ ONLY` **before** any catalog SELECT.
3. Verify the six-table schema returns no drift.
4. Test that the server itself refuses a write inside the read-only
   transaction.
5. Tamper with **in-memory metadata snapshots**, not live DB data:
   missing table, wrong tenant FK definition, changed Instagram-only provider
   check, missing index, wrong media JSONB column type, extra column and
   out-of-scope metadata. Confirm these report drift/fail closed.

## Proposed future operator procedure (NOT EXECUTED)

To inspect the real shared PostgreSQL, request **separate approval** after
confirming actual instance identity, backups and least-privilege access.
Use a dedicated role with read access to **schema metadata only**; do not
use the app's broad writer credentials. Run the fixed `INSTAGRAM_CATALOG_SQL`
inside a server-enforced read-only transaction. Review/report sanitized
schema metadata only; avoid customer table SELECT, row counts, DM contents,
secret material and production data manipulation.

If the actual schema differs, **stop and review**. Do not apply migrations,
repair schema, grant privileges, deploy workers or enable Meta webhook
subscriptions automatically.

## Remaining launch gates

- Inspect *actual applied* production-shared database schema with explicit
  authorization; only this proves the Render instance matches.
- Verify privileges, constraints (including the remaining non-critical
  definitions), index expressions, RLS/grants, actual migration provenance,
  and differences to our six unmerged SQL branch source files.
- Prepare truly isolated ongoing PostgreSQL environment with supervised
  worker process, durable alerts and replay/retention controls.
- Verify genuine Instagram Login webhooks and choose subscriptions/handling.
- Require separate user approval before live testing on `@sunsetoiasailing`.

**Always keep** Instagram Webhook Subscription OFF,
`INSTAGRAM_WEBHOOK_INGESTION_ENABLED=OFF`,
`INSTAGRAM_WORKER_MANUAL_ENABLED=OFF`.
No Render data operations, production `main` changes or WhatsApp edits.
