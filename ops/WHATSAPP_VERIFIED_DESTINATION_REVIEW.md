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

- `ops/db/20261020_whatsapp_verified_destinations_MANUAL_ONLY.sql`:
  **manual-only** PostgreSQL proposal, creates an empty table, rejects weak
  reviewer membership, prevents ownership/evidence edits/deletes, and permits
  exactly one irreversible revocation.
- `backend/app/whatsapp_verified_destination_registry.py`:
  metadata-only read-only SELECT limited to at most 1,024 reviewed, non-revoked
  destinations. Returns immutable `{(waba_id, phone_number_id): tenant_id}`
  in memory, throws on empty/invalid/duplicate mappings. No connection
  creation, HTTP route, webhook import, writes or credentials.
- `backend/tests/test_whatsapp_verified_destination_postgres_ci.py`:
  exercises the exact operator SQL in the **dedicated disposable GitHub CI
  PostgreSQL** service, extending only synthetic test fixtures.
  Independently tests two owners, inactive/non-admin reviewer rejection,
  cross-tenant duplicate ID denial, immutability, revocation, transaction
  rollback and the inert read-only resolver.

## Before *any* shared-DB step (requires NEW permission)

1. Collect restricted original Meta WABA/phone ownership evidence and signed
   controller confirmation, with dates and legal/operational relationships;
   do not put secret tokens, guest screenshots or private evidence into GitHub.
2. Independently verify the **current** WhatsApp security settings and both
   staging/production configurations. A previous Shell result from staging
   cannot prove production settings.
3. Do a read-only schema check of `public.sendro_tenants` and
   `public.sendro_tenant_users` (member_role/is_active requirements), existing
   indexes, row counts and migration name collisions. Stop on drift.
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
- Admin/DB owner can technically bypass DB triggers; production permissions,
  audit, operations and access controls must also be reviewed separately.

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
