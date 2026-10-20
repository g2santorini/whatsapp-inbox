-- READ-ONLY preflight for the MANUAL-ONLY WhatsApp destination registry.
-- Returns catalog metadata ONLY. Do not treat a pass as write authorization.
-- The Render staging and production backends share the same database.
-- PostgreSQL 16+ compatible; no customer rows, provider IDs, or credentials.
WITH expected_columns(relation_name, column_name, allowed_types) AS (
    VALUES
      ('sendro_tenants', 'id', ARRAY['bigint']::text[]),
      ('sendro_tenant_users', 'tenant_id', ARRAY['bigint']::text[]),
      ('sendro_tenant_users', 'user_id', ARRAY['integer']::text[]),
      ('sendro_tenant_users', 'member_role', ARRAY['text','character varying']::text[]),
      ('sendro_tenant_users', 'is_active', ARRAY['boolean']::text[]),
      ('users', 'id', ARRAY['integer']::text[]),
      ('users', 'disabled', ARRAY['boolean']::text[])
),
examined AS (
    SELECT e.relation_name, e.column_name,
           COALESCE(
             pg_catalog.format_type(a.atttypid, NULL) = ANY(e.allowed_types),
             FALSE
           ) AS type_matches
    FROM expected_columns e
    LEFT JOIN pg_catalog.pg_namespace n
      ON n.nspname = 'public'
    LEFT JOIN pg_catalog.pg_class c
      ON c.relnamespace = n.oid
     AND c.relname = e.relation_name
     AND c.relkind IN ('r', 'p')
    LEFT JOIN pg_catalog.pg_attribute a
      ON a.attrelid = c.oid
     AND a.attname = e.column_name
     AND a.attnum > 0
     AND NOT a.attisdropped
),
membership_key AS (
    SELECT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint con
        WHERE con.conrelid = pg_catalog.to_regclass('public.sendro_tenant_users')
          AND con.contype IN ('p','u')
          AND ARRAY(
              SELECT att.attname::text
              FROM unnest(con.conkey) AS key_column(attnum)
              JOIN pg_catalog.pg_attribute att
                ON att.attrelid = con.conrelid
               AND att.attnum = key_column.attnum
              ORDER BY att.attname
          ) = ARRAY['tenant_id','user_id']::text[]
    ) AS present
),
collisions AS (
    SELECT
        pg_catalog.to_regclass(
            'public.sendro_whatsapp_verified_destinations'
        ) IS NOT NULL AS table_exists,
        pg_catalog.to_regclass(
            'public.idx_sendro_whatsapp_destination_active_waba'
        ) IS NOT NULL AS index_name_exists,
        pg_catalog.to_regprocedure(
            'public.sendro_whatsapp_destination_validate_reviewer()'
        ) IS NOT NULL AS reviewer_function_exists,
        pg_catalog.to_regprocedure(
            'public.sendro_whatsapp_destination_immutable()'
        ) IS NOT NULL AS immutability_function_exists
)
SELECT
    current_database() AS database_name,
    current_setting('transaction_read_only') AS transaction_read_only,
    current_setting('server_version_num') AS postgres_version_number,
    (SELECT COUNT(*) FROM examined) AS checked_columns,
    (SELECT COUNT(*) FROM examined WHERE type_matches) AS matched_columns,
    (SELECT string_agg(relation_name || '.' || column_name, ', ' ORDER BY relation_name, column_name)
     FROM examined WHERE NOT type_matches) AS missing_or_incompatible_columns,
    (SELECT present FROM membership_key) AS composite_membership_key_present,
    collisions.table_exists,
    collisions.index_name_exists,
    collisions.reviewer_function_exists,
    collisions.immutability_function_exists,
    (
        (SELECT COALESCE(bool_and(type_matches), FALSE) FROM examined)
        AND (SELECT present FROM membership_key)
        AND NOT collisions.table_exists
        AND NOT collisions.index_name_exists
        AND NOT collisions.reviewer_function_exists
        AND NOT collisions.immutability_function_exists
    ) AS schema_preflight_pass
FROM collisions;
