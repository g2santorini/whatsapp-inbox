# Instagram Phase 2M — Original Manual SQL Replay in Isolated CI

## Discovery (important)

The actual **operator-authored PostgreSQL SQL scripts** for Sendro Instagram
database steps 1–6 live in open **unmerged** PRs #12–#17. They are not
present on the `dev` branch, despite the Instagram backend code relying on
the new tables. The scripts may have been run manually in a shared database,
but **this PR does not connect to or inspect that database**; the applied
live schema, migration history and drift remain **unverified**.

To permit offline migration replay, this PR copies the six scripts byte-for-
byte into `backend/tests/fixtures/instagram_migrations/step1.sql` through
`step6.sql`. These are **pinned snapshots of unmerged manual SQL**, not
new production migrations. This PR **must not merge or auto-execute them
through application startup or Render**.

| Script snapshot | Originating unmerged PR | Source blob SHA |
|---|---|---|
| step1.sql | #12 | `5463d2cc26493fedd988666a571bc97f9079ddb7` |
| step2.sql | #13 | `b09d391f47c83f0f1aac6e1fdee4befc2625e573` |
| step3.sql | #14 | `49f6187ee89c47881b8cd13a7348b12117d652da` |
| step4.sql | #15 | `16f60366313615366265370c6a77bfea4a620d1e` |
| step5.sql | #16 | `d32ddb378757f6dea9d582da10a543be15797f55` |
| step6.sql | #17 | `960cae77b0c7e784c5a33c0359117fd87685c699` |

## Differences from previous Phase 2L schema

- The manually authored Step 6 `sendro_channel_webhook_deliveries` has
  a **CHECK constraint restricting provider to `instagram`**, whereas
  Phase 2L's simplified schema allowed inserting a `whatsapp` provider
  record to test filtering. The actual queue must reject that insert.
- Full schema includes composite tenant/account/conversation foreign keys,
  status/body constraints, index definitions, `BIGINT ... IDENTITY`,
  and other production-like types absent from the minimal Phase 2L fixture.
- `public.users` is an existing Sendro app table required by step2. The
  ephemeral job creates a one-column stub `users(id)` strictly to satisfy
  that foreign key — no users are inserted.

## New CI tests

The PostgreSQL GitHub Actions job starts a disposable PostgreSQL 16 service
and first runs Phase 2L. Then a second pytest invocation drops the **CI-only
tables**, replays original six scripts **in order** including their explicit
BEGIN/COMMIT, and verifies:
- All six new tables and tenant-scoped FK constraints exist.
- The Step 6 inbox rejects an attempt to insert a WhatsApp delivery.
- The *existing application code* stores encrypted synthetic Instagram DMs,
  processes JSONB media and text, respects deduplication, and counts unread
  correctly **against replayed SQL**.
- Composite FK isolation prevents a channel account from being used under
  another tenant.
- Retry CAS/backoff and queue health queries operate against the replayed
  `next_attempt_at`, status and attempts columns.

All database access is guarded *before connection*, requiring exact
`GITHUB_ACTIONS` / approval env + localhost port `55439`, database
`sendro_ig_ci`, user `sendro_ci`. Nothing is connected to Render.

## Known remaining gates before live Instagram customer traffic

1. Read-only verification of the **actually applied** shared database schema
   and a signed-off schema drift report, without writing any data.
2. Reconcile six manual SQL PR branches with `dev` migration tracking,
   including non-automatic manual-only provenance. Never execute the DDL on
   the shared DB without independent backups and owner approval.
3. Separate, isolated end-to-end environment with the intended app schema,
   supervisors, queue retention, secure config and verified alert transport.
4. A genuine, safely captured Meta Instagram Login event to validate event
   shapes and webhook subscription fields. Unsupported events need handling.
5. Explicit later consent for live test and webhook subscription. Until then:
   `INSTAGRAM_WEBHOOK_INGESTION_ENABLED=OFF`,
   `INSTAGRAM_WORKER_MANUAL_ENABLED=OFF`,
   **Instagram Webhook Subscription OFF**.

Production `main` / WhatsApp backend remain unchanged.
