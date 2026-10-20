# WhatsApp registry: separate-schema empty-table installation proposal

**Status 2026-10-20: engineering proposal and ephemeral PostgreSQL 18.3 CI ONLY.
NO Render/shared staging+production DDL/DML or role change is authorized.**

## Proposed change (competes with the old public-table proposal)

Proposed operator-only SQL:
`ops/db/20261020_whatsapp_registry_DEDICATED_SCHEMA_MANUAL_ONLY.sql`.

This is a **replacement architecture** for
`ops/db/20261020_whatsapp_verified_destinations_MANUAL_ONLY.sql`,
**not** an additional migration. Never apply both scripts. The prior
`public.sendro_whatsapp_verified_destinations` table does not exist on
Render at the last metadata-only inspection.

After specifically authorized prerequisite role provisioning and grants,
a trusted migration session first creates the schema **AUTHORIZATION**
the dedicated NOLOGIN owner, then uses `SET LOCAL ROLE` to create all remaining
objects as that owner **inside the same atomic transaction**. The restricted
owner itself does NOT receive database-wide CREATE privileges. It creates ONLY:
- schema `sendro_whatsapp` owned by `sendro_whatsapp_registry_owner`;
- empty `sendro_whatsapp.verified_destinations` with FK/reviewer/immutability
  protections and an account lookup index;
- owner-controlled trigger functions (explicit EXECUTE revoked from PUBLIC);
- `USAGE` on new schema and SELECT on **only four metadata fields** to
  `sendro_whatsapp_registry_reader`.

No account mapping, guest data, old conversation ownership mapping or
message storage is migrated or seeded. No application route imports the
new adapter. No WhatsApp webhooks, statuses, media, templates or sending
behavior change. **No INSERT/UPDATE/DELETE/TRUNCATE/DDL permission is
granted to any online reader**, and no attestor/revoker permission is granted
in this initial SQL. Separate, evidence-backed human workflows will need
their own later approval.

The future read-only adapter
`load_dedicated_whatsapp_registry()` is inert and distinct from the earlier
public-table test adapter. It reads only the four columns needed by the
routing query (three projected and `revoked_at` in the filter). Failure to
read, empty mappings and duplicate/malformed data must fail closed.

## Critical role preconditions — not solved by this migration

- Establish who controls a **trusted independent migration principal** with
  database CREATE and authority to provision/set the dedicated owner role;
  separately provision the NOLOGIN owner and reader roles, plus restricted
  `REFERENCES` grants on pre-existing tenant/membership tables.
- Never create the registry under `sendro_user`; the inspected role has
  `CREATEROLE`, `CREATEDB` and schema creation rights and must not
  become a member/controller of the new owner role.
- Investigate what privileges Render permits for provisioning a truly
  independent owner. If the only available operator is `sendro_user`,
  **STOP**: do not work around the role-separation gate by running the older
  public schema DDL, weakening the checks, or changing live credentials.
- The future reader needs separate credentials and configuration; neither
  current staging nor production app has been switched to it.
- No privilege reduction, password change, IP ACL change, or restart of
  the existing Sendro connections is part of this phase.

## CI test matrix (synthetic only)

A **new, independently started** disposable PostgreSQL 18.3 GitHub CI job
(\`sendro_wa_private_ci\`, localhost 55443) replays the exact new SQL
under synthetic roles with no Render network access. It intentionally does
not share the older public-registry test database, so old synthetic objects
cannot create false-positive migration collisions:
1. Confirm seven source column types and membership key, and no schema
   name collision via catalog-only SELECT.
2. Attempt DDL without required REFERENCES. It must fail transactionally
   and **leave no new schema behind**.
3. Provision REFERENCES in the disposable DB, replay exact SQL, assert
   zero rows and distinct NOLOGIN object ownership.
4. Test a restricted separate reader login can resolve an empty registry
   (fails closed) but cannot see evidence/reviewer fields, write rows,
   disable triggers, TRUNCATE, SET ROLE owner or change schema.
5. Test a separate high-privilege synthetic *legacy* login cannot mutate,
   own or grant itself access to the independent registry.
6. Attempt exact migration a second time; require failure with no changes.
7. Re-run the read-only catalog audit to confirm the new schema/table exist
   only in CI and that migration collision detection now blocks rerun.

Tests deliberately do NOT assert Meta/GDPR owner evidence verification,
real account registration or real staging/production functionality.

## Separate live decision gates (not yet authorized)

A. Verify current private staging and production connection role identities
without revealing URLs, secrets or customer data.
B. Verify what independent controlled role provisioning Render supports.
C. Rehearse a production-shaped restore and all migration/privilege steps
on an **isolated non-Render-shared clone**; validate fail-closed rollback,
permissions and non-impact to the legacy inbox. The synthetic GitHub
test is necessary but not a production-shape rehearsal.
D. Take a **fresh** verified, independently restorable backup at the
time of the actual proposed write. The 2026-10-20 restore test is not a
guarantee of later recovery-point freshness.
E. Confirm metadata-only preflight
`ops/db/20261020_whatsapp_registry_DEDICATED_READ_ONLY_preflight.sql`
on the correct shared DB and agree on all new roles, privileges,
execution identity, schema names and rollback/no-loss runbook.
F. Seek a **new explicit owner approval naming the shared Sendro database,
the independent role prerequisites, and the creation of the empty schema
and table**. No approval for future WABA mapping or routing is implied.
G. Postflight: check new-object ownership, 0 rows, reader-column SELECT,
no write grants, no start-up migrations; verify the legacy Sendro service
health without sending unapproved real WhatsApp test traffic.
H. Later separate approvals: evidence-backed Sunset Oia WABA/Phone mapping,
real webhook/worker activation, historical GDPR mapping and production cutover.

**Rollback:** uncommitted DDL aborts atomically. A committed DDL rollout
cannot simply be undone by restoring an old snapshot without losing newer
guest traffic. Never use `DROP SCHEMA CASCADE`, `DROP TABLE`,
`TRUNCATE`, `pg_restore --clean` or broad role revocations on the
shared database as an automatic rollback. If approved empty objects
are created, no incoming webhook uses them; containment can remain
a dark feature while a separate, reviewed forward repair is prepared.
