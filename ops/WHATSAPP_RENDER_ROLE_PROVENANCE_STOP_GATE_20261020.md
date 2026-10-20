# WhatsApp registry — Render role-provenance STOP gate (2026-10-20)

**Decision: continue in disposable CI/read-only only. No shared-DB role
provisioning, ACL changes, table creation or deployment authorized.**

## Verified facts — Sendro Render metadata-only inspection

Inspected the agreed Sendro workspace, the `sendro-postgres` shared database
`sendro`, PostgreSQL server 18.3. Queries were SELECT-only and reported
`transaction_read_only=on`.

- Inspector principal: `sendro_user`; login enabled, `CREATEROLE=true`,
  `CREATEDB=true`, `SUPERUSER=false`, `BYPASSRLS=false`.
- Current database and `public` schema are both **owned by `sendro_user`**.
  Database and public-schema CREATE privileges are enabled.
- Direct role memberships for the inspector: **zero**.
- The proposed NOLOGIN `sendro_whatsapp_registry_owner` and reader
  `sendro_whatsapp_registry_reader` **do not exist**.
- Proposed `sendro_whatsapp` schema and `verified_destinations` table
  **do not exist**, nor does the previous public-table proposal.
- Existing seven prerequisite column types and membership composite key
  passed their previous read-only compatibility test.

**Important boundary:** these checks identify the database connection used
by the read-only Render tool. They do **not** independently prove the
connection role used by *either* running Sendro backend (production or staging).
Both backends share the database. Credentials/DSNs were neither requested
nor printed.

## Why a role created by the legacy login is NOT an independent owner

PostgreSQL 18 gives a non-superuser who has `CREATEROLE` the `ADMIN`
membership on roles they create (`SET FALSE, INHERIT FALSE` initially).
The creator can use that `ADMIN` capability to grant itself `SET TRUE`
and assume the new role. Therefore, an owner role created through the
legacy `sendro_user` would **not** satisfy the promised trust boundary.

Official PostgreSQL 18 documentation:
https://www.postgresql.org/docs/18/role-attributes.html

This is covered by the synthetic negative regression
`test_createrole_self_created_owner_is_not_independent`, executed ONLY
against a guarded, disposable GitHub PostgreSQL 18.3 service. It proves
that the role creator can become the role it made, and separately checks
that the **independently created** registry owner cannot be reached by
the simulated privileged legacy login. Never test role escalation against
the Render/shared customer database.

## Render user management caveat

Render documents a dashboard/API mechanism to add managed database
credentials, but the newly added managed credential becomes the
**new default user**. Blueprint-managed connection URL references may
change upon a future Blueprint sync. Creating a user with SQL instead
does not make that user a Render-managed credential.

Official Render documentation:
https://render.com/docs/postgresql-credentials

Do NOT click `New default credential`, provision a user via the API,
run `CREATE ROLE`, rotate passwords or change existing database
environment variables as a way to bypass this gate. A new default
credential may create operational coupling with the production inbox,
and it has not been established as a suitable independent migration
administrator.

## What must be demonstrated BEFORE any shared DB write

1. Identify an actually **independent trusted migration principal**
   available for this Render instance; the app's `sendro_user` is not
   acceptable to provision its own separate registry owner. Establish
   object-owner role creation provenance and the relevant grantor/admin
   memberships without printing credentials or guest data.
2. Confirm the two backend services' *actual* database identities privately;
   no assumptions based on the inspection connector or defaults.
3. Prove the independent principal can create the owner and controlled
   schema without granting membership or schema ownership to
   `sendro_user`. Do this first on an isolated production-shaped clone.
4. Confirm how Render credential management would affect production and
   staging URLs, automatic deployments and any Blueprint references.
   Do not change existing credentials or default users.
5. Rehearse the exact migration/role setup on an isolated PostgreSQL 18.3
   restore with synthetic/private secure controls, plus no-loss
   failure/recovery verification. CI fixture success is **not** sufficient.
6. Take a fresh restorable backup immediately before the approved operation.
7. Request **separate specific approval** for role provisioning and creating
   an **empty** dedicated registry. No WhatsApp account mappings, routing
   switch, historic GDPR mapping, or production promotion are implied.

**If only the current `sendro_user` can administer roles on the instance:**
STOP; do not run the dedicated-schema SQL and do not weaken ownership
requirements to make it pass. Review a genuinely separate security
boundary/managed administrative path and its no-outage impact instead.

The existing Sunset Oia WhatsApp functionality must remain unchanged.
