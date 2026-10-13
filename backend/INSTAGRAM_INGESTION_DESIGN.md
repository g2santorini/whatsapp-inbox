# Instagram Messaging: safe ingestion design for Sendro

**2026-10-13 — design only. No database migrations have run.**

## Current state

- Instagram Login is authorized for @sunsetoiasailing in Meta testing.
- Backend staging at `/webhook/instagram` verifies Meta GET challenge.
- A POST with a valid `X-Hub-Signature-256` returns intentional HTTP 503; no message is acknowledged or stored.
- The two test-only Meta permissions are `instagram_business_basic` and `instagram_business_manage_messages`.
- The Instagram webhook subscription remains OFF and Meta app publication/review has NOT been approved.
- Staging and production share a single PostgreSQL database. Adding even new tables has production implications; **requires separate explicit owner approval and backup**.

## Design requirements

1. **No phone number for Instagram identities.** Instagram peers have Instagram-scoped IDs. Do not use `conversations.contact_phone` or `messages.whatsapp_message_id` to represent Instagram.
2. **Channel + tenant isolation from the start.** The account receiving the DM, the company owning it, and the customer ID are all part of routing. Never associate conversations across businesses merely because the sender ID matches.
3. **Webhook durability before acknowledgments.** Validate raw body HMAC using `INSTAGRAM_APP_SECRET`. In a single database transaction, append the signed envelope to a durable, deduplicated webhook inbox. Return HTTP 200 *only after commit succeeds*. If the DB is unavailable, return 5xx so Meta can retry. Never print raw body, sender IDs or tokens in logs.
4. **Asynchronous message processing.** A worker processes each `entry[].messaging[]` item, creates/locates the scoped conversation, and enforces unique `(channel_account_id, message_id)` idempotency. Unknown and unsupported event types stay queued for explicit handling rather than being discarded.
5. **Outbound safety.** Channel-aware sends route to graph.instagram.com with the correct Instagram account token only if the Instagram customer-service window and Meta permissions allow it. Outbound errors must not be mislabeled as successful WhatsApp messages.
6. **UI compatibility.** Existing WhatsApp Inbox, user roles, quick replies and 5/15/15-second polling continue unchanged. A channel-aware API can merge rows for Instagram and WhatsApp in a separate feature rollout. No UI sends Instagram DMs before backend tests and Meta test approval.
7. **Privacy.** Encrypt Instagram access tokens at rest, prevent their inclusion in response objects/logs, use explicit retention and deletion rules for any saved raw envelopes.

## Proposed (NOT YET APPLIED) relational structure

- `sendro_tenants`: tenant ID, name, created_at; existing Sunset Oia accounts must be explicitly assigned to its own tenant before granting anyone channel access.
- `sendro_tenant_users`: tenant_id + existing users.id + role. Every channel endpoint checks membership and permissions.
- `sendro_channel_accounts`: tenant_id, platform (instagram initially), external business ID, secure encrypted credential reference, created_at, status. Unique provider+business-ID ownership constraint; no duplicated claiming of the same IG business account across tenants.
- `sendro_channel_conversations`: tenant_id, channel_account_id, Instagram-scoped customer ID, assignee, status/unread count, timestamps. Unique account+customer pair. Prevent cross-tenant foreign keys with composite keys/foreign-key checks.
- `sendro_channel_messages`: tenant_id, conversation_id, channel_account_id, provider message ID, direction, text, media metadata, timestamps and status. Unique account+provider-message-ID; optimize `(conversation_id,id DESC)`.
- `sendro_channel_webhook_deliveries`: account/tenant routing, SHA-256 of raw request (or provider delivery ID where available), encrypted payload or minimal verified event JSON, receive/processed timestamps, error/retry state. A signed batch persists atomically before a success response. Quarantine events that cannot be routed rather than assigning the wrong tenant.

This structure is a *design proposal*, not a migration to run automatically. It must be reviewed for referential integrity, exact payload retention, encryption, and compatibility with the existing `create_all` application startup logic. Use a manual migration after explicit backup verification; never automatically create these tables on staging boot, because staging uses the **production-shared** DB.

## Current code in this PR

- `backend/app/instagram_event_normalizer.py` is a pure parser for `object=instagram` messaging webhook batches: account routing, inbound DM vs outbound echo, text/media metadata, timestamps.
- Unknown reactions, unsends, reads, comments and malformed account IDs produce an explicit error rather than silently losing data.
- Unit tests use synthetic IDs and no real accounts, network requests or databases.
- It is **not wired to the POST endpoint yet**. The endpoint continues to return 503 until durable ingestion exists.

## Controlled rollout

1. Obtain sample webhook structure from Meta's testing tools with fake data; verify the parser against the actual Instagram Login variant.
2. Review and approve shared-DB tenant/channel migration **separately**. Confirm fresh backup and deployment window.
3. Implement webhook-inbox + workers and write isolated SQLite/Postgres tests for batch+retry+duplicates; keep ingestion disabled by default.
4. Confirm account credential handling, scoped authorization, and Instagram outbound messaging rules.
5. Only then consider Meta Publish/App Review and enable webhook subscription, initially with approved testing identities.
6. Measure and observe actual deliveries, errors and reversibility. Roll out UI channel filters only after processing is stable.

## Unchanged

- No database DDL or writes, no Instagram webhook subscription, no Meta publication.
- No changes to WhatsApp webhook/send, users, roles, existing message tables, or the frontend polling frequencies.
