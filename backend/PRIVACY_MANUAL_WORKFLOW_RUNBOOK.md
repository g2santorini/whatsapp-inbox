# GDPR manual workflow MVP — release checklist

**Source of customer requests:** customers contact the **business** (e.g. Sunset Oia) by email or WhatsApp; no requirement to know Sendro. This MVP does **not** automatically read email, detect STOP, capture customer contact details, send replies, or erase data. Business admins manually register a non-identifying case, manage the external request in their normal secure email/inbox, verify identity only if appropriate, review scope, respond directly, and record that the answer was sent.

### Flow
1. Customer writes to the business. Staff select the correct company in GDPR Manager.
2. Reviewer with active tenant owner/admin role and a **recent signed MFA** token selects **New request**, then only its source (email, WhatsApp, Instagram). No contact info, customer IDs, message text, attachment or subject identity is stored in GDPR case tables.
3. System creates an opaque UUIDv4 case reference and timestamps; staff note that reference in the business's existing restricted email/ticket, not the customer's name in Sendro case notes.
4. Reviewer ticks "Verified outside Sendro" only after checking identity/authority. A case without verification remains open; a real customer request should not be refused solely for lack of unnecessary paperwork.
5. Scope review uses explicit checkboxes for known data categories, holds and retention exceptions; incomplete checks remain blocked. Scope review is *not* proof of erasure or automated discovery.
6. Reviewer responds through the business's channel. Only after actually sending it, records "Response sent" in Sendro. This does not mean all data is erased; responses may explain legal retention grounds and further action.
7. Case timestamps provide one-calendar-month target reminders in UI, with appropriate legal exceptions; no timer auto-completes or deletes anything.

### Safety / gating
- New manual POST endpoints and status GET are **not mounted** unless:
  - existing GET preview staging service-ID and two exact reviewed flags pass
  - SENDRO_PRIVACY_MANUAL_WORKFLOW=reviewed-staging-manual-only
  - SENDRO_PRIVACY_EMAIL_SCHEMA_READY=verified-email-channel-check
- Both additional flags default OFF; frontend checks capability and hides write controls if absent.
- The email column CHECK adjustment is contained in a **manual-only** SQL proposal; it must never be run on startup. This PR must not trigger it.
- Real staging shares production database. No live POST/DDL tests without a separate approval. Test against synthetic SQLite and disposable PostgreSQL only.
- Tenant access is checked server-side on **every** request; JWT fresh MFA required for all POST operations, no PII in case metadata, no writes to guest conversations.
- Append-only audit events; optimistic locking; 10 requests/min per user in this staging-only single-instance limiter; existing no-store middleware covers /privacy paths. Do not claim this is a multi-instance SaaS-grade rate limiter.
- Production main remains unaffected unless separately authorized.

### Non-code compliance work
Privacy notice/contact per business; processor/controller agreement and provider retention policy; customer access/rectification/export/erasure fulfillment outside Sendro; legal review of actual case handling; full audit and disaster-restore tests required before general SaaS rollout. This is case *tracking*, not complete automatic GDPR compliance.

### Optional Phase A: subject metadata preview (separate staging gate)
- `SENDRO_PRIVACY_SUBJECT_PREVIEW=reviewed-staging-metadata-only` is a **third independent opt-in**. Do not set it without review of the PR and separate owner approval. Production cannot mount this route.
- When enabled, a tenant owner/admin with recent verified MFA and a previously manually identity-reviewed case may send an exact **Instagram conversation ID** in the JSON body of a POST to the read-only `/privacy/requests/{ref}/subject-preview` endpoint.
- The body-based lookup avoids customer IDs in the request URL. Exact company membership, GDPR case tenant and Instagram account tenant are checked independently. Every lookup is rate-limited.
- Returns counts of rows in `sendro_channel_messages` and of rows with `media_json`, **never** names, phone numbers, external platform IDs, media bytes, or message text.
- Searches of legacy `conversations` (WhatsApp) are **blocked**; that table has no trusted tenant ID. Do not infer company from staff IDs, telephone number, or the request's stated source.
- The preview is **partial**: it excludes template batches, detached media, raw ingestion data, provider-held copies, logs and backups. It does not authorize or perform erasure. `safe_to_delete_count=0` is invariant.
- The UI's "Related to Sendro?" answer and selected conversation are currently **ephemeral and not persisted**. A permanent GDPR-to-subject link would introduce identifying personal data into the privacy workflow; design a separately restricted relation, purpose, retention policy, audit and migration before requesting approval for a shared-production DB change.
- Never use real identifiers or actual customer records for test requests. Run synthetic isolated SQLite/PostgreSQL tests before enabling on live staging.


### Legacy WhatsApp ownership bridge — proposal only, NOT activated
Read-only Render preflight on 2026-10-19: 25,463 legacy `conversations`, 94,978 `messages`, 27,028 `template_batch_items`; one tenant and **no WhatsApp row in** `sendro_channel_accounts`. Just 709 conversation-creating users currently have one active tenant membership; 24,754 have none. **None of this is proof of record ownership.** The existing `conversations` table has no `tenant_id` or business-account identifier.

Current WhatsApp webhook matches old records by **customer contact phone alone** and writes via a global configured WhatsApp Meta sender. It does not save a verified receiving business account on each conversation. Therefore it is not multi-tenant-safe to infer an owner or bulk-assign old records from phone, user assignment, environment config, or tenant count. This is a hard blocker for turning on legacy preview/erasure generally.

The `ops/db/20261019_privacy_legacy_whatsapp_ownership_MANUAL_ONLY.sql` file is an **unapplied** schema proposal. It creates an **empty** per-conversation ownership map with FK to the precise legacy conversation, tenant, and reviewer; an opaque reference to separately retained evidence; and a revocation timestamp. There are **no migrations at application startup**, no automatic backfill, no live insertion or deletion.

The `SENDRO_PRIVACY_WHATSAPP_VERIFIED_LINKS=reviewed-staging-exact-links-only` environment flag is OFF by default and must remain OFF. It is independent of the staging GDPR subject preview flag. It may be enabled **only** after:
1. Business owner identifies the historical WhatsApp business account(s), date ranges and whether conversation ownership has ever changed. Obtain actual verified operator/controller evidence. No automatic assumption that all records belong to the only current tenant.
2. Explicit approval for the proposed schema change to the production-shared database, fresh verified backup and controlled restore/rollback readiness.
3. Approve a separate *exact-conversation* linkage workflow with an independent evidence reference; double-check verified tenant and business account; investigate phone collisions and any cross-company conversation mixing before linking.
4. Perform isolated synthetic PostgreSQL tests of schema constraints/joins, revoked mapping, cross-tenant access, and existing WhatsApp webhook behavior. Handle future inbound/outbound tenant provenance before general rollout.
5. Separately approve activating the new flag on staging, never on production.

The metadata inspector only counts legacy `messages` and rows with a `media_id` for an exact, separately verified and non-revoked conversation. It excludes unlinked template batches, other potentially associated guest data, provider copies, media storage, logs and backups; **never** claims that such a preview is a complete deletion inventory. All GDPR case-to-conversation relationships remain ephemeral, and `erasure_enabled=false` always.

For legitimate GDPR access/erasure requests meanwhile, keep using the independent manual review and external source-of-truth evidence. Do not report "verified" or "erased" from this preview.
