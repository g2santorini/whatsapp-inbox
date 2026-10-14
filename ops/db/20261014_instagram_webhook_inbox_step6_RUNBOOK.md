# Sendro Instagram Webhook Inbox — DB Step 6 (manual)

**Prepared, NOT applied automatically.** Staging and production share one live PostgreSQL database. The owner has taken a backup for the current migration series; verify it remains recoverable before operating. Never put credentials or guest messages in GitHub or chats.

## Prerequisites

1. Database is `sendro`; tenant `1` has slug `sunset-oia` and exactly **13** members.
2. `sendro_channel_accounts`, `sendro_channel_conversations`, and `sendro_channel_messages` are present and **empty**.
3. `sendro_channel_webhook_deliveries` **does not** exist.
4. Existing WhatsApp is operational and a backup is available.

## What it creates

One empty internal webhook inbox table with **10 columns**:
- `provider`, `raw_body_sha256` dedupe exact re-deliveries, unique together.
- `payload_ciphertext BYTEA` holds ciphertext **only**. The future app must verify the exact Meta HMAC-signed body and encrypt it with a dedicated Fernet key provided via secure backend environment settings **before** a DB insert. Never store plaintext or secrets.
- `processing_state`, `attempts`, `last_error_code`, `next_attempt_at`, `processed_at` enable safe retries/quarantine.
- `received_at` and `id` record ordering and arrival.
- Partial work-queue index covers pending and failed notifications.

One incoming envelope can include Instagram events for several business IDs, including unknown IDs, so this *envelope* is not assigned to a tenant. The future **worker** must split it, resolve and validate each business account, and enforce channel+tenant isolation for every conversation/message. The encrypted global inbox must never be queryable from tenant-facing API endpoints. Have a documented retention/delete policy before real use.

The table by itself cannot receive Instagram webhooks. The current POST route still returns 503 after HMAC validation. Future implementation must commit encrypted payload transactionally before returning 200, use deduplication and idempotent workers, rate and payload limits, retry/backoff, observability, and tests against the actual Instagram Login webhook schema.

## Manual execution

Run `20261014_instagram_webhook_inbox_step6.sql` once in a single transaction with short lock timeout. Do **not** trigger from the app, CI or Render auto-deploy.

Postflight should report **10 columns, 0 rows**, plus unique(provider, raw_body_sha256) and a partial work index. Stop on error; do not use IF NOT EXISTS to mask drift.

## What is deliberately unchanged

- No WhatsApp tables, status, polling, or webhooks touched.
- No Meta publish, Instagram webhook subscription or real DM processing.
- No Instagram app/access tokens saved, and no extra Render environment secrets are required until we build encrypted ingestion.
- No rollback or table drops without separate approval.
