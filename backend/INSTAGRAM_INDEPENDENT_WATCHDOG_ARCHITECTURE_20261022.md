# Independent Instagram operations watchdog — design decision / no live rollout

**2026-10-22. Status: code-reviewed policy rehearsal only. Not running.**

## What we checked (read-only)

- Staging backend `sendro-backend-staging` is a **single Render Starter
  web-service instance** running `uvicorn app.main:app`. Auto-deploy
  is ON for `dev`. The service's `notifyOnFail` is `default`,
  and its `healthCheckPath` is empty. Metadata does **not** prove
  operational queue incident delivery or the effective Instagram flags.
- Existing Sendro browser notifications in `frontend/src/App.jsx`
  rely on the active logged-in browser/Notification permission and are
  oriented toward WhatsApp needs-reply counts. A browser that is closed,
  offline or no longer authenticated is **not an unattended incident
  responder**. Do not reuse the personal preference as a substitute
  for 24/7 incident receipt.
- The current CI-only Instagram observer/episode/outbox/dispatch
  prototypes are manually invoked **library functions**. The
  in-app Incident Center router remains unmounted. They are not a
  deployable production health monitor and do not notify staff.
- `backend/INSTAGRAM_FIRST_REAL_DM_GO_NO_GO_20261022.md` remains
  authoritative: live Meta subscription, real database writes and
  the first actual DM remain **HOLD**.

## Decided reliability architecture (future approval required)

Two distinct failure domains are required:

**A. Instagram delivery/queue supervision**
1. An explicitly provisioned, *independently supervised* worker
   handles **bounded batches** and uses exact tenant/account routing,
   atomic processed/quarantined transitions, idempotency and
   reviewed transient retry rules. Never enable the prototype's
   permissive "oldest available" runner for a live first-DM pilot.
2. A **separate** periodic read-only observer examines only aggregate
   operational PostgreSQL state and records validated, redacted
   incident episodes into dedicated durable incident storage in
   an approved schema. Its *last successful cycle heartbeat* must
   be durable outside its own process. No guest text, sender/customer
   IDs, ciphertext or Meta secrets may be part of an alert.
3. A **separate dispatcher** claims durable incidents with leases,
   bounded retries and dead-letter/manual escalation. The dispatch
   service maintains its own durable successful heartbeat and
   operator receipt/acknowledgment state. A callback returning
   `True` is transport acceptance, **not** human acknowledgment.
4. A real user must log in through the existing Sendro session/JWT
   and recent signed MFA and have independently delegated incident
   rights to acknowledge a global event. The CI-only actor-ID and
   responder table must NEVER be mounted in production unchanged.

**B. Independent liveness / out-of-band escalation**
5. A process **independent of both worker and observer** checks
   observer+dispatcher heartbeats and overdue operator acknowledgment.
   Without a source outside the failed process, a stopped observer
   could silently report zero incidents forever.
6. A *separate* externally monitored delivery channel (proposed:
   an explicitly approved operational mailbox and secondary human
   escalation route) must alert a named staff member even if Sendro
   frontend is closed. Recipient, consent, failover and provider
   have NOT been selected/approved. Never send trial notices to
   real staff or reuse house-project Resend credentials by default.
7. Monitor the watchdog **itself** externally (no fresh sample /
   missing watchdog heartbeat becomes a critical signal); otherwise
   it too could die without anyone noticing.

These components may require a separately provisioned Render
background service or scheduler. Availability, costs, permissions
and quotas must be assessed with owner approval. The existing
staging/production services share PostgreSQL; a new worker must
not be pointed at the shared DB without approved roles, backups,
credential separation and operator stop procedure. No new
Render service or paid resource is authorized in this PR.

## Reusable pure policy in this PR

`backend/app/instagram_watchdog_policy.py` contains only a pure
`evaluate_instagram_watchdog(snapshot, now=...)` function. Its
input contract is an exact **redacted** mapping:

`source`, `captured_at`, `observer_heartbeat_at`,
`dispatch_heartbeat_at`, `unacknowledged_incidents`,
`oldest_unacknowledged_at`, `failed_notifications`.

It rejects extra keys, PII, unknown source labels, naive/non-datetime
timestamps, bool masquerading as integers, out-of-range counts and
inconsistent reviewed-at/count pairs. It never echoes user-supplied
fields in its return value or exceptions. Its outputs include only
static generic escalation codes and decisions.

Current **design targets** (not service guarantees):

| Independent signal | Timeout | Severity |
|---|---:|---|
| External monitoring observation absent/stale | >90 sec | Critical |
| Queue observer last successful cycle missing/stale | >120 sec | Critical |
| Dispatch heartbeat missing/stale | >300 sec | Critical |
| Any failed notification dispatch | Immediate on next sample | Critical |
| Human acknowledgment overdue | >15 min | Warning |
| Clock anomaly in source timestamps | >5 sec future | Critical |

Thresholds are policy proposals. Final scheduling/retention, timezone,
event storm coalescing, contact rotation and SLA must be ratified
with the staffed responders and cost budget. The policy emits
`NOMINAL_UNVERIFIED` when inputs are fresh and healthy: this
**does not independently verify authenticity or authorize Meta/DB
changes**. It always emits `live_pilot_authorized: false`.

**Crucially:** the evaluator is NOT scheduled and NOT connected to
PostgreSQL, Render or an alert provider. It cannot detect a dead
service in practice until an **independent trusted caller** supplies
fresh observations and delivers escalation via an out-of-band route.

## GitHub Actions test contract

`backend/tests/test_instagram_watchdog_policy.py` covers:
- fresh metric input still does NOT grant live pilot approval;
- observer/dispatcher heartbeat missing/stale even with zero queue
  incidents; stale external feed and invalid clocks;
- failed delivery, expired human review, multiple simultaneous
  failures and ordering/severity;
- unexpected guest data rejected, no secret content leaked;
- malformed, out-of-range and stale signal data fail closed;
- incident resolution, repeatable deterministic outputs and
  source scan for database/network/scheduler side effects.

These are pure Python synthetic tests that can run on GitHub without
a database connection. **No actual heartbeat, alert email or observer
service has been deployed.**

## Exact gates before real activation

- Human Render PostgreSQL engineer guidance and reviewed ownership
  boundaries; dedicated safe reader/writer roles and a tested restore.
- Review and separately approve actual runtime env flags and Meta
  permissions/subscription blast radius and exact tenant/account mapping.
- Name and authorize an operator + backup operator and chosen
  independent notification provider/channel, with receipt confirmation
  and actual delivery-failure escalation proof.
- Implement trusted heartbeat storage, independently scheduled observer,
  dispatcher, and external watchdog self-monitor. Rehearse process
  crashes/outages against **non-live** PostgreSQL first.
- Tie the alert recipient UI to *actual* Sendro MFA/role controls,
  preserve immutable audit and strict tenant-vs-global boundary.
- Explicitly approve any new Render service/cost, shared database
  read/write, migration, Meta webhook activation or real Instagram DM.

**Until these are signed off, do not wire this code to FastAPI
startup, an automatic scheduler, Render worker, real notification
provider, `main` or a Meta subscription.**
