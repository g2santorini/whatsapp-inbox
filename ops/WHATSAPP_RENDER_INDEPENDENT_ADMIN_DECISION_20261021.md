# Render WhatsApp registry — independent administrator decision (2026-10-21)

**Status: STOP for all shared Sendro PostgreSQL writes.** Read-only
verification completed. Local real-backup clone registry installation,
reader ACL and original-restore preservation were confirmed on
2026-10-21, and its portable PostgreSQL 18 instance was stopped.
No live Render schema, user, routing, credential, ACL, backup schedule
or production service has been modified by this investigation.

## Confirmed facts from the shared Render database

Safe `pg_catalog` queries executed via the Render *read-only* Postgres
connector on database `sendro` (PostgreSQL 18.3):

- The connection identity is `sendro_user`, the owner of the database
  and its `public` schema, with `CREATEROLE`, `CREATEDB`, database
  `CREATE` and `LOGIN`. It is NOT a superuser.
- Existing non-system LOGIN roles:
  `sendro_user`, `postgres`, `primaryuser`, `render_conn`,
  `datadog`. `postgres` is a **platform** superuser: its credentials,
  accessibility and willingness of Render to run privileged operations
  for us are **unknown**. Do not try to connect with it.
- Among observed non-superusers, ONLY `sendro_user` currently has
  `CREATEROLE`. `primaryuser`, `render_conn` and `datadog`
  lack both `CREATEROLE` and database `CREATE`.
- `sendro_user` has no direct role memberships at inspection time.
- The proposed private registry roles, schema and table still
  **do not exist** on Render.
- All observed current Sendro database client connections in
  `pg_stat_activity` were under `sendro_user`, with empty
  `application_name`. This is circumstantial evidence, NOT proof
  of which connections came from the production vs staging backend.

The new catalog-only script:
`ops/db/20261021_whatsapp_registry_ROLE_INDEPENDENCE_READ_ONLY.sql`
can repeat the role/membership/schema checks without reading data,
passwords or connection strings. It is read-only and cannot certify
a role creator's history or Render service DATABASE_URL identities.

## Confirmed service metadata (no secrets)

- `sendro-backend` uses branch `main`, automatic deployments enabled.
- `sendro-backend-staging` uses branch `dev`, automatic deployments enabled.
- Both use the same existing Render Postgres instance.
- The Render service-details API available here does not expose
  individual service environment variables or current DB URL usernames.
  We did NOT pull secret environment values, inspect customer messages,
  run a service shell, restart services or issue live Meta traffic.

## Blocker and legitimate possible paths

PostgreSQL 18 explicitly documents that when a non-superuser with
`CREATEROLE` creates a new role, it receives `ADMIN` on that role.
It can then grant itself `SET TRUE`. Therefore **creating the
supposed independent owner as `sendro_user` would break isolation.**
See: https://www.postgresql.org/docs/18/role-attributes.html

**Preferred first:** Obtain Render's advice on a supported method to
create an independently administered NOLOGIN object owner and reader
without changing default credentials or existing application
connections. It may require Render support / a platform-controlled
administrative action. This is NOT confirmed available.

**Potential fallback (NOT approved):** A **new Render-managed
credential** dedicated solely to offline migrations, which would
become the database's **new default user**. Render says previous
users remain valid, but Blueprint dynamic connection-string references
update on the *next Blueprint sync*, and old-default credential
visibility changes. Critically, whether a newly provisioned managed
user actually gets `CREATEROLE`, schema ownership / CREATE authority,
and appropriate trust separation is **unverified** on this instance.
Do not create the credential to test casually. Before requesting
approval, confirm all service env sources, Blueprint usage, migration
principal capabilities, precise grants, rollback and operational risk.
See: https://render.com/docs/postgresql-credentials

**Architectural fallback:** an independent Render PostgreSQL service
could isolate credential administration, but brings costs, cross-DB
referential integrity limitations, authentication and routing
complexity. Requires a separate technical design and cost approval.
Do not create or deploy one opportunistically.

## Proposed support inquiry — copy into Render support ticket

Subject: Safe independent PostgreSQL role owner without rotating
current default credentials

Hello Render team,

We operate two Python services (production and staging) connected
to the **same** Render PostgreSQL 18 instance. Our original database
user owns the database and public tables and has CREATEDB/CREATEROLE.
Existing services must continue to use their current credentials
with **no interruption or automatic connection-string change**.

For a new, currently inactive, empty WhatsApp account registry in a
private schema, we need an independently provisioned NOLOGIN owner and
a restricted, separately administered read-only reader. The registry
owner must not be created by the existing application role, because
PostgreSQL 18 gives CREATEROLE creators ADMIN membership on roles
they create.

1. Can Render support safely provisioning these roles via a
   platform-controlled independent administrator, without making
   a new default credential or changing current connection URLs?
2. If our only supported option is a new managed database credential,
   which PostgreSQL attributes and memberships does it receive by
   default (especially CREATEROLE, CREATEDB and SET ROLE)?
3. Does creating a new default credential **immediately** change
   existing service environment variables or connection URLs, or
   only on subsequent Blueprint sync? What audit/checks should
   we perform first?
4. Can the resulting isolated migration principal have targeted
   DB CREATE privilege and the private NOLOGIN role's SET ability,
   without access being granted back to the existing app principal?
5. Is there any supported zero-downtime method you recommend for
   this role-provenance/permissions scenario?

This is a technical inquiry only. **Please do not change our
database credentials, roles, ACLs or services** without explicit
confirmation and a reviewed change plan.

Thank you.

## Clear go/no-go rules

- Need independent trusted provisioning path confirmed and the
  production and staging real connection roles resolved PRIVATELY.
- Need fresh verified and restorable backup immediately before
  any real database DDL/ACL operation.
- Review exact role creation, schema install, GRANTs,
  deployment/reference effects and rollback/no-loss recovery.
- Require **new, explicit owner approval** for creating new roles,
  adding grants and creating the empty `sendro_whatsapp` schema/table.
- No tenant mapping, WABA verification, real Instagram/TikTok routing,
  Meta calls, production promotion or historical guest-data migration
  is authorized or part of this decision.

**STOP if independent role ownership is not feasible.** Do not
weaken the checks, use the previous public-schema migration, or
create roles through the legacy application role to get unstuck.
