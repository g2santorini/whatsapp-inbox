-- READ-ONLY CATALOG PREFLIGHT TEMPLATE. DO NOT RUN BY AUTOMATION.
-- Requires user's explicit authorization before even querying the shared
-- Render PostgreSQL, despite containing SELECT statements only.
--
-- Inspect names/types/constraints; never SELECT customer/token rows.
-- The following statements do not change tables, secrets, roles or settings.

SELECT
    to_regclass('public.sendro_tenants') IS NOT NULL
        AS has_tenant_table,
    to_regclass('public.sendro_tenant_users') IS NOT NULL
        AS has_tenant_user_table,
    to_regclass('public.sendro_channel_accounts') IS NOT NULL
        AS has_channel_registry,
    to_regclass('public.sendro_instagram_oauth_challenges') IS NOT NULL
        AS already_has_instagram_oauth_challenges,
    to_regclass('public.sendro_instagram_token_vault') IS NOT NULL
        AS already_has_instagram_token_vault;

SELECT
    c.table_name, c.column_name, c.data_type,
    c.is_nullable
FROM information_schema.columns AS c
WHERE c.table_schema = 'public'
  AND c.table_name IN (
    'sendro_tenants',
    'sendro_tenant_users',
    'sendro_channel_accounts',
    'sendro_instagram_oauth_challenges',
    'sendro_instagram_token_vault'
  )
ORDER BY c.table_name, c.ordinal_position;

SELECT
    t.relname AS table_name,
    con.conname AS constraint_name,
    con.contype AS constraint_type
FROM pg_catalog.pg_constraint AS con
JOIN pg_catalog.pg_class AS t
  ON con.conrelid = t.oid
JOIN pg_catalog.pg_namespace AS n
  ON t.relnamespace = n.oid
WHERE n.nspname = 'public'
  AND t.relname IN (
    'sendro_tenant_users',
    'sendro_channel_accounts',
    'sendro_instagram_oauth_challenges',
    'sendro_instagram_token_vault'
  )
ORDER BY t.relname, con.conname;

-- No SELECT from any tables containing real users, Instagram tokens or DMs.
-- No role names or credential values are displayed. Finish here.
