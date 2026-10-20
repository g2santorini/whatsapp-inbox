-- Sendro WhatsApp registry — read-only ROLE/ACL readiness preflight.
-- SELECT-only catalog/privilege metadata; NO guest rows, account IDs or secrets.
-- Safe to run on the shared DB only as an explicitly approved read-only check.
-- It inspects the current CONNECTION ROLE. It does NOT establish which role
-- staging/production actually uses; audit their config independently.
-- A green result here is NEVER DDL/GRANT/Meta activation approval.
WITH inspector AS (
    SELECT r.rolname, r.rolsuper, r.rolcreatedb, r.rolcreaterole,
           r.rolbypassrls, r.rolcanlogin
    FROM pg_catalog.pg_roles r
    WHERE r.rolname = CURRENT_USER
),
target AS (
    SELECT pg_catalog.to_regclass(
        'public.sendro_whatsapp_verified_destinations'
    )::oid AS registry_oid
),
acl AS (
    SELECT
        t.registry_oid IS NOT NULL AS registry_exists,
        (SELECT pg_catalog.pg_get_userbyid(c.relowner)
           FROM pg_catalog.pg_class c WHERE c.oid=t.registry_oid
        ) AS registry_owner,
        pg_catalog.has_schema_privilege(CURRENT_USER, 'public', 'CREATE')
            AS can_create_in_public,
        pg_catalog.has_database_privilege(CURRENT_USER, CURRENT_DATABASE(), 'CREATE')
            AS can_create_in_database,
        COALESCE(pg_catalog.has_table_privilege(
            CURRENT_USER,t.registry_oid,'INSERT,UPDATE,DELETE,TRUNCATE'),FALSE)
            AS has_table_mutation_privilege,
        COALESCE(pg_catalog.has_column_privilege(
            CURRENT_USER,t.registry_oid,'revoked_at','UPDATE'),FALSE)
            AS can_revoke,
        COALESCE(pg_catalog.has_column_privilege(
            CURRENT_USER,t.registry_oid,'evidence_ref','SELECT'),FALSE)
            AS can_read_evidence_ref,
        COALESCE(pg_catalog.has_column_privilege(
            CURRENT_USER,t.registry_oid,'verified_by_user_id','SELECT'),FALSE)
            AS can_read_reviewer_id,
        COALESCE(pg_catalog.has_column_privilege(
            CURRENT_USER,t.registry_oid,'waba_id','SELECT'),FALSE)
        AND COALESCE(pg_catalog.has_column_privilege(
            CURRENT_USER,t.registry_oid,'phone_number_id','SELECT'),FALSE)
        AND COALESCE(pg_catalog.has_column_privilege(
            CURRENT_USER,t.registry_oid,'tenant_id','SELECT'),FALSE)
        AND COALESCE(pg_catalog.has_column_privilege(
            CURRENT_USER,t.registry_oid,'revoked_at','SELECT'),FALSE)
            AS can_read_routing_metadata,
        COALESCE(
            (SELECT c.relowner = (SELECT oid FROM pg_catalog.pg_roles
                 WHERE rolname=CURRENT_USER)
             FROM pg_catalog.pg_class c WHERE c.oid=t.registry_oid),
            FALSE) AS owns_registry,
        COALESCE(
            (SELECT pg_catalog.pg_has_role(
                CURRENT_USER,c.relowner,'MEMBER'
             ) FROM pg_catalog.pg_class c WHERE c.oid=t.registry_oid),
            FALSE) AS member_of_registry_owner
    FROM target t
)
SELECT
    CURRENT_DATABASE() AS database_name,
    CURRENT_SETTING('transaction_read_only') AS transaction_read_only,
    CURRENT_SETTING('server_version_num') AS postgres_version_num,
    i.rolname AS inspected_role,
    i.rolsuper,
    i.rolcreatedb,
    i.rolcreaterole,
    i.rolbypassrls,
    i.rolcanlogin,
    acl.registry_exists,
    acl.registry_owner,
    acl.can_create_in_public,
    acl.can_create_in_database,
    acl.owns_registry,
    acl.member_of_registry_owner,
    acl.has_table_mutation_privilege,
    acl.can_revoke,
    acl.can_read_evidence_ref,
    acl.can_read_reviewer_id,
    acl.can_read_routing_metadata,
    (i.rolsuper OR i.rolcreatedb OR i.rolcreaterole
      OR i.rolbypassrls OR acl.can_create_in_public
      OR acl.owns_registry OR acl.member_of_registry_owner)
      AS role_separation_required,
    (acl.registry_exists AND acl.can_read_routing_metadata
      AND NOT (i.rolsuper OR i.rolcreatedb OR i.rolcreaterole
        OR i.rolbypassrls OR acl.can_create_in_public
        OR acl.owns_registry OR acl.member_of_registry_owner
        OR acl.has_table_mutation_privilege OR acl.can_revoke
        OR acl.can_read_evidence_ref OR acl.can_read_reviewer_id))
      AS metadata_reader_least_privilege_pass
FROM inspector i CROSS JOIN acl;
