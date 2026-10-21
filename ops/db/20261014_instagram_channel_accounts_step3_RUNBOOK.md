# Sendro Instagram / SaaS — Manual database Step 3: channel accounts

Status: **prepared, not executed**. Applies to the **shared** live PostgreSQL used by staging and production, so obtain explicit backup/owner approval and run under the operator's supervision.

## Verified preflight (14 October 2026)

- `public.sendro_tenants` has tenant `1`, slug `sunset-oia`.
- `public.sendro_tenant_users` contains 13 memberships for tenant 1.
- `public.sendro_channel_accounts` does **not** exist.
- No change to existing WhatsApp tables or roles is needed.

## Change

Run `20261014_instagram_channel_accounts_step3.sql` manually in a short transaction. This adds an empty registry recording platform, external account ID, company ownership, optional display label and status. The unique (platform,external_account_id) constraint prevents a single IG/Facebook/WhatsApp account from being attached to two tenants; (id,tenant_id) supports future composite foreign keys. No secrets or tokens belong in this table.

No accounts are inserted at this stage: do **not** guess the Instagram business account ID from the Meta App ID (those are different identifiers). The Meta Instagram app access token stays secret; channel credential storage will be designed and reviewed separately. Use tenant + membership authorization before any API endpoints expose data.

## Preflight and postflight

Read-only preflight:
```sql
SELECT to_regclass('public.sendro_channel_accounts') AS existing;
```
Expected `null`. Confirm latest backup is recoverable.

Postflight:
```sql
SELECT column_name FROM information_schema.columns
WHERE table_schema='public' AND table_name='sendro_channel_accounts'
ORDER BY ordinal_position;
SELECT count(*) FROM public.sendro_channel_accounts;
```
Expected: `id`, `tenant_id`, `platform`, `external_account_id`, `display_name`, `status`, `created_at`, `updated_at` and **0** rows.

Any failed statement rolls back the transaction. Stop and inspect; never retry blindly. No DROP or destructive rollback without separate owner confirmation.

## Explicitly out of scope

No automatic migration, no production code changes, no WhatsApp webhook changes, no Instagram publication/subscription or DM ingestion, no cross-tenant user access enforcement yet. The existing WhatsApp inbox remains on its legacy schema.
