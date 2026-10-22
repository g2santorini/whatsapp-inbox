# Instagram first real DM — evidence-based HOLD checkpoint (2026-10-22)

**Status: NO-GO for live activation.** The latest CI-only integrated
signed-DM -> quarantine -> alert -> authenticated review rehearsal
passed in PR #78. Render read-only metadata confirmed the staging
backend deploy for that PR (`cad0251c4bf46420b677c956d62a8c8efe703cf3`)
went LIVE at 2026-10-21 12:06:24 UTC. This means the inert CI
test files are deployed; it **does not** prove Instagram ingestion,
a supervised worker or Meta subscriptions are enabled or ready.

## The new offline gate

`backend/app/instagram_pilot_evidence_preflight.py` is a **pure,
redacted, manually invoked checklist** that:
- Uses the existing `instagram_live_readiness.inspect_instagram_live_readiness`
  on a **caller-supplied configuration snapshot**, not Render's actual
  effective environment. It must never claim this is real env verification.
- Evaluates **12 explicitly named evidence items**, each demanding exact
  `{"verified": true, "source": "<expected source>", "verified_at": "<UTC timestamp>"}`.
  Missing, stale, malformed, future-dated, wrong-source, extra-field,
  non-boolean or unknown evidence fails closed. Items have individually
  bounded freshness windows, at most 24-168 hours depending on the item.
  The function never prints the provided source, timestamp, URLs or raw
  evidence values.
- **Always returns `decision: HOLD`, `live_pilot_authorized: false`,
  `independently_verified: false`, even if all supplied items are
  formally valid. Self-reported evidence is NOT independently verified.
- Has no DB import/connection, Render/Meta API, user data, worker
  invocation, scheduler, CLI flags to activate, table writes, env writes,
  actual notifications, service changes or Meta subscription calls.
- The CLI `python -m app.instagram_pilot_evidence_preflight`
  outputs redacted JSON and **always exits 2**, intentionally. It
  accepts no secret/evidence input files and **cannot grant GO**.

This gate is a review aid, **not a real operational attestation platform**.
The synthetic CI tests do not prove the following real-world items.

## Evidence required before an attended real Instagram DM pilot

| Evidence item | Required independent reviewer/source | Current evidence |
|---|---|---|
| Staging effective ingestion/worker/pilot flags verified OFF | Read-only staging Render env inspection | **Unknown**, defaults are insufficient |
| Production effective flags verified OFF | Read-only production Render env inspection | **Unknown** |
| Actual Meta Instagram webhook subscription OFF | Meta Developer Dashboard | **Unverified** |
| App permissions/test-account roles reviewed | Meta Developer Dashboard | **Unverified** |
| Single Instagram business -> exact Sendro tenant/account mapping reviewed | Authorized security review | **Unverified** |
| Current shared database backup **restored and verified** | Isolated restore drill | **Needs fresh operator evidence**; older local restore is not a future backup attestation |
| Shared DB privilege/role boundary approved | Authorized security/DBA review | **Render engineer response pending** |
| Bounded supervised worker stop rehearsed | Staffed synthetic operational drill | **Not deployed** |
| Real alert recipient receipt rehearsed | Staffed synthetic notification drill | **Not deployed** |
| Authenticated MFA global responder and audit authority reviewed | Authorized security review | **CI-only prototype**, no live ACL |
| Exact one-DM scope/timing and consent reviewed | Attended operator rehearsal | **Not approved** |
| Quarantine, stop and rollback rehearsed | Attended operator rehearsal | **No staffed live rollback rehearsal** |

**Some of these cannot possibly be marked as genuinely complete
today.** The CI-only observer, alert dispatch and Incident Center are
libraries/test fixtures and are not an automatically supervised
production monitoring service, actual staff notifier or live audit store.
Do not mark these as completed because the corresponding CI tests pass.

## Hard stop / safety and next actions

1. Keep `main`, shared database schema/roles/data, live WhatsApp,
   Meta webhook subscription and all Instagram execution flags untouched.
   Never install `sendro_ci_*` test tables in Render.
2. Await human Render engineer guidance on independently managed
   PostgreSQL roles. Track a separate approved migration/security plan;
   **do not** use `sendro_user` to invent a supposedly independent owner.
3. Plan, implement and test a separately supervised production-compatible
   incident observer and real delivery to an approved responder, with
   explicit acknowledgment, retries, outage escalation, and operational
   stop. Avoid reading or disclosing customer DM payloads for alerts.
4. Verify Meta permissions and account/test roles read-only, and review
   subscription blast radius: turning on a page/account subscription may
   immediately collect **other genuine customer DMs**.
5. Confirm a fresh tested backup/restore and independently authorize
   one exact enrolled business/account/tenant. Run a staffed sandbox or
   fully controlled test first. Require explicit owner approval **for
   each** real Meta subscription or shared DB operation.
6. Do not enable Instagram outbound replies: this feature is not
   implemented or authorized for live use.

**Code review/testing of this offline gate does not alter any of these
preconditions.** The owner must provide a separately scoped, explicit
authorization before any real shared-database modification, Render
settings change or Instagram webhook event reception.

## Read-only audit provenance

- GitHub repository: `g2santorini/whatsapp-inbox`; production is
  `main` and staging auto-deploys from `dev`.
- PR #78 was merged only to `dev`, with six CI jobs succeeding.
- Render staging deployment for PR #78 was seen as LIVE via read-only
  list-deploys on 2026-10-22. The status does not show effective env flags.
- The shared PostgreSQL instance serves both staging and production,
  so `dev` merges must remain non-invasive.

No live configuration, database, customer IDs, keys or account
permissions were queried or changed to produce this document.
