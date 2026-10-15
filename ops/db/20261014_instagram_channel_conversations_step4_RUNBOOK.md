# Sendro Instagram / SaaS — DB Step 4 (manual, one empty table)

**Not applied by GitHub or the app.** Staging and production share one live PostgreSQL database. The operator must execute one transaction after confirmation of a fresh recoverable backup. The user controls the execution.

## Preconditions

- DB name `sendro`; `sendro_tenants` includes ID 1, slug `sunset-oia`.
- `sendro_tenant_users` has exactly 13 entries for that tenant.
- `sendro_channel_accounts` exists with 8 columns and currently zero rows.
- `sendro_channel_conversations` must not already exist. Stop if it does.

## Purpose

Create a new, **empty** `sendro_channel_conversations` table for social media customer threads, separate from legacy WhatsApp `conversations`.

- `tenant_id`, `channel_account_id` enforce business account ownership with composite foreign key.
- `external_customer_id` stores platform-scoped Instagram/Facebook/etc customer ID as a string; NEVER use `contact_phone`.
- `(channel_account_id,external_customer_id)` uniquely identifies a single customer thread on that account.
- `(tenant_id,assigned_to_user_id)` references existing `sendro_tenant_users` membership, rejecting assignment to someone outside the company.
- `(id,tenant_id,channel_account_id)` unique constraint prepares composite keys for a future `sendro_channel_messages` table.
- Status, contact name, unread count and timestamps can drive a future channel-aware Inbox. Negative unread counts and unrecognized status values are rejected.
- `assigned_to_user_id` can be NULL (unassigned). The member's `is_active` status must **also** be checked in the future application layer; the foreign key alone does not enforce active status.

## Execution and verification

Execute `ops/db/20261014_instagram_channel_conversations_step4.sql` manually inside its transaction; no automatic migration. Confirm 11 columns, no rows, two foreign key relationships and the account+customer unique constraint.

The change does not alter existing WhatsApp tables, user privileges or webhook endpoints, and stores no Instagram credentials.

Do not enable Instagram webhook subscription. The Instagram POST handler intentionally refuses to acknowledge notifications until durable message persistence and retry-safe processing are complete. No live Instagram messages are stored by this step.

## Rollback

Do not drop the new table without separate approval; after inserting data or adding dependent message tables, dropping it could destroy data.
