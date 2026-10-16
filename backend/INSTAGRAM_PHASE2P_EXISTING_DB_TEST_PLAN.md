# Phase 2P — Zero-recurring-cost Instagram rehearsal & existing-DB pilot plan

**Goal:** prepare a safe, controlled first Instagram DM in Sendro without
provisioning a paid, persistent second Render database. Development and
confidence-building tests use the **existing GitHub Actions ephemeral PostgreSQL
service**, not the real shared PostgreSQL.

## What this PR actually does

A new synthetic **signed HTTP-to-Inbox E2E test** runs only inside the
GitHub Actions disposable Postgres 16 service. The strict fixture allowlist
from Phase 2L requires `GITHUB_ACTIONS=true`, a dedicated CI approval
variable, `127.0.0.1:55439`, user `sendro_ci`, and database `sendro_ig_ci`.
The six pinned author-written Instagram SQL migrations are replayed
in that throwaway database, never in Render.

Tests run the **actual FastAPI Instagram webhook and read-only Instagram
Inbox routers**, and the manually gated worker under a temporary test-only
environment override:

1. Verify POST is **503** with ingestion OFF and wrong/missing HMAC is **403**.
2. Temporarily set `INSTAGRAM_WEBHOOK_INGESTION_ENABLED=true` **only inside
   pytest**, send one synthetic correctly signed POST, and confirm encrypted
   durable queue storage before the HTTP 200 acknowledgment.
3. Verify manual worker execution fails while the manual gate is disabled.
   Explicitly enable it in the test's in-memory argument dict, process a
   single queued envelope and confirm exactly one saved inbound message and
   one unread conversation in the expected tenant.
4. Check tenant isolation and no internal ciphertext/provider IDs in the
   read-only Inbox JSON; replay signed payload bytes to prove idempotency.
5. Send a mixed supported/unsupported signed envelope and confirm that the
   entire delivery is quarantined without writing partial conversations.
6. Send a synthetic two-business signed batch and check tenant-specific routing.
7. Flip the local test flag back to OFF and verify further signed POSTs
   return **503**, without clearing any queue items.

No real Meta request, token, webhook configuration, Render environment
variable, production table or customer content is used in these tests.

## Why NOT test writes in the existing PostgreSQL yet?

The shared PostgreSQL is both **staging and live WhatsApp production**.
Instagram lives in separate tables, but locks, pool exhaustion, misconfiguration,
backend exceptions and accidental authorization mistakes can still impact live
traffic. Lower traffic helps with load only; it does not eliminate those risks.

Further, enabling Meta Instagram subscriptions on the real business account
can deliver **unsolicited customer traffic**, not only a selected test DM.
A test-only worker with limited coverage of Meta webhook event types is not
yet an assured production process. We cannot safely promise one received
message and zero other incoming events.

The Phase 2O read-only audit found:
- Schema structure, required indexes and critical isolation constraints match
  the six pinned SQL migration snapshots.
- RLS **not enabled** on the six social-channel tables. API membership checks
  exist but database-enforced tenant separation is not established.
- Database owner has broad privileges and network allowlist permits 0.0.0.0/0.
  These are planned hardening tasks requiring separate rollout review so live
  WhatsApp access isn't disrupted.

## Controlled existing-database pilot: future separately approved gate

No operator should proceed to the following steps as part of this PR.
These are **preconditions for a future live pilot**, not an execution script:

1. Verify a **recoverable recent snapshot**, restoration procedure, active
   alert contact and the correct connected Instagram professional account
   (independently cross-check the Meta app and external business ID without
   revealing tokens).
2. Make an inventory of staging/prod connection pools and app permissions.
   Define a narrow pilot window and a tested **kill switch** to disable both
   webhook intake and worker processing. Remember that disabling intake will
   lead to Meta retries and *may impact real Instagram users*.
3. Resolve event coverage / quarantine policy. Sign off exact Meta webhook
   subscribed fields; never silently acknowledge potentially lost customer DMs.
4. Prove the ingest encryption key matches the worker, without exposing
   key material. Establish automated monitoring, durable failure alerts,
   retry/idempotency and a recovery mechanism for pending/quarantined envelopes.
5. Confirm the tenant's account is enrolled, authorized Inbox users can see
   only their own tenant, and other accounts cannot be accidentally processed.
6. Choose an explicit **signed-off pilot**: who sends a test DM, permitted
   time window, how unexpected incoming customer messages are handled, and
   what observable evidence counts as success (real HTTP 200 -> encrypted
   queue -> processed -> authorized conversation appears exactly once).
7. Only after an additional explicit owner approval, apply the minimum live
   config changes, starting with the smallest feasible scope. Monitor actively,
   stop on any unexpected behavior and preserve the entire audit trail.

**Forbidden without new approval:** Paid Render provisioning, a fresh
long-running database/service, live Meta subscriptions, Render config
changes, enabling `INSTAGRAM_WEBHOOK_INGESTION_ENABLED` or
`INSTAGRAM_WORKER_MANUAL_ENABLED`, manual processing of real deliveries,
synthetic database writes to the shared PostgreSQL, `main` edits or
WhatsApp production changes.

### Rollback vs. emergency stop

The immediate kill switch is **turn off worker execution and disable incoming
Instagram ingestion/subscription**, once its Meta retry consequences are
understood. **Do not delete or truncate pending deliveries or message history**.
If an envelope is already acknowledged and encrypted in the durable queue,
it must remain recoverable even when intake and processing are paused.
Turning flags OFF is not a substitute for investigating pending deliveries.

### Next engineering gates

The GitHub Actions rehearsal is **not live testing**. A genuine Meta-signed
payload from an authorized test account has not been verified. Current
supervision is a **SQLite-only prototype** and deliberately rejects
PostgreSQL. There is no deployed Instagram production supervisor or durable
alert transport. The Inbox is read-only; Instagram replies are not yet
implemented. These remain gates before a shared-DB pilot.

**Current state:** existing shared DB unmodified, Meta subscription OFF,
Instagram intake OFF, Instagram manual worker OFF. No added recurring fee.
