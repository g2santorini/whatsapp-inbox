-- GDPR Phase 4: READ-ONLY schema readiness report.
-- No PII, no message reads, no data changes, no migration.
-- May be executed manually with a read-only connection after authorization.
WITH required_columns(table_name, column_name) AS (
    VALUES
      ('sendro_tenants','id'),
      ('sendro_tenant_users','tenant_id'),
      ('sendro_tenant_users','user_id'),
      ('sendro_tenant_users','member_role'),
      ('sendro_tenant_users','is_active'),
      ('users','id'),
      ('users','disabled')
), examined AS (
    SELECT r.table_name, r.column_name,
           EXISTS (
               SELECT 1 FROM information_schema.columns c
               WHERE c.table_schema='public'
                 AND c.table_name=r.table_name
                 AND c.column_name=r.column_name
           ) AS present
    FROM required_columns r
)
SELECT
    current_database() AS database_name,
    current_setting('transaction_read_only') AS transaction_read_only,
    current_setting('server_version_num') AS postgres_version_number,
    COUNT(*) AS expected_columns,
    COUNT(*) FILTER (WHERE present) AS present_columns,
    COUNT(*) FILTER (WHERE NOT present) AS missing_columns,
    (SELECT COUNT(*) FROM pg_catalog.pg_class
     WHERE relnamespace='public'::regnamespace
       AND relname IN ('sendro_privacy_cases',
                       'sendro_privacy_case_events')) AS existing_privacy_relations,
    (SELECT COUNT(*) FROM pg_catalog.pg_proc
     WHERE pronamespace='public'::regnamespace
       AND proname='sendro_privacy_event_no_mutation') AS existing_privacy_trigger_functions,
    (SELECT COUNT(*) FROM pg_catalog.pg_constraint
     WHERE conrelid='public.sendro_tenant_users'::regclass
       AND contype IN ('p','u')
       AND pg_get_constraintdef(oid) LIKE '%(tenant_id, user_id)%') AS tenant_membership_composite_keys
FROM examined;
