# WhatsApp verified destination registry — review gate, 2026-10-20

**Status: proposal + CI-only PostgreSQL verification. NO LIVE CHANGE AUTHORIZED.**

The proposed table `sendro_whatsapp_verified_destinations` is not deployed.
The corresponding read-only adapter is **not imported by** the current
WhatsApp webhook or any API route. Neither the new registry nor active
multi-tenant WhatsApp routing is available to operators in Sendro today.

## Purpose

One reviewed, evidence-backed, revocable ownership record per Meta WhatsApp
Phone Number ID, jointly identified by its WABA ID and Meta Phone Number ID.
A WABA may hold several phone numbers. The same phone ID must NEVER be
silently reassigned between tenants. The table does not contain customer
phone numbers, message bodies, provider credentials or WhatsApp access tokens.

**These are separate concerns:**
- The Meta portfolio holding a WABA is **not automatic legal GDPR controller
  verification**. The controller/operator must attest the precise scope.
- An authenticated Meta webhook tells us its claimed receiving account, but
  account-to-tenant authorization must come from the reviewed server-side
  registry, not from customer phone, user ID or the number of current tenants.
- New-message destination routing **does not retroactively verify** 25,511
  legacy conversations or permit historical backfill.

## Assets in this PR

- `ops/db/20261020_whatsapp_verified_destinations_READ_ONLY_preflight.sql`:
  **catalog-only** PostgreSQL preflight. Checks seven required column types,
  the composite tenant membership key, and table/function/index name collisions.
  No customer rows or metadata about actual WhatsApp accounts are selected.
  A pass is **not** permission to perform DDL.
- `ops/db/20261020_whatsapp_verified_destinations_MANUAL_ONLY.sql`:
  **manual-only** PostgreSQL proposal, creates an empty table, rejects inactive
  or non-owner/admin reviewers **including disabled application users**,
  prevents ownership/evidence edits/deletes, and permits exactly one
  irreversible revocation.
- `backend/app/whatsapp_verified_destination_registry.py`:
  metadata-only read-only SELECT limited to at most 1,024 reviewed, non-revoked
  destinations. Returns immutable `{(waba_id, phone_number_id): tenant_id}`
  in memory, throws on empty/invalid/duplicate mappings. No connection
  creation, HTTP route, webhook import, writes or credentials.
