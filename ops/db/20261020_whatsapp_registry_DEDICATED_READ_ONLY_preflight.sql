-- Sendro dedicated WhatsApp registry — catalog-only readiness report.
-- A pass does NOT authorize SQL writes to the shared database.
-- Reads names, type/role metadata and object metadata ONLY; no business rows.
WITH required(table_name,column_name,expected_type) AS (
    VALUES
      ('sendro_tenants','id','bigint'),
      ('sendro_tenant_users','tenant_id','bigint'),
      ('sendro_tenant_users','user_id','integer'),
      ('sendro_tenant_users','member_role','text_or_varchar'),
      ('sendro_tenant_users','is_active','boolean'),
      ('users','id','integer'),
      ('users','disabled','boolean')
), cols AS (
    SELECT r.table_name, r.column_name,
           COALESCE(
              CASE WHEN r.expected_type='text_or_varchar'
              THEN pg_catalog.format_type(a.atttypid,NULL) IN ('text','character varying')
              ELSE pg_catalog.format_type(a.atttypid,NULL)=r.expected_type END,
              FALSE) AS valid_type
    FROM required r
    LEFT JOIN pg_catalog.pg_namespace n ON n.nspname='public'
    LEFT JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid
         AND c.relname=r.table_name AND c.relkind IN ('r','p')
    LEFT JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
         AND a.attname=r.column_name AND a.attnum>0 AND NOT a.attisdropped
), objects AS (
    SELECT
      pg_catalog.to_regnamespace('sendro_whatsapp') IS NOT NULL AS new_schema_exists,
      pg_catalog.to_regclass('sendro_whatsapp.verified_destinations') IS NOT NULL AS new_table_exists,
      pg_catalog.to_regclass('public.sendro_whatsapp_verified_destinations') IS NOT NULL AS old_proposal_table_exists,
      EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='sendro_whatsapp_registry_owner')
         AS owner_role_exists,
      EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='sendro_whatsapp_registry_reader')
         AS reader_role_exists,
      EXISTS(SELECT 1 FROM pg_catalog.pg_constraint con
        WHERE con.conrelid=pg_catalog.to_regclass('public.sendro_tenant_users')
        AND con.contype IN ('p','u')
        AND ARRAY(SELECT att.attname::text FROM unnest(con.conkey) AS u(num)
          JOIN pg_catalog.pg_attribute att
          ON att.attrelid=con.conrelid AND att.attnum=u.num
          ORDER BY att.attname)=ARRAY['tenant_id','user_id']::text[])
         AS membership_key_exists
)
SELECT current_database() AS database_name,
       current_setting('transaction_read_only') AS transaction_read_only,
       current_setting('server_version_num') AS server_version_num,
       (SELECT COUNT(*) FROM cols) AS checked_columns,
       (SELECT COUNT(*) FROM cols WHERE valid_type) AS valid_columns,
       (SELECT string_agg(table_name||'.'||column_name,', ' ORDER BY table_name,column_name)
        FROM cols WHERE NOT valid_type) AS incompatible_columns,
       objects.*,
       (SELECT COALESCE(bool_and(valid_type),FALSE) FROM cols)
           AND objects.membership_key_exists
           AND NOT objects.new_schema_exists
           AND NOT objects.old_proposal_table_exists AS schema_shape_ready
FROM objects;
