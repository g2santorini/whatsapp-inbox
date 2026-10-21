# WhatsApp registry: production-shaped rehearsal vs genuine restored backup

**Updated 2026-10-21: Render catalog read-only inspection + disposable CI + successful installation on a *local clone of a verified real backup*. NO Render/shared-DB writes.**
No customer information, IDs, DB credentials, or backup data are in this file.

## Verified PostgreSQL 18.3 dependency shape (catalog-only)

The actual **shared** Render database has these relevant features:
- `public.sendro_tenants`: `id BIGINT` primary key, mandatory unique
  `slug VARCHAR(100)` with slug format check, mandatory
  `display_name VARCHAR(160)`, `created_at TIMESTAMPTZ DEFAULT now()`.
- `public.sendro_tenant_users`: `tenant_id BIGINT`, `user_id INTEGER`,
  primary key `(tenant_id,user_id)`, actual foreign keys to tenant and
  users on delete restrict, `member_role VARCHAR(20)` restricted to
  `owner/admin/operator/viewer`, `is_active BOOLEAN`, and
  `joined_at TIMESTAMPTZ DEFAULT now()`.
- `public.users`: `id INTEGER`, `disabled BOOLEAN NOT NULL`;
  the real table contains additional unrelated authentication columns
  intentionally NOT reproduced in CI.
- These three tables are owned by the existing `sendro_user`. The schema
  and registry preflight passed 7/7 required types, with NO new schema/role
  present on shared Render at the last read-only inspection.
- A metadata-only sample of `pg_stat_activity` showed active/idle
  connections with username `sendro_user`. It does **not** attribute
  a particular session to staging vs production.

## Additional PostgreSQL 18.3 CI regression

`backend/tests/test_whatsapp_dedicated_registry_postgres_ci.py` now
models the actual **tenant and membership constraint shape**, including
FK restrictions, slug and member-role checks, timestamps/defaults and
column widths, all with fabricated rows. It snapshots catalog signatures
of pre-existing columns and constraints plus fake row counts before
and after executing the EXACT inactive registry SQL.

A test passing means:
1. The synthetic source tables remain byte-for-byte identical **in their
   catalog representations** and fake row counts, after registry creation.
2. A failed installation leaves no partial schema.
3. The successful install creates an empty schema/table independently owned,
   with narrow read-only privileges, and an attempted second install fails.

**This is an improved dependency-shape rehearsal, NOT a production backup
restore, a reproduction of the full Sendro database, nor approval for
a shared-database DDL change.**

## Backup limitation and next practical step

The genuine 2026-10-20 Render backup
`2026-10-20T07_27Z.dir.tar.gz` was successfully restored/validated
on the user's **Windows machine** earlier today and the isolated temporary
local database was stopped. This ongoing execution environment does
NOT contain that original backup or a mounted clone, and no private
file was found in the accessible Sendro Project files.

Do **not** upload the customer-data backup into the public GitHub repo,
attach it to GitHub Actions, or deploy it on an unrelated shared cloud
service. Preserve the original backup securely.

### Completed 2026-10-21 — real restored-clone SQL installation (user-verified terminal output)

The Windows machine hosted PostgreSQL 18 in an isolated local cluster
bound to `127.0.0.1:55442` with two databases:

- Original restored backup: `sendro_restore_check`, preserved as reference.
- Independently cloned rehearsal DB:
  `sendro_registry_rehearsal_20261020`, created via PostgreSQL
  `CREATE DATABASE ... WITH TEMPLATE sendro_restore_check`.

The owner reported executing the **exact manually reviewed SQL** from
`ops/db/20261020_whatsapp_registry_DEDICATED_SCHEMA_MANUAL_ONLY.sql`,
downloaded from immutable commit
`7b895cdc73e169b17209cf7d38b855cab020dd69`; their PowerShell
verified Git blob SHA-1
`889f4e0b3bfea64b454f5b24a887117f16f2d955` BEFORE executing.
The clone-only safety check passed. The execution log contained
`BEGIN`, `CREATE SCHEMA`, `CREATE TABLE`, both triggers/functions,
grants and `COMMIT`, then printed
`REGISTRY_INSTALL_VERIFIED_OK`.

The owner then ran the independent read-only audit and reported:

- `ORIGINAL_RESTORE_OK` — source restore still has **no registry schema**.
- `CLONE_SECURITY_AUDIT_OK` — clone has an empty registry, correct
  NOLOGIN ownership, intended reader column-level SELECT and schema
  USAGE only, absent reader write/schema CREATE/sensitive-column SELECT,
  and both intended enabled noninternal triggers.
- `SENDRO_LOCAL_REGISTRY_REHEARSAL_PASSED`.
- Both databases' expected **one tenant, 25,548 conversations and 95,316
  messages** were checked. This confirms row **counts**, not hashes or
  deep content equality, and is not a complete application regression.
- Local `sendro_restore_local` superuser password was rotated after
  the test; local PostgreSQL shut down cleanly with
  `LOCAL_TEST_DATABASE_STOPPED`. Never store secrets in GitHub.

**Scope and important remaining caveats:** This is now an actual
real-backup **local-clone installation rehearsal**, NOT merely synthetic CI.
It validates the registry installation, basic ownership/read permissions,
the original backup's lack of registry and unchanged row counts.
It does **not** validate live routing or full app behavior, full
rollback/forward recovery after a simulated failure, complete data
checksums, production PostgreSQL role provisioning or a Render deployment.
The independent local migration administrator was a **local superuser**:
that does not establish an available/approved independent admin in Render.
The shared Render database remains unchanged; there is no authorization
for any live role, credential, schema, DDL, DML or Meta switch.

Do not run migration SQL on the shared Render DB.

## Independent role owner — unresolved external constraint

The Render-managed credential flow makes a newly created credential
the **new default user**, which can alter connection-string references
on future Blueprint sync. The privilege boundaries for independently
provisioned PostgreSQL roles are not yet confirmed for this instance.
The available Render connector exposes only **read-only PostgreSQL SQL**
plus service metadata; it cannot safely confirm individual backend
DATABASE_URL usernames (nor should credentials be printed).

Before any shared-DB write, obtain a documented feasible path for a
migration-only role genuinely independent of `sendro_user`. A role
created by `sendro_user` itself is NOT independent because of PostgreSQL
18 CREATEROLE administrative membership. If Render cannot supply that
boundary, choose a separately reviewed architecture instead of weakening
the approval gate.

References:
- https://www.postgresql.org/docs/18/role-attributes.html
- https://render.com/docs/postgresql-credentials

## Shared database freeze

No existing grants, connection strings, roles, backup schedules, schema,
routing, Meta account IDs or historical privacy links may be modified
as part of this PR. A fresh restorable backup and a new **explicit**
owner authorization remain mandatory before the first real change.
