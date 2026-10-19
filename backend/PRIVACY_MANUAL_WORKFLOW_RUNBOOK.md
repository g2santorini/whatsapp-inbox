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
