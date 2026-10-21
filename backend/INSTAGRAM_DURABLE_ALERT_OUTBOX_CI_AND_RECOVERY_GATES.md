# Instagram delivery alerts: durable-outbox CI proof & manual recovery boundaries

**2026-10-21 — entirely synthetic / GitHub Actions disposable PostgreSQL 16.**
No Render database objects, environment variables, Meta webhook subscriptions,
guest/customer records, WhatsApp routing, new paid services, live alert
recipients or `main` commits are part of this phase.

## Why a durable outbox prototype is necessary

The current Phase 2R supervisor calls `on_alert` **after** committing the
delivery transaction. If that in-process test callback fails, the synthetic
queue keeps the delivery state (properly), but **an operator is not guaranteed
to see the incident**. Alerts exist only transiently in the process.

The new library-only **CI-only** `instagram_alert_outbox_ci.py` is a narrow
experiment to demonstrate that sanitized incidents can be recorded durably
**before** a separate simulated notification transport fails. It is not
a real production notifier.

## Exact proof and scope

- The *test fixture*, and **not application code**, creates
  `public.sendro_ci_instagram_alert_outbox` in the strictly allowlisted,
  disposable GitHub Actions Postgres database
  `sendro_ig_ci` (`127.0.0.1:55439`, user `sendro_ci`).
- Importing any of these modules or merging into `dev` creates **nothing**.
  No automatic startup hook, CLI, scheduler or Render worker exists.
- Every outbox function rejects non-CI environments and database identity
  **before any DB connection**. It requires all three CI flags:
  `GITHUB_ACTIONS=true`,
  `SENDRO_INSTAGRAM_PG_CI_APPROVAL=ephemeral-local-service-only`,
  `INSTAGRAM_ALERT_OUTBOX_CI_ENABLED=true`.
- Only five fixed alert codes, five queue-state integer counts and due/
  deferred integer counts are allowed. Unexpected fields (including
  account/customer/delivery IDs or message content) are rejected.
- One alert code has one upserted incident row; repeated observations
  increment a counter. Reading through another DB connection proves
  the commit survived the callback function returning/raising.
- Simulated notification failure causes the supervisor to fail closed,
  while the outbox incident and quarantined encrypted delivery remain
  durable; zero chat messages/conversations are created.
- The alert outbox **never modifies existing delivery states, auto-resets
  failures, deletes ciphertext or sends real email/Slack notifications**.

**Important limitation:** The outbox is not transactionally coupled to
every failure of the worker and currently still depends on an invoked
callback. If the process dies after worker commit but before the callback,
an alert could still be missed. There is no independent recurring
health poller, persisted dispatch attempt/ack state, actual operator
delivery, alert deduplication across recovery episodes, secure credentials,
or production service deployment. The CI outbox table has **not** been
reviewed as a live schema migration and must **never** be installed on
the shared Sendro database by following these test fixtures.

## Triage / recovery policy for a future staffed live pilot

| Queue condition | Safe initial human response | Strict prohibition |
|---|---|---|
| `pending` still due | Check health totals and worker deployment, investigate known account identity privately | Do not manually toggle to processed or delete |
| `processing` committed | Treat as stuck/foreign-writer anomaly; preserve row and seek DBA audit | Do not auto-release lock or reset to pending |
| `quarantined` | Review sanitized `last_error_code`, subscribed event coverage, and account enrollment with explicit tenant authorization | Do not force unsupported payload into a conversation |
| `failed` retries exhausted | Preserve encrypted payload, confirm the recoverable fault and operator-approved bounded replay plan | Do not blindly requeue or reset attempts to zero |
| Alert receiver unavailable | Keep the incident recorded, separately escalate to a named human, stop further attended tests | Do not assume a callback or database insert is a delivered notification |

An approved future recovery operator must use **exact delivery/account/tenant
identity**, verify destination ownership and evidence, enforce optimistic
concurrency and a bounded one-off change, preserve the original encrypted
payload and audit record, prove idempotency on synthetic PostgreSQL, and
have a tested stop/rollback and immutable incident history. None of those
production operations exists in this PR.

## Next separately scoped work

1. Design a *real* event-to-outbox transactional story or independent
   periodic observer so a process crash between commit and callback
   cannot make alerts disappear.
2. Choose a reliable operator notification destination, implement durable
   dispatch/acknowledgement/retries/dead-letter handling, and verify the
   alert arrives **without customer PII**. No destination selected yet.
3. Rehearse operator-approved one-row recovery (quarantine vs transient
   failure vs orphan processing handled differently) with fake DM data.
4. Verify actual staging env booleans (redacted offline preflight),
   Meta subscription OFF, backup recency, tenant/account enrollment and
   staffed response process. This shared production/staging DB must not
   be used for experimental INSERT/UPDATE.
5. Seek new, specific approval before any shared database DDL, Render env
   changes, Meta subscriptions, real guest message or outgoing Instagram DM.

**Never mistake a successful CI outbox test for live monitoring.**
