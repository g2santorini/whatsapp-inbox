# Sendro privacy — retention and erasure engineering plan (2026-10-16)

**STATUS: design and offline-only classifier. NO live retention policy, purge, deletion job, DB migration, production API or Meta approval has been activated.**

## Decisions and limits

- Operator: **George Georgoulas, sole proprietor** (provided by owner; verify exact registered trade details before legal publication).
- Working proposal for ordinary conversation history: **12 calendar months from latest relevant activity**, subject to validated business necessity and legal review. **Not a GDPR-mandated universal number.**
- GDPR requires storage limitation, demonstrable processes, a lawful basis for each processing activity, response to rights requests and possible justified retention exemptions.
- Inactivity alone does not authorize erasure: unresolved customer inquiries, unread/assigned/follow-up conversations, disputes, reservations, legal holds, backup recovery and related records need assessment.
- **Never automatically erase anything solely because this planner says "candidate_for_manual_review".**

Authoritative resources:
- https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/principles-gdpr_en
- https://www.edpb.europa.eu/news/edpb-identifies-challenges-hindering-the-full-implementation-of-the-right-to-erasure_en

## Code-backed data inventory (reviewed against backend/app/models.py and Instagram dev modules)

| Area | Personal/related fields | Notes |
| --- | --- | --- |
| `conversations` | contact_name, contact_phone, assignment, last_message_at, timestamps | Legacy WhatsApp (production). |
| `messages` | message content, media ID/MIME/filename, WhatsApp message ID/status, reactions, timestamps and author | Media may live outside PostgreSQL; verify provider retention and accessibility. |
| `template_batch_items` | guest_name, phone, reservation_number, external_id, operation_date, status, linked conversation/message | Admin deletion currently **unlinks** message and conversation but does NOT delete these rows. |
| `template_batches` | batch_id, label, source, event and related operational fields | May contain names or operational identifiers depending on values. |
| `users` & authentication | staff name, email, roles, passwords hashed, encrypted MFA secrets, device tokens hashed | Staff retention is separate from conversation policy. |
| `projects` / `project_tasks` / comments | descriptions, free-text, author and assignee IDs | Potential incidental personal data; separate legitimate purpose. |
| Instagram `sendro_channel_*` (dev) | platform-specific customer IDs, message content, media JSON, timestamps, encrypted webhook envelopes | Distinct tenant/account ownership; never convert scoped IG IDs to phone numbers. Webhook ingestion is still OFF. |
| Logs, provider records, Render backups | possible identifiers and message/status details | Verify actual logging, hosting/provider access, retention and recovery before making any deletion promise. |

**The existing** `DELETE /conversations/{id}/` **is not a complete data subject erasure workflow.** It removes matching legacy message rows and conversation, but it only clears the linking IDs in template batch items. It does not prove removal of batch fields, outside media, logs, backup snapshots or other legal copies. Archive is not erase.

## Phase 1 (this branch) — inert offline preview

`backend/app/privacy_retention.py` is a pure function module:
- Applies a 12-*calendar*-month cutoff, in UTC.
- Uses the **newest** of creation, update, conversation activity and related-message timestamp (never only an easily stale timestamp).
- Requires explicit verification flags for activity history, other references and legal holds.
- Excludes active, unread, assigned, follow-up, recent, malformed and unknown cases.
- Returns only aggregated reason counts; neither PII nor record IDs appear in results.
- Does not import the application DB or expose a route, scheduler or CLI. It cannot delete anything.
- Unit tests use fabricated records only.

The flags currently default to **not reviewed**. Live DB integration is not included: no evidence about production data is assumed.

## Phase 2 — before any real-data inspection

