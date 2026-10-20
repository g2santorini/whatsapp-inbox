# WhatsApp registry: production-shaped rehearsal vs genuine restored backup

**2026-10-20 — Read-only Sendro Render schema evidence and disposable CI ONLY.**
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

A real production-shaped migration rehearsal is still pending. When the
owner is at the Windows PC again, prepare an independently isolated local
PostgreSQL instance using the existing verified restore procedure, run
**only the reviewed manual-only migration against that clone with
independently provisioned synthetic/isolated roles**, then check that
legacy counts, names, FKs, and application reads remain unchanged.
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
