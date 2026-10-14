# Sendro Instagram SaaS — manual database Step 2

Prepared only. The staging `dev` and production `main` backends share the same live PostgreSQL instance. No DDL runs during deployment.

## Existing state checked

- The `sendro_tenants` table exists with 4 columns; `sendro_tenants` has **0 rows**.
- Existing `users` table has user IDs as PostgreSQL `integer`.
- `sendro_tenant_users` does **not** exist yet.
- A backup was reported taken by the owner; confirm it is retained and recoverable before executing.

## Purpose

Create an **empty** `sendro_tenant_users` table. Each row would link an existing Sendro user to one company. A compound primary key forbids duplicate memberships. Separate foreign keys with `ON DELETE RESTRICT` prevent accidental deletion of members/companies while membership exists.

Fields: tenant_id bigint, user_id integer, member_role (owner/admin/operator/viewer), is_active, joined_at. A user_id lookup index complements the (tenant_id,user_id) primary key.

This migration **does not** add members, reassign roles, change existing users or WhatsApp access control, or enable Instagram DMs. No existing tables are altered.

## Manual instructions

Execute `20261014_instagram_tenant_users_step2.sql` once in a transactional SQL session. Stop on any error. Do **not** add `IF NOT EXISTS` to hide partial/different schema. Verify it has 5 columns and 0 rows afterward.

## Next steps require separate approval

1. Create a tenant row for Sunset Oia and bind named staff memberships after explicit review of the 16 existing Sendro users.
2. Build tenant-scoped channel accounts, conversations, messages and durable webhook deliveries with proper composite constraints.
3. Implement authorization checks and message ingestion; complete tests before any real Instagram webhook subscription.

No automatic migration. No rollback without a separate user approval, and never drop tables with real company or message data.