- `backend/tests/test_whatsapp_verified_destination_postgres_ci.py`:
  exercises the exact operator SQL in the **dedicated disposable GitHub CI
  PostgreSQL** service, extending only synthetic test fixtures.
  Independently tests two owners, inactive/non-admin/**disabled** reviewer rejection,
  cross-tenant duplicate ID denial, immutability, revocation, transaction
  rollback and the inert read-only resolver.

## Live read-only preflight — 2026-10-20

A read-only metadata inspection of the designated Sendro workspace/database
reported PostgreSQL 18.3, all seven expected prerequisite column types,
the required composite tenant membership key, and **no destination registry,
reviewer functions, or proposed index name collisions**. The proposed schema
preflight therefore passed. This is **not** an installation/rollout approval.

**Security stop gate discovered in the same read-only inspection:** the
inspection/database role can create objects in the `public` schema and has
broad administrative capabilities. Whoever creates the registry owns it and,
as owner, can bypass row-level trigger safeguards (for example by TRUNCATE or
changing the schema). No immutable-registry claim is justified merely because
trigger-based synthetic tests passed. Confirm privately which database role
each live backend uses; do not print connection strings or credentials.

**Do not execute the manual registry DDL yet**, even with a compatible schema,
until a concrete role/permission design has been independently reviewed:
- A dedicated, controlled migration/ownership principal rather than an
  ordinary webhook/API runtime principal should own the registry.
- The live inbound/outbound runtime should have the minimum read privileges
  actually required (not owner, DDL, TRUNCATE, UPDATE or DELETE privileges).
- Manual attestation/revocation requires a separately authorized path,
  with independent evidence review, auditable operator controls and a
  demonstrated fail-closed response to privilege failures.
- Check actual role memberships, schema/table/default ACLs, and both
  staging and production connection roles. Default ACLs owned by another
  grantor **do not automatically apply** to a new table made by this role.
- Rehearse the intended role grants and negative privilege tests solely in
  disposable PostgreSQL. Do not change existing shared database roles or
  revoke their legacy privileges without an independent no-outage plan.
- A fresh, restorable backup and a separate, explicit empty-table creation
  approval remain mandatory even after the privilege design passes.

No WhatsApp account was registered, no legacy mapping was created, and no
shared-database DDL/DML was run during this inspection.

## Before *any* shared-DB step (requires NEW permission)

1. Collect restricted original Meta WABA/phone ownership evidence and signed
   controller confirmation, with dates and legal/operational relationships;
   do not put secret tokens, guest screenshots or private evidence into GitHub.
2. Independently verify the **current** WhatsApp security settings and both
   staging/production configurations. A previous Shell result from staging
   cannot prove production settings.
3. Run `ops/db/20261020_whatsapp_verified_destinations_READ_ONLY_preflight.sql`
   against the correct **shared** Render database using a read-only connection.
   Require `transaction_read_only=on`, `matched_columns=7`,
   `composite_membership_key_present=true`, and `schema_preflight_pass=true`.
   It checks `users.disabled` alongside the tenant/membership columns,
   exact ID types and new-object name collisions. Stop on any mismatch.
   Inspect deployment role privileges/default ACLs separately: a catalog pass
   does not prove least privilege. Capture only metadata and aggregate counts,
   never guest or Meta account records.
4. Take a new verified restorable backup of the **shared** staging/production
   PostgreSQL and rehearse restore on an isolated clone.
5. Require a separate explicit approval to **create an empty table**, distinct
   from the separate, later approval for registering a real WhatsApp Phone
   Number ID or enabling any routing. Existing GDPR ownership-link table is
   another independent dataset and must remain untouched.
6. For each proposed real destination registration, require evidence UUID,
   verified tenant, active owner/admin reviewer, WABA/Phone pair and written
   exceptions procedure; no company inference from user ID, customer ID or
   account name. Never seed on service startup.
7. Only after full signed-webhook, status, reaction, media, outbound/template
   and no-loss rollback rehearsals on isolated PostgreSQL consider a new
   opt-in rollout at staging. Production requires a **separate** later go/no-go.

## Explicitly unsupported and intentionally blocked

- No direct real business mapping inserted into the registry.
- No historical privacy ownership links inserted (last independently checked
  count: 0).
- No real webhook signature flag changed and no live route integrated.
- No GDPR erasure or automatic tenant grants.
- No easy "transfer the number" by editing a row. An actual account transfer
  needs a new independently approved design (possibly a separate versioned
  history model), not bypassing the immutability guard.
- Admin/DB owner can technically bypass DB triggers or TRUNCATE; production
  permissions, audit, operations and access controls must also be reviewed
  separately. The registry must not be writable by an ordinary inbox agent,
  and evidence UUIDs require external human verification: a valid UUID does
  not independently prove ownership.
- Membership status is verified at attestation time; changing a user's status
  later does not silently alter or reassign an existing ownership record.
  Account revocation is a separately authorized action.

## Rollback and failure behavior

The CI job discards its entire PostgreSQL service after the test. Bad inserts
and multi-row transactions rollback atomically. **Do not use DROP TABLE or
TRUNCATE on the shared database to undo a migration.** If manual table
creation is eventually approved and applied, the rollback must be reviewed
beforehand with a verified backup and dependency audit. Revocation preserves
metadata but is not a data deletion.

**Next engineering milestone:** account-scoped runtime paths for webhook
ingress, idempotent delivery, statuses, reactions and outbound, fully staged
with durable retry/quarantine. The current live WhatsApp flow remains legacy
single-business behavior until the owner authorizes a safe migration.
