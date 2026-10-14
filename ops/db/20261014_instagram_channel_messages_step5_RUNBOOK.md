# Sendro Instagram / SaaS — manual database Step 5: channel messages

**Status:** Prepared only. This PR performs no migration on its own.

Staging and production share the same PostgreSQL database. Run manually
only after confirming a recoverable backup and the owner's approval.
The existing WhatsApp tables and inbox code are not modified.

## Prerequisites

1. Database `sendro`.
2. Tenant `1`, slug `sunset-oia`, with 13 memberships.
3. `sendro_channel_accounts` and `sendro_channel_conversations`
   both exist and contain zero rows.
4. `sendro_channel_messages` does not yet exist.
5. The operator has verified a fresh backup.

## What changes

Creates a new, **empty**, channel-specific messages table with 15 fields:

- Tenant/account/conversation IDs use a **three-column foreign key** into
  `sendro_channel_conversations`; a message cannot reference a conversation
  belonging to a different tenant or social account.
- Optional `sent_by_user_id` has a composite tenant/member foreign key.
- `provider_message_id` is unique per channel account (deduplicates inbound
  retries); inbound rows must have a provider message ID. Outbound draft/
  pending rows may lack one until the provider accepts a send.
- `direction` is inbound/outbound; text is stored as `content`, optional
  attachments metadata as `media_json` JSONB. No message with neither.
- `provider_timestamp` records platform time; delivery status / is_read
  support later channel-specific inbox interactions.
- Indexes support recent messages per conversation and tenant.

The unique account/message-ID constraint is necessary but not by itself
sufficient for fully safe webhook batch processing. We still need a
durable webhook inbox, transaction handling, retry worker, and proven
idempotency and authorization at the application level.

## Manual postflight

Expected: 15 columns, 0 message rows, 2 foreign keys.
```sql
SELECT count(*) FROM information_schema.columns
WHERE table_schema='public' AND table_name='sendro_channel_messages';
SELECT count(*) FROM public.sendro_channel_messages;
SELECT count(*) FROM pg_constraint
WHERE conrelid='public.sendro_channel_messages'::regclass
  AND contype='f';
```

## Exclusions / safety

- No migration at app startup, no automatic PR deploy altering the database.
- No WhatsApp `messages` or `conversations` changes; existing polling remains as-is.
- No Meta webhook subscription or Instagram app publication yet.
- No tokens, app secrets or raw personal webhooks added. Credentials need
  a separate secure storage design; avoid storing ephemeral media URLs with
  credentials in logs.
- No automatic tenant-enforced access until APIs actually enforce it.
- Do not drop tables for rollback without separate owner approval.
