# Instagram read-only staging preview (Phase 2G)

This change introduces an optional Instagram navigation entry and separate
responsive preview page in Sendro's frontend. It does **not** alter WhatsApp
conversation components, message send flows, polling intervals (5/15/15s),
existing backend WhatsApp routes, or production `main`.

## What an eligible user can do

1. Open `https://sendro-frontend-staging.onrender.com` and log in normally.
2. Select **Instagram** from the top workspace tabs or the left Channel
   sidebar (mobile: top tab or More menu).
3. The client requests `GET /channels/instagram/tenants`, which returns
   only companies where the current user holds an *active* tenant membership
   and a testing/active Instagram account exists.
4. It shows selected company's Instagram conversations and message history,
   using already reviewed, tenant-scoped read-only GET endpoints.
5. The user may manually click Refresh. There is **no automatic Instagram
   polling** and **no outbound Instagram send/reply functionality** yet.

The first Sunset Oia result is currently an empty list, because no real
Instagram webhook has been accepted. The empty state explains that the
Meta webhook subscription remains OFF and there are no DMs yet.

## Security boundaries

- JWT from existing staging login is used via existing `apiRequest`; never
  paste tokens into browser console screenshots, logs, or chat.
- Tenant IDs come from authenticated backend `/channels/instagram/tenants`
  endpoint, NOT hardcoded tenant 1; the backend still enforces membership
  on each request.
- Media URLs/token-bearing metadata and encrypted webhook payload are
  not sent to the UI.
- Only normal project/workspace users can reach Instagram; developer and
  project_viewer remain restricted to Projects & Tasks through existing
  app active-user checks.
- User cannot send, mark read, archive, assign or edit Instagram DMs.
- No new DB tables, server secrets, Meta App Publish or webhook activation.

## Verification before continuing

- Run GitHub backend regression/tenant-isolation tests and frontend build.
- On staging, log in as a company member, choose Instagram, verify the
  empty-state displays with no console errors; switch back to WhatsApp and
  ensure conversations, message sending and 5/15/15s refresh are unchanged.
- Repeat on mobile to verify Instagram preview and navigation.
- Future: real Meta event sample validation, safe async worker orchestration,
  Instagram outbound send permissions and window rules, then controlled
  Meta App Review/Publish + subscription activation.

Production `main` must remain unchanged until separately approved.
