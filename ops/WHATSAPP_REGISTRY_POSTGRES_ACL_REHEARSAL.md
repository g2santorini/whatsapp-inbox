# WhatsApp destination registry — PostgreSQL privilege separation rehearsal

**Status: CI-ONLY design/testing; not a Render migration, no live permissions changed.**

## Why this gate exists

The 2026-10-20 metadata-only Render preflight found a structurally compatible
registry schema, but the inspected `sendro_user` principal can create tables
and owns the `public` schema. A table owned by the live inbox principal is
not protected against that same principal disabling its triggers or using
`TRUNCATE`. Avoid changing this existing principal or its legacy privileges
while customer WhatsApp is operating.

## Proposed separation (NOT deployed)

| Principal | Purpose | Proposed registry privileges |
| --- | --- | --- |
| controlled migration owner | owns table and trigger functions; not an API login | CREATE/ALTER in a controlled migration session |
| WhatsApp runtime reader | loads only account routing metadata | SELECT limited to WABA ID, destination Phone Number ID, tenant ID and revoked_at |
| human-controlled attestor | manual, independently verified account attestation | INSERT only, plus minimal reviewer account and membership read |
| human-controlled revoker | separately authorized one-time revocation | SELECT(phone_number_id,revoked_at), UPDATE(revoked_at) only |

The owner is **NOLOGIN** in the synthetic test; creating objects under that
role uses a privileged, isolated bootstrap session. That CI bootstrap is
not analogous to giving the live application superuser privileges. Separate
synthetic login connections test runtime, attestor and revoker independently,
rather than merely switching roles on a privileged live connection.

## Automated, no-customer-data rehearsal

- `backend/tests/test_whatsapp_destination_privileges_postgres_ci.py` runs
  against the dedicated ephemeral GitHub PostgreSQL 16 service
  `sendro_wa_acl_ci`, localhost TCP port 55441 only.
- The test refuses any database host, username, port, database or approval
  gate that does not exactly match the disposable GitHub Actions configuration.
  No `DATABASE_URL`, Render connection or Meta credential is used.
- The test replays the **unchanged** manual registry SQL under the synthetic
  object owner, then applies synthetic GRANTs for role capability tests.
- The runtime reader cannot INSERT, UPDATE, DELETE, TRUNCATE, ALTER, CREATE,
  assume the owner role, or read evidence UUIDs, reviewer user IDs or membership
  tables. The metadata-only adapter works with the restricted projection.
- The attestor can attest with eligible synthetic owner/admin membership, but
  cannot edit/revoke/delete. Ineligible operator/disabled reviewers and duplicate
  destination account IDs must fail transactionally.
- The revoker can update only `revoked_at`, one time, cannot rewrite tenant or
  evidence, and cannot restore a revoked mapping. Runtime routing then
  **fails closed** for the revoked-only registry.
- The three login roles cannot create objects in `public`, grant themselves
  ownership or acquire admin/role-management capabilities.

## Important limitations (NOT rollout clearance)

1. CI uses PostgreSQL 16 synthetic schema; shared Render is PostgreSQL 18.3.
   Passing CI cannot verify live credentials, role memberships, grants,
   default ACLs, schema owner privileges, Meta ownership or a production rollout.
2. Existing Sendro staging and production backends share a database. Simply
   introducing restricted roles in test code **does not change the current
   broad privileges of their live database connection principal**.
3. A trigger validates account-role membership at **time of attestation**.
   An independently documented evidence review, secure operator workflow and
   handling of later employee-status changes remain outstanding.
4. It is not sufficient to revoke registry table grants from `sendro_user`
   while that principal still owns the object/schema or retains the ability to
   obtain the registry owner's role. Production roles must be explicitly
   audited; the final design may require a **dedicated schema**, owner role,
   constrained migration operator and independent connection credentials.
5. Any restriction on existing `sendro_user` privileges could break today's
   production code. Do **not** perform such changes in the shared database
   without an isolated production-shape rehearsal, no-outage migration/cutover
   plan, fresh restorable backup and specific human approval.
6. PostgreSQL table or trigger protections cannot replace operational access
   controls, logging, account evidence verification or signed-webhook checking.
7. No manual account registration, GDPR history mapping, Meta request, webhook
   switch or main/production promotion is authorized by this document.

**Decision gate:** The existing `ops/db/20261020_whatsapp_verified_destinations_MANUAL_ONLY.sql`
remains BLOCKED for Render. Explicit approval to create an empty table must
be separate from approval for real account attestation and live routing.
