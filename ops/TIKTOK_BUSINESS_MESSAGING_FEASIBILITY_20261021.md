# TikTok direct messages in Sendro — official API feasibility (2026-10-21)

**Status:** research/design only. No TikTok app registration, access approval,
account linking, API call, webhook subscription, customer-data access,
database migration, new Render service or production change.

## Product scope

The Sendro requirement is **private customer-to-business TikTok DMs only**,
not video comments, follower analytics, paid-ad event tracking, or
outbound cold-message automation. A single Inbox may eventually display
WhatsApp, Instagram and TikTok as separate channel identities without
collapsing unrelated customer identifiers.

## Verified official TikTok references

TikTok *does* document an **API for Business / Business Messaging API**
for authorized business accounts; it is NOT equivalent to the general
TikTok Login Kit, Display API or an unofficial scraping endpoint.

- Official developer entry and steps (Business account, developer
  registration, developer app, product access, authorization, subscribe
  to Business Messaging Webhook events, authentication, first call):
  https://business-api.tiktok.com/portal/docs/business-messaging-api-get-started/v1.3
- Official overview: authorized Business Accounts exchange direct
  messages via integrated platforms; real-time messaging includes
  messages and media:
  https://business-api.tiktok.com/portal/bm-api/education-hub
- Official product/API directory lists endpoints for conversation
  listing, message listing, send-message, media transfer, account
  capability checks, and Business Messaging webhook management:
  https://business-api.tiktok.com/portal/docs?id=1736271785207810
- Official TikTok Messaging Partners guidance explicitly mentions
  TikTok direct messages in multichannel Inbox tools and warns that
  partner authorization grants conversation/webhook permissions:
  https://ads.tiktok.com/resources/help/article/about-message-management-tools?lang=el-GR
- Business Center DM permissions documentation:
  https://ads.tiktok.com/resources/help/article/how-to-grant-users-permissions-to-manage-direct-messages

The generic Business Messaging API get-started guide lists a
10 QPS endpoint rate limit. That is **not** a verified quota for the
specific Sendro developer account, nor proof of eligibility.

## Unverified prerequisites: do NOT infer authorization

1. Is a TikTok for Business developer registration available/approved
   for the intended Sendro operating entity and use case?
2. Is the **Business Messaging API product** enabled and allowed for
   this developer account, Greek/EU business account(s), and specific
   connected TikTok Business profile(s)?
3. Does this product support the exact **organic inbound DM** scope the
   owner wants, separately from TikTok Messaging Ads?
4. What privacy/data-security/app review approvals and token scopes
   are required? Confirm current policies **inside the actual app
   console** before planning activation.
5. What webhook event types, delivery/redelivery signature scheme,
   de-duplication identifiers, conversation windows, retention,
   media handling and sending constraints apply to the approved app?
6. Will onboarding via an approved Messaging Partner be required,
   or can Sendro be a directly authorized integration? No partner
   approval has been established for Sendro.

The existence of a documented product and other messaging partners
does NOT mean that this app or business profile has API permission.
Do not label TikTok messaging as integrated or production-ready.

## Safe architecture proposal (no implementation yet)

- **Account authorization:** tenant-bound TikTok business account
  enrollment only after OAuth/permission verification, owner approval
  and duplicate-account safeguards. Store tokens encrypted, never in
  GitHub/CI or chat.
- **Ingress:** isolated `/webhook/tiktok` with signature verification
  specific to TikTok, bounded body size, durable encrypted queue,
  event-type allowlist and 2xx acknowledgement **only after durable
  acceptance**. Do not reuse the Meta signature verifier.
- **Isolation:** partition by `(provider='tiktok', business_account_id,
  scoped_sender_id)`. Never reuse WhatsApp `phone_number_id` or
  Instagram-scoped sender IDs; never map to a tenant from user-submitted
  text. Reject unregistered business accounts.
- **Workers:** at-least-once queue consumption, idempotency across
  provider events/messages, controlled retries/quarantine, dead-letter
  audit, no fallback to another company's pending event, bounded
  synthetic tests before live usage.
- **Inbox:** a separate TikTok badge/filter with tenant-scoped access,
  external media as thumbnails/approved proxy only, no TikTok posting
  or comment-management surfaces.
- **Replies:** a later separate permissioned milestone; uphold
  provider conversation windows and approved message types. No live
  send API until inbound E2E is stable and explicitly approved.
- **Privacy:** agree customer-data retention, erasure/audit scope,
  region/cross-border constraints, and avoid ad-measurement event
  reporting without a distinct explicit business purpose/approval.

## Recommended sequence while the Render registry question is open

A. Finish Instagram synthetic/operational readiness without altering
the shared PostgreSQL database or Meta subscriptions.

B. Ask the TikTok Business developer portal whether **Business Messaging
API** access is offered to Sendro for Greek/EU business profiles,
which permissions or review steps are required, and whether organic
private inbox is covered. No business login or token required for
public-documentation research.

C. With eligibility confirmed, prepare an entirely inert TikTok data
contract/normalizer, fake signed event fixtures and disposable CI tests.
Do not activate any endpoint, make paid service, or configure TikTok
webhooks until separately authorized.

D. Reuse Sendro's multi-tenant security model only after its ownership
provenance / fail-closed routing has been reviewed, not by bypassing
the WhatsApp registry independence gate.

**NO GO:** A separate TikTok approval and an independent integration
design are required before any shared-database DDL, real token,
webhook subscription, live customer DM, or reply operation.
