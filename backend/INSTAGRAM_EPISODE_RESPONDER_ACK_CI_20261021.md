# Instagram CI alert episode dedupe + explicit responder acknowledgement

**Date:** 2026-10-21. **Scope: ephemeral GitHub PostgreSQL only.**
No production or staging database writes, no Meta subscription, no real
notification, no actual staff authentication, no email address, and no
changes to `main`.

## Risk addressed

PRs #71–73 established a redacted alert outbox, manually invoked queue
observer, and simulated dispatch / transport acceptance / acknowledgment.
They treat every additional queue observation as a **new dispatch version**.
If one DM remains quarantined for hours, recurring checks could generate
repeated notifications and accidental alert storms.

The original CI acknowledgment function also only models an
exact-version state change, **not** staff authorization. This PR adds a
separate test-only contract; it does not convert the old CI function into
a production API.

## What this CI experiment does

`instagram_alert_episode_ci.py` runs only on deliberate direct call,
with **all** existing disposable Postgres flags plus
`INSTAGRAM_ALERT_EPISODE_CI_ENABLED=true`. It reads **aggregate
queue health** and, in a single transaction, records an episode and
stages **one alert per continuous active alert code**:

- First detection opens episode 1 and one dispatch version.
- Repeated observations of the *same active* problem increase its
  observation counter only; they do not cause a new notification,
  even after a test human has acknowledged it.
- An observation confirming the problem is gone marks the episode
  inactive, without pretending to repair/erase a delivery.
- A later recurrence opens episode 2 and demands new transport
  acceptance and a new human acknowledgment.
- Episode creation and dispatch staging are **one database transaction**;
  if test dispatch storage fails, no half-published episode is committed.
- Concurrent calls use row locking for existing episodes; first-insert
  conflicts fail closed and can be retried. Full concurrency/idempotency
  under independent workers is **not** established in this PR.

`instagram_alert_staff_ack_ci.py` additionally demands
`INSTAGRAM_ALERT_ACK_CI_ENABLED=true`, a literal confirmation, an
exact alert-code + episode, and a **CI-only global responder allowlist**:
active, explicitly permitted `incident_admin` or
`incident_responder`, time-bounded permission, global incident scope.
Ordinary tenant-scoped operators cannot acknowledge an aggregate
**global** Instagram queue incident. The acknowledgment and a
unique per-episode reviewer audit are committed together or neither
is committed. A failed audit write cannot mark an incident acknowledged.

The fixture alone creates synthetic tables
`sendro_ci_instagram_alert_episodes`,
`sendro_ci_instagram_incident_responders`, and
`sendro_ci_instagram_ack_audit` on ephemeral GitHub Postgres
`sendro_ig_ci` at `127.0.0.1:55439`, user `sendro_ci`.
Importing modules or deploying `dev` never creates objects or
starts observer/dispatch/recovery code. No real message is touched.

## What the tests actually establish

- 12 repeated observations of one quarantined synthetic DM stage only
  one dispatch version; additional observations after simulated
  acknowledgment **do not** send again.
- Synthetic resolution followed by a new quarantine opens a new episode,
  requires new transport acceptance, and rejects the old acknowledgment.
- Unapproved, inactive, expired, wrongly scoped or ordinary operator
  identities cannot acknowledge global alerts. A separate synthetic
  global responder can, once, with an audit entry.
- Missing audit storage leaves the accepted alert unacknowledged.
  Missing dispatch storage rolls back episode creation.
- Wrong database or missing CI gate is rejected before any connection.
  Alert outputs carry only generic codes, counters and synthetic
  test reviewer IDs, never DM text, guest identifiers or credentials.

## Hard limitations / go-no-go

- **No real identity verification yet.** The `actor_user_id` parameter
  is controlled by the synthetic test caller. Role allowlisting is NOT
  authentication: exposing this function to a live HTTP request would
  permit actor spoofing without an authenticated, session-derived user
  principal and authorizer. It MUST remain inaccessible to production.
- No scheduled independent observer, no real email/push/Slack transport,
  no authenticated live acknowledgment UI, no escalation when staff do
  not respond, no episode grouping by tenant or by individual DM, and
  no incident resolution/automated replay in production.
- Global aggregate queue-health codes can hide per-tenant distribution.
  Any future real design needs independently verified, scoped incident
  ownership and access control; a generic tenant admin must not gain
  global acknowledgment rights.
- An explicit CI simulation of clearing a problem by altering a fake
  delivery state is a **test action only**, not a recovery algorithm.
- All CI-only tables and flags MUST stay off the real Render DB. The
  shared DB needs independent-role/backup approvals before any schema
  changes. A live Meta subscription and single real DM pilot require
  a separate approval after operational readiness review.

**Next:** design the real operator notification destination and
session-derived responder access control, reliable supervised health
sampling, and authenticated acknowledgment + escalation with a proper
reviewed schema migration. Do not send actual alerts to staff until
that design and the recipient have been independently approved.
