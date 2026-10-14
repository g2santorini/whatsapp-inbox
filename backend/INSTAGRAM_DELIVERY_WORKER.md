# Instagram Phase 2D — Transactional message worker (no scheduled execution)

## Status

This work is **code and tests only**. It runs no background job,
installs no cron service, and does not attach a worker to FastAPI startup.
Instagram webhook POST remains feature-gated and disabled by default.
The Meta subscription remains OFF. There is no production `main` release.

## Processing design

`backend/app/instagram_delivery_worker.py` exposes
`process_one_pending_instagram_delivery(engine, encryption_key)`.

In **one database transaction** it:

1. Locks one pending encrypted Instagram delivery using PostgreSQL
   `FOR UPDATE SKIP LOCKED`; multiple future workers won't claim the same
   delivery simultaneously.
2. Decrypts the exact stored body with the dedicated Fernet key.
3. Validates every `entry[].messaging[]` item using the existing strict
   Instagram event normalizer before any message insert.
4. Looks up *every* business account ID by its stored Instagram business ID,
   restricting to approved `testing`/`active` channel accounts.
   Unknown accounts (or unsupported events) quarantine the **whole** encrypted
   delivery with a generic error code; no PII is written to logs or error
   metadata, no partial message is created.
5. Creates account/customer conversations and inserts inbound/echo messages
   idempotently on `(channel_account_id, provider_message_id)` unique key.
   Only newly inserted inbound messages increase `unread_count`.
6. Marks delivery `processed` in the same transaction. An unexpected DB
   exception rolls back all changes (including delivery state) for safe retry.

A customer ID can appear on two Instagram business accounts without leaking
between tenants. An outbound echo never increments unread count.

## Not yet ready for real customer traffic

- No actual Instagram Login webhook samples from Meta have been confirmed
  against the normalizer yet. Real events may include unsends, reactions,
  delivery receipts, stories, or different media structures.
- Current worker is **not started/scheduled**, and must never be invoked from
  a request thread. Real ingestion should stay disabled until continuous
  reliable background processing and operator alerting are available.
- No Instagram account has been registered in `sendro_channel_accounts`
  (this requires the true Instagram business ID, not Meta App ID).
- Tenant-aware authenticated APIs, frontend Inbox integration, actual Send API
  replies, token storage, long-term encrypted delivery retention/cleanup
  and advanced Meta permissions are pending.
- Reprocessing quarantined events after onboarding requires a manual,
  separately reviewed procedure. Nothing is silently discarded.
- Never publish the Meta app or enable webhook subscription yet.

## Testing

`backend/tests/test_instagram_delivery_worker.py` uses synthetic Instagram
events in isolated SQLite databases. Tests cover multi-message batches,
business isolation across tenants, deduplication, outbound echoes, media
metadata, quarantining of unknown/unsupported events, wrong decryption key,
and atomic DB error rollback. This does not establish performance or
PostgreSQL concurrency guarantees under production load; perform separate
integration tests before enabling the live webhook subscription.

No production DB data migration or WhatsApp code change is part of this PR.
