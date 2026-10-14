# Instagram read-only Inbox API (Phase 2F) — staging only

## Scope

Adds two new **authenticated, read-only** endpoints to the existing Sendro
FastAPI app. WhatsApp endpoints, database tables, existing Inbox, employee
permissions, polling intervals and Meta webhook subscriptions remain unchanged.

- `GET /channels/instagram/conversations?tenant_id=1&limit=50&offset=0`
- `GET /channels/instagram/conversations/{id}/messages?tenant_id=1&limit=50&before_id=...`

Both use the **existing** `get_current_active_user` dependency (bearer JWT,
token invalidation/version, disabled users, password change/MFA gate and
project-only account restriction). The dedicated Instagram API then checks
the caller is an **active tenant member** in `sendro_tenant_users` before
accessing channel data.

All SQL queries are explicitly constrained by `tenant_id` and
`platform='instagram'`, and hide accounts with disabled/pending status.
Requests for another tenant's data fail 403 or 404; an Instagram customer
scoped ID cannot cross tenant or account boundaries.

The API returns only approved conversation/message metadata and text; it
does **not** expose raw encrypted webhook bodies, credential/token fields,
media URLs, WhatsApp phone numbers or WhatsApp message IDs. The `has_media`
field indicates only whether media metadata exists; media rendering will
require a separate securely authorized endpoint.

No frontend changes or new automatic polling calls are introduced in this
phase. No sends, conversation updates or message acknowledgments are possible.

## Current expected staging response

The owner has registered `@sunsetoiasailing` as tenant 1 Instagram account 1,
in `testing` status. The new channel conversation and message tables are
currently empty. A legitimate Sunset Oia tenant member should therefore
receive an empty JSON list from the first endpoint.

Never paste bearer tokens, access tokens or App Secrets into chat.
An unauthenticated request will be rejected; a member from another tenant
will be denied.

## Validation

`backend/tests/test_instagram_inbox_read_api.py` runs entirely against
synthetic SQLite tables with two separate tenants, a third-party WhatsApp
account and a disabled Instagram account. Tests enforce tenant membership
checks, JWT dependency presence, cross-tenant 403/404, pagination, media
redaction and zero access to WhatsApp conversations/messages.

## Remaining before live IG DMs

- Verify actual Meta Login webhook payload formats.
- Build reliable always-running/operational queue processing and alerts.
- Secure tenant-specific outbound Instagram Send API with message window
  policies and credential management.
- Build React Inbox channel UI and replies; keep existing 5/15/15s polling.
- Only then consider Instagram webhook subscription and Meta publication/
  Advanced Access with explicit rollout approval.

**The Instagram ingestion flag and Meta webhook subscription remain OFF.**
