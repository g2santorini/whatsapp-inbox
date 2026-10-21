# Instagram alert dispatch and explicit acknowledgment — synthetic CI rehearsal

**Date: 2026-10-21. No production monitoring, real notification or live rollout.**

Previous Instagram test-only phases have proven that:
1. queue-health queries identify quarantined, failed and stranded `processing` DMs;
2. a manual CI observer can persist aggregate alert codes independently of the
   worker callback;
3. a CI-only outbox survives a simulated notification callback failure.

This phase models **how a notification should be claimed, accepted and later
acknowledged**, without choosing a real email/chat/push provider.

## What the disposable PostgreSQL tests now prove

The standalone library `backend/app/instagram_alert_dispatch_ci.py` is
available only when **all** of these match:
- `GITHUB_ACTIONS=true`
- `SENDRO_INSTAGRAM_PG_CI_APPROVAL=ephemeral-local-service-only`
- `INSTAGRAM_ALERT_OUTBOX_CI_ENABLED=true`
- `INSTAGRAM_ALERT_DISPATCH_CI_ENABLED=true`
- PostgreSQL URL is **exactly** localhost `127.0.0.1:55439`,
  user `sendro_ci`, DB `sendro_ig_ci`.

These checks happen **before any DB connection**. A test fixture (not the app)
creates `public.sendro_ci_instagram_alert_dispatch` only in this disposable
GitHub Actions service.

The state machine:
- `pending`: a redacted alert code/version from the durable outbox is queued.
- `leased`: a single worker has a 60-second lease, acquired transactionally
  with PostgreSQL `FOR UPDATE SKIP LOCKED`. Concurrent callers cannot both
  claim the same available incident.
- `accepted`: a supplied synthetic callback returned *exactly* `True`.
  This is **transport acceptance only**, NOT proof a real person saw it.
- `acknowledged`: a **separate explicit** exact-version simulated human
  action succeeds. Transport acceptance does not imply acknowledgment.
- `failed`: three consecutive synthetic transport failures leave the
  alert durable and require manual triage. No row is deleted.

Transport rejection/exception releases the lease with a 30-second retry.
Crash while holding a lease permits reclaim after expiry. Old lease tokens
cannot complete a later claim. These semantics are **at-least-once**:
a crash after external acceptance but before database recording can
cause duplicate notifications. Real providers must support idempotency
or a controlled duplicate warning; exactly-once delivery is not promised.

Observing a newer version during an in-flight lease does **not** let an
older completion acknowledge the newer version. A new snapshot must be
delivered and explicitly acknowledged. Repeated observations of a persistent
incident currently create new versions; a future live design needs episode
grouping / throttling to avoid notification storms.

Only the fixed incident code and numeric observation count reach the
synthetic transport callback. No guest data, account IDs, delivery IDs,
message text, payload ciphertext, secrets, URLs or lease token are sent.
The synthetic dispatch status API reports only codes, numeric counters
and states.

## Operational boundaries and next gates

- **No real email/Slack/push notification is being sent.** The callback
  is test-supplied, and no external networking exists in this module.
- **No automatic polling, live worker, scheduler or startup hook** is
  registered. `dev` auto-deploys code but the CI guard rejects Render.
- No real staff identity is stored or verified by the synthetic ack
  function; a live design needs operator authorization and append-only
  audit before anyone can acknowledge or resolve incidents.
- The incident/outbox/dispatch schema lives only in test fixtures;
  there is **no migration** to install it on the shared Sendro DB.
- The real source/transport outcome is not transactionally coupled to
  the queue observer. A reliable independently supervised observer,
  real recipient delivery/receipt tracking, missing-alert escalation,
  episode throttling and secure failure recovery remain pending.
- No automated replay/reset of failed or quarantined Instagram DM rows:
  those require separately scoped, operator-approved, auditable recovery.

**Never set these CI-only flags on Render.** Before any real DM, secure
independent tenant-account enrollment, real Meta subscription details,
reliable controlled worker/alerts, restore point and recovery procedure
plus fresh explicit operator approval. Both Sendro production and
staging continue to share the same PostgreSQL database.