1. Verify legal controller/processor responsibilities and lawful purposes (including Sunset Oia's role), decide written 12-month retention justified by operational need, and distinguish employee, logs, batches and webhook envelopes.
2. Obtain owner-specific authorization for **a read-only aggregate audit** of the shared database and verify fresh backups, schema drift, table dependencies, latest message timestamps and legal hold handling. Avoid sensitive row-level output.
3. In a separately reviewed feature branch, implement an explicit tenant-aware, admin-only aggregate dry-run endpoint with stable query plans, limits, redacted logging and proof that SELECTs do not mutate records. Integrate only after approval.
4. Build legal-erasure-request workflow: authenticated request, controller confirmation, identity/authority verification, scope analysis, secure audit outcome (minimal metadata), holds/exceptions, redaction where required, and response tracking.
5. Separate **eligible erasure** from long-term archival; schedule deletion only after validated scope, approvals, ability to stop/recover, and tests on disposable PostgreSQL. Rate limit; never use startup auto-purge.
6. For backup restores, maintain a secure, access-limited record of fulfilled deletion instructions and reapply/verify them before restoring the application to service; validate backup retention with Render. Do not claim live/backup instant deletion.
7. Deal with provider-held media and Meta copies distinctly. Document DPA/subprocessor and international-transfer arrangements.

### Release gates
- No testing against the production-shared database before explicit approval.
- No auto-purge or privacy API merged into WhatsApp `main` until owner explicitly approves and backup/rollback evidence is available.
- No Meta submission of draft legal URLs until retention/erasure practices and language are accurate and approved.
- Use CI synthetic fixtures or isolated disposable PostgreSQL only.


## Phase 2A — synthetic PostgreSQL read-only aggregate rehearsal (16 October 2026)

Implemented `app/privacy_retention_pg_preview.py` for **disposable CI PostgreSQL only** and a dedicated integration test. The code requires two explicit GitHub Actions test flags, loopback host, dedicated CI database/user/port and a server-confirmed `READ ONLY` transaction. The caller supplies the connection; there is no runtime engine, route, worker, scheduler or automatic execution. It retrieves counts only, not customer identifiers or contents.

The preview counts legacy conversation age/activity, open or pending conversations, template-batch items linked by either conversation or message, and orphan batch items with neither link. It never declares deletion eligibility, because orphan records, legal holds, provider media/logs, controller responsibilities and backups are not fully reviewed. All tests create **fabricated data only on the ephemeral PostgreSQL CI service**. No live staging or production data is queried or changed.

**Next gated action:** review actual schema and backup readiness, then request separate explicit authorization before **any** aggregate-only query against the shared Render database. This module intentionally refuses to run there. Production deletion/retention enforcement remains OFF.


## Phase 3 — offline GDPR request case-management core (16 October 2026)

The new `backend/app/privacy_erasure_cases.py` provides a **pure, immutable
case-review engine** for simulated data-subject requests. It does not import the
FastAPI app, SQLAlchemy, production database, background worker or any provider.

### Flow (synthetic/offline only)

1. Only an explicitly supplied active admin/owner within the same tenant can
   create/review a case; cross-tenant requests fail closed. The case reference
   must be a random UUIDv4 (NOT a phone number, customer name, Meta ID or email).
2. Identity-check status can be marked only after externally verified evidence;
   this module **does not itself verify identity**.
3. Structured scope checklist: verify controller authority, requester authority,
   tenant boundary, WhatsApp/Instagram messages, template batch data (including
   1,518 unlinked batch records observed in the October 16 metadata audit),
   media, provider-held copies, application logs, backup recovery and legal
   retention exceptions. Unknown checks always block progress. Explicit legal
   holds block even when every other check passes.
4. A complete checklist yields `ready_for_manual_decision` — **not** deletion
   authorization. There is deliberately NO `delete` operation or success state.
5. Responses can only be marked recorded after an **external** confirmation;
   recording a response is not case closure or proof that anything was erased.
6. Every state transition appends an immutable event with only action code,
   internal actor user ID and UTC timestamp. No free-text notes, subject
   identifiers, contact details, message content or media is stored in cases.
7. The non-identifying preview always reports `erasure_enabled=False`,
   `erasure_performed=False` and `safe_to_delete_count=0`.

### CI/release and operational gaps

- All tests are fabricated, offline unit tests. They exercise admin-only
  actions, same-tenant isolation, invalid identity assertions, all missing
  scope checks, legal holds, response tracking, immutable audit, redacted
  previews and chronologically ordered timezone-aware timestamps.
- **No website or actual inbox UI, no API route, no DB persistence or DDL,
  no real customers, no schedule, no production behavior change.**
- The actual request workflow needs *secure* persistence and identity evidence
  storage separated from non-identifying audit events, authenticated role/tenant
  membership from the existing app, controller instructions and access reviews.
- Need a policy on holding/restoring backups and reapplying deletion instructions
  before any production write feature. The live database audit was READ ONLY
  and is not blanket permission to enable erasure.
- GDPR response deadlines and exceptions require review by a qualified advisor
  before sending the final legal pages to Meta. Never claim a simulated request
  has satisfied an actual data-subject rights request.

The existing live admin `DELETE /conversations/{id}/` endpoint is unchanged.
The 12-month retention proposal remains **unenforced** in production.


## Phase 4 — tenant-scoped request persistence and gated REST API (17 October 2026)

**Built as reviewable source + isolated tests. NOT enabled on Sendro staging or
production. NO live database schema changes, retention purge or message deletion.**

Files:
- `backend/app/privacy_case_store.py`: creates and updates non-identifying
  request records, with an atomic append-only audit event per successful
  transition. Role is derived **from active tenant membership AND the not-disabled
  users table** on every operation. No trust in roles supplied by a client.
- `backend/app/privacy_case_api.py`: factory for a private admin REST interface.
  Its authentication and session dependencies must be injected. **It is
  intentionally not imported or mounted in `main.py`.** No production route
  exists yet.
- `ops/db/20261017_privacy_cases_MANUAL_ONLY.sql`: proposed PostgreSQL DDL
  creating privacy cases and audit-event tables. Includes tenant-scoped
  foreign keys, validation, optimistic version tracking, and a DB trigger
  blocking modifications/deletions of audit events. This is a **manual proposal
  only**, never executed on Render.
- `backend/tests/test_privacy_case_api.py`: in-memory SQLite synthetic tests
  for admin/owner membership, tenant boundary, revoked/disabled operators,
  rejected personal-data fields, state transitions, audit sequence, and
  transaction rollback on failure.
- `backend/tests/test_privacy_case_postgres_ci.py`: isolated GitHub Actions
  disposable PostgreSQL test for real SQL migration and append-only protection.
  Hard-gated to the disposable GitHub CI local Postgres host/port/account.

The REST factory offers intake, list, case detail, manual verification
attestation, structured checklist review and external-response attestation.
It intentionally has no free-text input, subject email, phone, name, platform
ID, message content, reservation number, export or delete endpoint. The app
generates a random UUIDv4 server-side. Audit events contain action, internal
actor user ID and timestamp only.

**Human attestation is not an identity-proofing service.** Even when every
checklist item is true, the engine returns `ready_for_manual_decision`, never
an erasure approval. Every preview reports `erasure_enabled=false` and
`erasure_performed=false`. There is no database relationship to actual
customers at this stage, so the module cannot fulfil a GDPR subject request
yet. A later secured evidence vault/verified identity crosswalk, controller
instructions, legal review, customer notification process, log/provider/media
review and backup-restore deletion replay are required.

Release gates:
1. Do not apply the migration to the shared Render database without **separate
   owner approval**, verified backup and tested recovery/rollback procedure.
2. Do not mount the router in `main.py` until migration, auth, RBAC, tenant
   boundary, rate limiting, CSRF/origin protection where relevant, and operator
   workflow have completed staging review.
3. Do not expose real data, permit actual deletion, or promise complete
   erasure until policy, dependencies and backups have been verified.
4. The approved read-only aggregate inspection of the shared database on
   October 16 did not authorize DDL, writes or direct customer reads.
