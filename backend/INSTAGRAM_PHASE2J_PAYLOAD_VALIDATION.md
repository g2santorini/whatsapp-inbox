# Instagram Phase 2J — Payload-Shape Compatibility (2026-10-15)

## Scope
**Offline only**. This PR adds synthetic, Meta-shaped Instagram Login webhook
test cases and narrow fail-closed parser hardening. No live Instagram
traffic, no API credential use, no secret storage, no service start, no DB
schema changes, no WhatsApp changes, no Meta webhook subscription.

The checked-in examples use **fabricated business/customer IDs** and a
fabricated message ID with an Instagram-like prefix. They are *not* genuine
captures or a substitute for verifying our specific Meta app's live payload.

## Relevant references
- Meta's official Instagram Postman workspace (Instagram Login and Send API):
  https://www.postman.com/meta/instagram/overview
  https://www.postman.com/meta/workspace/instagram/documentation/23987686-9386f468-7714-490f-9bfc-9442db5c8f00
- Meta developer documentation (confirm version when available):
  https://developers.facebook.com/docs/instagram-platform/webhooks
- Community-observed Instagram DM shapes (informative, not official API
  contract):
  https://github.com/chatwoot/chatwoot/blob/develop/app/jobs/webhooks/instagram_events_job.rb

## Cases covered
- Inbound DM with IG business account ID in entry/recipient, Instagram-scoped
  customer as sender, Instagram-style message ID, millisecond timestamps.
- Explicit business echo (message.is_echo=true) routes outbound; a business
  sender without an echo marker is **not** silently classified as outbound.
- Media attachments (image, video, audio, share, ig_post) retain metadata
  for protected storage. The public read API already returns only has_media,
  never media URLs.
- Quick reply text and story reply context: message text is retained; extra
  context is **not yet stored**. These tests do not claim full story support.
- Read receipts, reactions, message edits, unsends, postbacks, comments,
  standby and unsupported message variants fail closed, including when a
  text message-like field is also present.
- Mixed known/unsupported batches stop instead of silently dropping unknown
  items. Existing transactional worker tests verify whole-envelope quarantine.

## Remaining blockers before any real Instagram subscription
1. **Actual Meta event capture is unverified.** Compare a sanitized example
   from the *exact Instagram Login* integration (correct API version) with
   these examples, using secure test handling only. Never paste raw guest
   DMs, tokens, signatures or customer IDs into issues/chat.
2. Worker is **manual/inert**; no durable service lifecycle, scheduling,
   retry/backoff/recovery visibility, operator alerts, or retention policy.
3. The current transactional worker **quarantines** unsupported event types,
   including mixed batches. Before real subscription, decide which fields to
   subscribe to and implement safe non-message handling or verified routing.
4. A safe end-to-end live test with the real @sunsetoiasailing should use an
   explicit test window and an isolated pipeline. The *production-shared
   PostgreSQL* must not receive synthetic inserted messages or live traffic
   as an experiment.
5. A generated Instagram access token must remain outside GitHub, logs,
   screenshots and chat. Do not configure the token into the live worker
   or enable ingress on the existing staging backend.

## Gates
- INSTAGRAM_WEBHOOK_INGESTION_ENABLED: **OFF**.
- INSTAGRAM_WORKER_MANUAL_ENABLED: **OFF**.
- Instagram Webhook Subscription: **OFF**.
- Production main and WhatsApp backend/polling: **UNCHANGED**.
- PR target: dev, review first; do not merge automatically.
