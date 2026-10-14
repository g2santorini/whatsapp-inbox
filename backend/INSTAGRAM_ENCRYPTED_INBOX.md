# Instagram webhook inbox — encrypted storage (Phase 2C, 2026-10-14)

## Scope and safety gates

This code is only on the Sendro `dev` branch/staging. It does **not**
subscribe Instagram webhooks, publish the Meta application, read/send
Instagram DMs, update the Inbox UI, or modify legacy WhatsApp behavior.
Staging and production **share the same PostgreSQL database**.

The webhook endpoint `POST /webhook/instagram` still returns **503** by
default after validating a Meta HMAC-SHA256 signature. **DO NOT enable**
`INSTAGRAM_WEBHOOK_INGESTION_ENABLED` until the worker, tenant-scoped
routing, and actual Meta webhook payload validation have been implemented,
tested, and approved. Encrypted storage alone will not show DMs to staff.

## Current database state (manually created by operator)

The owner has created the following tables in the shared database:
`sendro_tenants`, `sendro_tenant_users`,
`sendro_channel_accounts`, `sendro_channel_conversations`,
`sendro_channel_messages`, and `sendro_channel_webhook_deliveries`.
Tenant `sunset-oia` has 13 staff memberships (the technical/development
accounts are excluded). Channel accounts, conversations, messages, and
webhook deliveries are currently empty.

## Environment variables (staging backend only; secrets never shared in chat)

Already set:
- `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` — verifies the Meta GET challenge.
- `INSTAGRAM_APP_SECRET` — validates the raw POST signature.

**Not required until later worker/ingestion rollout, do not set the flag yet:**
- `INSTAGRAM_WEBHOOK_ENCRYPTION_KEY`: a new dedicated **Fernet** key,
  distinct from the app secret, access token, JWT key and existing
  encryption secrets. Generate privately using
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`,
  and copy directly into Render's secret environment variable field.
  Do not expose in screenshots or application logs. Losing the key
  makes historical encrypted deliveries irrecoverable.
- `INSTAGRAM_WEBHOOK_INGESTION_ENABLED`: must remain unset/`false`
  until the worker and message storage paths are ready and approved.

## Technical guarantees / limitations

- Reads request body as a bounded stream (max 256 KiB).
- Verifies `X-Hub-Signature-256` against the Instagram App Secret on the
  exact bytes before allowing any storage.
- Rejects payloads not structured as `object=instagram` + `entry` list.
- When deliberately enabled, encrypts complete body with Fernet BEFORE
  database insertion. Only ciphertext and SHA-256 digest are stored.
- Performs a single SQL transaction with unique
  `(provider,raw_body_sha256)` handling: identical signed retries get
  one row, and 200 only after commit.
- Database/encryption/config failures return 503; never silently send 200
  for a message that was not durably saved.
- Unknown Instagram message events are stored, **not interpreted** at
  this stage. The future worker MUST parse every nested entry/item,
  enforce per-tenant account routing, quarantine unsupported events,
  idempotently save messages and update conversation counters.
- Deliberately never logs raw body, access token, app secret or ciphertext.
  Apply an agreed retention/deletion policy before enabling real traffic.

## Next milestone

1. Verify Meta's actual Instagram Login webhook payload samples for
   inbound DMs, outbound echoes, delivery events and media types.
2. Build reliable worker claiming queued encrypted envelopes with locking
   and backoff; ensure all items of one delivery are processed exactly once
   or retried safely, and unknown accounts are quarantined rather than
   associated with the wrong tenant.
3. Implement channel-specific ORM/API and UI access enforcement by tenant
   and test with synthetic events.
4. Add Instagram business account by its actual IG business ID (never App
   ID), and securely store access token outside the DB until reviewed.
5. Then — and only then — deploy carefully, add Fernet key, enable
   ingestion, verify with official testers, and complete Meta publication /
   app permissions when ready.

## Test coverage

`backend/tests/test_instagram_encrypted_inbox.py`: Fernet ciphertext
roundtrip, no plaintext at rest, duplicate replay, distinct bodies,
malformed payloads, wrong key, database failure, disabled-by-default,
valid signature, bad signature, missing encryption key, body limit,
and durable HTTP acknowledgement on synthetic DB.

Production `main`, WhatsApp 24-hour messaging behavior and Inbox polling
are unchanged.
