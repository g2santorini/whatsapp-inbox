# Sendro WhatsApp multi-tenant — privileged-role cutover plan (DESIGN ONLY)

**2026-10-20 status: NO SHARED-DB MIGRATION AUTHORIZED.**
This is an explicit, reproducible plan, not an operator command to execute.

## What was actually verified (read-only, on Render)

Workspace: Sendro. PostgreSQL instance: sendro-postgres (database `sendro`,
PostgreSQL 18.3). Catalog schema preflight was green (7/7 required types,
membership composite key, no registry object collisions). The registry remains
**ABSENT**. The inspected role `sendro_user` is LOGIN with `CREATEDB`,
`CREATEROLE`, and `CREATE` in the `public` schema; it is **not SUPERUSER**
and has **zero directly granted role memberships**.

These are the privileges of the *inspection connection*. The Render connector
does not establish the private connection string/username configured in **each**
backend service. Do not infer either backend's actual role from this report.

The old, one-business WhatsApp backend is still running; do not modify its
database role or its grants in this project phase.

## Proposed future trust boundaries (unimplemented)

**Registry control plane**
- A separate restricted schema and table owner controlled via an approved
  migration workflow; owner must not be the routine WhatsApp API runtime.
- Separate independently authenticated, audited human workflows for initial
  account attestation and one-way revocation; authorization and evidence must
  be checked outside the mere existence of an evidence UUID.
- Administrative/database-owner credentials never appear in normal webhook,
  delivery, template, or media worker environment variables.

**Messaging data plane**
- Each future service needs its own minimally privileged credential for
  reviewed destination metadata `SELECT`; no UPDATE/INSERT/DELETE/TRUNCATE,
  schema CREATE, role administration, or ownership privileges.
- Existing legacy production connection remains unchanged until a **separate**
  no-outage application and credential migration has passed production-shaped
  rehearsals. An HTTP request's tenant ID cannot grant cross-tenant DB access.
- Tenant IDs used by new ingress, conversations, messages, reactions, media,
  status and template operations must derive from the verified, signed Meta
  destination pair; not from customer phone or single-tenant defaults.

**Important SQL blocker:** the current
`ops/db/20261020_whatsapp_verified_destinations_MANUAL_ONLY.sql` hardcodes
`public`. It is not a deployable least-privilege rollout for a dedicated
schema. Do not run it on Render and do not implicitly substitute schema
names without a reviewed migration proposal and isolated PostgreSQL 18.3
rehearsal.

## Sequential release gates

| Gate | Work | Live database impact | Status |
| --- | --- | --- | --- |
| A | Metadata-only schema and privilege audits | None | Schema pass; `sendro_user` too privileged |
| B | Independent 14-tenant delivery, identity, replay and ACL tests | None: ephemeral CI PostgreSQL | Test cases added; CI verdict required |
| C | Design schema owner, separation of runtime/attestor/revoker, and secure credentials | None | Proposed, not approved |
| D | Rehearse full production-shaped migration and reversal on isolated restored clone | None on shared DB | Pending |
| E | Verify current production/staging role identities **privately**, backups, isolation, idle connection pool/retries | Read-only review | Pending |
| F | Explicit owner approval to create **only an empty table** with a reviewed role/schema migration | Yes: shared DB DDL | **NOT APPROVED** |
| G | Separate verified Sunset Oia WABA/Phone evidence and explicit mapping approval | Yes: real registry INSERT | **NOT APPROVED** |
| H | Account-scoped webhook/outbound release: isolated pilot then separate production authorization | Yes: behavior changes | **NOT APPROVED** |

In gate E, authorized operators should check role *names* without displaying
DSNs, passwords, tokens, guest records or unredacted environment variables.
For database connectivity, a planned credential rotation must support both
application pools, readiness checks, retries and a no-loss fallback.

## Read-only audit repeatability

`ops/db/20261020_whatsapp_registry_ROLE_ACL_READ_ONLY.sql` reads only
catalog/role metadata about the CURRENT authenticated connection. On today's
shared DB, an absence of the new registry and broad `sendro_user` privileges
should keep `metadata_reader_least_privilege_pass=false`. This is expected:
**do not** relax criteria just to make the result green.

CI verifies that a dedicated narrow reader returns `true` only after
the synthetic registry exists with the correct GRANTs, while privileged
bootstrap, attestor and revoker do not masquerade as that reader.

The existing
`backend/tests/test_whatsapp_destination_privileges_postgres_ci.py` tests
the *exact original* manual DDL in disposable PostgreSQL 18.3 under a
separate synthetic NOLOGIN owner. This is an architectural rehearsal,
not permission to install that DDL in `public` on Render.

## Scale validation vs production capacity

`backend/tests/test_whatsapp_multitenant_postgres_ci.py` now verifies 14
synthetic tenant identities and 15 accounts (one tenant with two phone IDs).
It tests signed ingress, replay idempotency, cross-tenant data separation,
tenant-scoped outbound intent and account-specific status changes.

Passing a 14-tenant **functional** test does not establish database capacity,
infrastructure sizing, latency, rate limits, provider quotas, Meta eligibility,
data privacy compliance, or SLA for 14 paying businesses. Those require
separate observability/load testing and staged rollout.

## Outage and rollback boundaries

- Never revoke legacy `sendro_user` privileges, rotate live passwords,
  update `DATABASE_URL`, change Render IP ACLs, enable feature flags or run
  migrations without new, action-specific approval.
- Confirm a **fresh, independently restorable** backup immediately before any
  later authorized shared-database write (the 20/10 successful restore is a
  proof of recovery tooling, not perpetual recovery-point freshness).
- A single SQL transaction can rollback an unsuccessful *uncommitted* migration;
  this does **not** undo a committed write. Avoid destructive `DROP TABLE`,
  `TRUNCATE` or restoring an old snapshot to undo a live rollout.
- The application fallback should keep existing single-business WhatsApp
  reception and transmission unchanged while future registry functionality
  is dark, and stop routing on unknown/ambiguous accounts.
- Real migrations need an operator-reviewed compatibility matrix, cutover
  windows, monitoring and no-loss recovery playbook approved independently.

**Final rule:** No real account registration, GDPR backfill, Meta calls or
live routing until the corresponding separate release gates are approved.
