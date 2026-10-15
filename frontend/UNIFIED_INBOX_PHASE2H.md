# Sendro Unified Inbox — Phase 2H (staging-only first step)

**Goal:** the main Sendro Inbox list shows WhatsApp and Instagram
conversations together, in last-message order. Each item is clearly
identified by its channel. This is only the **read-only Instagram stage**;
WhatsApp messaging behavior is unchanged.

## Feature

- `Unified Inbox` tab replaces the old `WhatsApp Inbox` tab label only in
  the regular inbox UI; existing ProjectWorkspace-specific navigation is
  preserved.
- Channel filters `All / WhatsApp / Instagram` are added above the
  conversation views `Open / Mine / Follow Up`.
- `All` merges the already-fetched WhatsApp rows with permitted Instagram
  rows from `GET /channels/instagram/tenants` and per-tenant
  `GET /channels/instagram/conversations`. Each Instagram row has a
  collision-safe key (tenant + account + conversation ID); it cannot
  accidentally be treated as a WhatsApp thread.
- Instagram rows open a separate read-only chat panel using the
  authenticated tenant-scoped Instagram message API. **No Instagram
  send, archive, release, take, or mark-as-read actions exist here.**
- `Mine`, `Follow Up`, and `Archived` remain WhatsApp-only because
  Instagram assignment/reply workflows have not been implemented.
- Instagram messages are fetched on entering the unified Inbox, upon
  explicit channel selection and using the manual refresh button. **No
  Instagram automatic polling** has been introduced. This is a preview,
  not a realtime DM inbox yet.
- Instagram search is **client-side** over the currently loaded Instagram
  guest name, account label, or IG-scoped ID, while the existing WhatsApp
  backend search is left untouched.

## Safety boundaries

- This UI change runs no schema migrations; staging and production share
  a PostgreSQL DB but the new frontend only makes authorized GET requests.
- WhatsApp send, templates, Quick Replies, 24h policy, notifications,
  assignment, status, read receipts and mobile back are not modified
  beyond adding safe channel selection. Existing polling constants
  remain **5 sec active chat / 15 sec inbox / 15 sec summary**.
- The Instagram access token, App Secret, encryption key, raw webhook
  payloads and media URLs are **not** exposed in any frontend API.
- Only companies returned by active membership-scoped
  `GET /channels/instagram/tenants` can be queried, and every follow-up
  request re-verifies membership in the backend. Failed access clears
  cached Instagram rows.
- Instagram webhook subscription and `INSTAGRAM_WEBHOOK_INGESTION_ENABLED`
  remain **OFF**, manual delivery worker locked. There are no real
  Instagram conversations yet.

## Tests and staged rollout

- Run `node --test src/unifiedInboxRows.test.js` for channel filters,
  distinct IDs and no WhatsApp data mutation.
- Run existing backend regression tests and React production build in CI.
- Deploy PR to **dev/staging only**. Manually open staging on desktop:
  `Unified Inbox`, select `All`, `WhatsApp`, `Instagram`. With no
  Instagram DMs, `All` should show existing WhatsApp rows, `WhatsApp`
  the same legacy rows, and `Instagram` an appropriate empty state.
- Check an existing WhatsApp thread opens and can be sent normally.
  Return from Instagram standalone tab and confirm navigation.
- Repeat on mobile to check channel filter, chat navigation and size.
  Verify no unintentional Meta traffic.
- Do not promote to production main without separate owner approval.

## Future (NOT part of this stage)

1. Validate real Instagram Login webhook event envelopes.
2. Add monitored, fail-safe background processing, account credential
   lifecycle, and tester-only controlled ingestion.
3. Add secure Instagram outbound sending with Meta permissions and
   customer-service-window policy.
4. After tests and approval, enable live real-time Instagram messages.
   At that point upgrade Instagram refresh from manual to a properly
   budgeted real-time strategy without changing WhatsApp polling.
