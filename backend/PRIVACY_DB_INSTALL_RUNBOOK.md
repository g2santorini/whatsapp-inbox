# Sendro GDPR request tables — pre-installation runbook

**Status:** Planning only. Not authorization for a database schema write.
**Environment:** `sendro-postgres` (Frankfurt). The dev/staging and main/production backends currently use the **same** database. Running the SQL affects production data structure even if done while viewing staging.

## Read-only preflight already completed — 2026-10-17

Using the Render PostgreSQL read-only query connector:
- Database `sendro` — PostgreSQL 18.3.
- Server reported `transaction_read_only=on`.
- All **7 of 7** prerequisite columns were present.
- Composite tenant membership key was present.
- Both GDPR request tables and the audit trigger function were absent.
- No rows were updated and no DDL was issued.
- The GDPR case/API code from PR #40 is present on `dev`, but its router is **not mounted** in `main.py`; the manager is not live.

Reusable metadata-only SQL: `ops/db/20261017_privacy_cases_READ_ONLY_preflight.sql`.
It returns counts, not actual customer information.

## Backup and human approval gate

The owner reported that the Render database export had finished. **This is not independent verification** that a downloadable archive was saved or can be restored.

Before considering any migration:
1. Confirm the new export is marked completed in Render **Recovery → Logical backups**.
2. **Download** the `.dir.tar.gz` file to a secure local location; verify a sensible nonzero file size. No password or customer backup should be uploaded to ChatGPT or checked into GitHub.
3. Optionally validate gzip/tar integrity with a read-only archive listing (`tar -tzf FILE.dir.tar.gz`) on the owner's own computer. For real restore confidence, rehearse restoration to an **isolated empty PostgreSQL 18 instance**, never to the live Sendro DB. Restoring to an additional Render database could incur costs: confirm with owner first.
4. Verify the recovery plan, backup timestamp and scope; keep connection strings private.
5. Obtain **separate, explicit owner approval** for applying `ops/db/20261017_privacy_cases_MANUAL_ONLY.sql` to the shared DB. The earlier read-only audit authorization and completed export do **not** constitute write authorization.
6. Stop if the read-only preflight differs (columns missing, duplicate privacy objects, unexpected schema drift), if export is unverified, if service health is unstable or if there is any missing approval.

## Execution and postflight design — NOT EXECUTED

- Manual operator-only migration is in `ops/db/20261017_privacy_cases_MANUAL_ONLY.sql`.
- Ensure bounded locks/timeouts; database DDL is transactional. Abort on any error.
- Do not run auto-migration at API boot, and do not grant front-end access during schema application.
- After an authorized migration, use read-only catalog checks for two new tables, FK constraints, indexes, and the trigger. Keep the API router **unmounted** pending a separate auth/endpoint readiness review.
- Audit events are designed as append-only. Never test DELETE/UPDATE against real audit records; only test in disposable PostgreSQL.
- Do not run `DROP TABLE`, `TRUNCATE`, manual record deletion, or destructive `pg_restore --clean` on a live DB as a "rollback." A full database restore changes customer data and requires its own incident/recovery authorization.
- App changes must be promoted from `dev` to `main` **separately**, after verified migrations, tenant membership, security review and acceptance testing.
- This release does not erase guest messages or enforce the proposed 12-month retention. It only builds the future privacy-request workflow.

## Render documentation

Render Postgres exports are compressed directory backups (`.dir.tar.gz`) and are retained by Render for **seven days**; download them for longer-term storage. Point-in-time restore provisions a new database and is a distinct recovery option:

https://render.com/docs/postgresql-backups
