# One real Instagram DM — exact delivery pilot safeguards (proposed, not activated)

## Why this change

The existing manually enabled Instagram worker always selects the oldest
available pending delivery. In a shared real database, that is too broad
for an initial attended test: an unexpected genuine customer event might
be older than the test message.

**This change adds a scope, not a live Instagram integration.** The goal is
to prove using **disposable GitHub PostgreSQL** that selecting exactly one
queued inbound DM can never accidentally process another delivery, an
unexpected Instagram business account or the wrong Sendro tenant.

## Code added / modified

- `backend/app/instagram_delivery_worker.py`:
  `InstagramPilotScope(delivery_id, tenant_id, channel_account_id,
  business_account_id)` optionally narrows one existing worker transaction.
  The original `process_one_pending_instagram_delivery(engine, key)` behavior
  remains unchanged when no pilot scope is supplied.
- Explicit `id = :pilot_delivery_id`, `provider='instagram'`,
  `processing_state='pending'`, due timestamp, and PostgreSQL
  `FOR UPDATE SKIP LOCKED` selection. No fallback to the next row if
  the selected one is locked, deferred, missing or processed.
- Pre-write validation requires **exactly one normalized inbound DM**
  targeted to the expected Instagram business account and a registered
  account matching the expected tenant and channel-account PK.
  No batch processing, echo or cross-tenant routing in this mode.
  Unsupported/mismatched event returns `blocked` and leaves the queued
  encrypted delivery untouched for human triage, without creating a
  conversation or marking the queue row processed.
- `backend/app/instagram_pilot_operator.py` is **library-only**, no
  FastAPI hook, no CLI, no cron, no Render service, and no Meta call.
  Before opening the DB it requires:
  `INSTAGRAM_PILOT_ONE_DM_ENABLED=true`,
  `INSTAGRAM_WORKER_MANUAL_ENABLED=true`,
  the exact confirmation phrase
  `I_APPROVE_EXACTLY_ONE_INSTAGRAM_PILOT_DM`,
  plus separately configured exact delivery, tenant, account and business IDs.
  It uses the existing encryption key only after these gates pass.
  Results have only generic status and inserted count.
- No schema migration, additional infrastructure or paid service.

## What CI verifies

Real Postgres 16 inside **GitHub Actions only**, with the pinned six SQL
migration fixtures and Phase 2L strict URL/port/user/DB identity gate.
Tests seed entirely fabricated deliveries, tenants, business account IDs,
user IDs and Fernet keys.

1. Default gates refuse use **before any database access**.
2. Exact delivery/tenant/account/business configuration and confirmation
   are mandatory.
3. The *second* envelope can be selected while an earlier unrelated
   one stays pending; rerunning the same selection stays idle and
   never falls back.
4. Wrong business account or tenant returns `blocked`, changes **zero**
   message/conversation rows and does not increment delivery attempts.
5. Multi-message envelopes and unsupported Instagram event kinds
   return `blocked`, preserving encrypted queue data.
6. Missing/deferred/locked exact delivery skips rather than processing
   another tenant's pending delivery.
7. Invalid pilot scope fails before database queries.
8. Existing synthetic end-to-end, retry, schema, frontend and role tests
   continue running unchanged.

## Still NOT a green light for the first live DM

Before using this on the existing production-shared PostgreSQL, explicitly
verify and agree with the owner:

- Meta app access, webhook verify token/signature setup, app-role test
  account, and the actual Instagram webhook subscriptions. Even a
  one-DM worker **cannot prevent other real customer webhook deliveries
  from arriving** once Meta subscription is enabled.
- Correct account -> Sendro tenant/user enrollment and readiness of the
  authorized Conversations view.
- Recent recoverable backup + restoration plan; runtime secret/key
  agreement; targeted metadata-only queue inspection and human verification
  of the approved delivery/account; clear handling of unexpected events.
- Short staffed pilot window; failure alerts reaching an operator;
  explicit stopping procedure for both webhook ingestion and manual
  worker invocation; preserve acknowledged queued payloads for later
  recovery instead of deleting/truncating them.
- Explicit separate authorization to activate Meta webhook subscription,
  change Render environment flags, read queue identifiers or write ANY
  rows to shared PostgreSQL. This PR does none of those.
- No Instagram send/reply API has been enabled yet. The first goal is
  **inbound observation** of a single expected DM only.

This pilot code is not called from any current runtime startup or manual
CLI by this PR. It needs a *future*, separately approved operational
entrypoint and human-attended test plan. The continuous supervisor,
durable alerts and full Meta event handling are still not deployed.

**Branch/deployment guard:** Draft PR targets only `dev`; Render staging
automatically deploys `dev` after a later approved merge. Do not merge
this PR without explicit owner confirmation. No changes to `main`,
WhatsApp production, current Render configuration or shared DB.
