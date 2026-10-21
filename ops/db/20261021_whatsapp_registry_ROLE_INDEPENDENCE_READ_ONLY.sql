-- Read-only Render PostgreSQL 18 registry-owner independence audit.
-- Does not reveal passwords, connection strings or guest records.
-- Run only as a SELECT (the Render SQL connector wraps it read-only).
-- A result does NOT authorize changing the live database.
WITH wanted(role_name) AS (
  VALUES ('sendro_user'),('postgres'),('primaryuser'),('render_conn'),
         ('datadog'),('sendro_whatsapp_registry_owner'),
         ('sendro_whatsapp_registry_reader')
), owner AS (
  SELECT oid FROM pg_catalog.pg_roles
  WHERE rolname='sendro_whatsapp_registry_owner'
), found AS (
  SELECT w.role_name,r.oid,r.rolcanlogin,r.rolsuper,r.rolcreaterole,
         r.rolcreatedb,r.rolbypassrls
  FROM wanted w LEFT JOIN pg_catalog.pg_roles r ON r.rolname=w.role_name
)
SELECT current_database() AS database_name,
       current_setting('transaction_read_only') AS read_only,
       f.role_name, (f.oid IS NOT NULL) AS role_exists,
       f.rolcanlogin, f.rolsuper, f.rolcreaterole,
       f.rolcreatedb, f.rolbypassrls,
       CASE WHEN f.oid IS NULL THEN NULL
            ELSE pg_catalog.has_database_privilege(f.oid,current_database(),'CREATE')
       END AS database_create,
       CASE WHEN NOT EXISTS(SELECT 1 FROM owner) OR f.oid IS NULL THEN NULL
            ELSE EXISTS(
              SELECT 1 FROM pg_catalog.pg_auth_members m
              WHERE m.member=f.oid AND m.roleid=(SELECT oid FROM owner)
                AND m.admin_option
            )
       END AS directly_administers_registry_owner,
       CASE WHEN NOT EXISTS(SELECT 1 FROM owner) OR f.oid IS NULL THEN NULL
            ELSE EXISTS(
              SELECT 1 FROM pg_catalog.pg_auth_members m
              WHERE m.member=f.oid AND m.roleid=(SELECT oid FROM owner)
                AND m.set_option
            )
       END AS direct_set_registry_owner,
       (pg_catalog.to_regnamespace('sendro_whatsapp') IS NOT NULL) AS new_schema_exists,
       (pg_catalog.to_regclass('sendro_whatsapp.verified_destinations') IS NOT NULL) AS new_registry_exists
FROM found f
ORDER BY f.role_name;