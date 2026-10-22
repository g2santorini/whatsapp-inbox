# Sendro Instagram — first external availability sentinel (NOT DEPLOYED)

**Prepared 2026-10-22. No Render services were created or changed.**
**Live Instagram remains NO-GO.** No application startup hook, database
queries, account identifiers, Meta subscriptions, outgoing DMs or real
operator alerts are included in this work.

## Render account evidence (read-only check)

Existing resources observed:
- `sendro-backend` (`main`) and `sendro-backend-staging` (`dev`):
  one Frankfurt Starter web service each, running FastAPI
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- `sendro-postgres`: a single existing Frankfurt PostgreSQL 18 database
  shared between staging and production. No independent worker/cron
  service was shown in the services listing.
- Staging PR #80 code deployed LIVE via Render; this only proves the
  **pure watchdog policy code** is deployed. The separate worker,
  observation timestamps and alerts do not run yet.
- `backend/app/main.py` exposes public `GET /` returning JSON with
  `status: ok` and a short version string. This handler does not
  query the delivery queue; it is **not a PostgreSQL/Instagram health
  check**.

## Stage 1 code, executable but intentionally disabled

`backend/app/instagram_staging_http_sentinel.py` is a minimal Python
stdlib-only **one-shot** network probe of the exact hardcoded URL:

`https://sendro-backend-staging.onrender.com/`

- Imports do nothing; it is not imported by `main.py` or React.
- By default it makes **zero outbound requests**, prints fixed redacted
  `backend_http: disabled` JSON and exits with status 2 (failure).
- Only a *future explicit operator authorization* setting
  `SENDRO_IG_STAGING_HTTP_SENTINEL_ENABLED` to the exact value
  `I_APPROVE_STAGING_PUBLIC_STATUS_GET_ONLY` permits a **single** public
  HTTPS GET to staging root. Do **not** set this on existing Sendro
  staging/production web services.
- Requests contain no API key, bearer authorization, cookies,
  credentials, query string, user IDs, DM payloads or database URL.
  No redirects (even another HTTPS site), no dynamic host selection,
  a strict five-second timeout and a 1,024-byte response limit.
- Success requires HTTP 200 + JSON content type +
  `{"status":"ok","version":"..."}` shape. Public version and response
  body are **never printed**; output is only `reachable` or
  `unavailable` plus permanent `instagram_pipeline: not_checked`.
- Any HTTP/network/schema/timeout error returns unavailable and
  exits 2. Only a validated public status reply exits 0.
- All paths print `live_pilot_authorized:false`,
  `database_access:none`, `meta_access:none` and
  `operator_notification:not_configured`. Returning 0 means
  **public staging root reachable only**, not live Instagram readiness.

The matching `backend/tests/test_instagram_staging_http_sentinel.py`
mocks network access to verify the exact fixed URL, disabled gate
no-network contract, wrong response/redirect/timeout denial and no
error-string/secret leakage.

## Stage 1 optional Render Cron proposal — NOT provisioned

`ops/render/instagram-staging-http-sentinel.UNDEPLOYED.example.yaml`
describes a proposed, **intentionally unlinked** Render cron job:
- `type: cron`, 512 MB compute plan, Frankfurt region, `dev` branch,
  every **5 minutes**, no dependencies (`buildCommand: true`),
  simple one-shot start command, auto-deploy OFF.
- Its **approval environment variable is deliberately absent**.
  Syncing this file without the owner approving the service and
  setting up alerts would create cost and recurring **failed** runs.
- It is **not** named `render.yaml` and must not be synced to the
  account or moved to root without separate owner approval.

Official Render docs describe cron jobs as billed per second of run
time, with a minimum of **$1/month per job** at the time of review.
The 512 MB plan is currently **$0.00016 per billable minute**;
real costs depend on executions/duration, build time, plan and policy.
Render supports email/Slack **cron execution failure notifications**
if configured in workspace or per-service notification settings.
Having a failed cron doesn't alone prove notifications arrive; the
named recipient must be verified and the alerts themselves exercised.

Links for subsequent owner review:
- https://render.com/docs/cronjobs
- https://render.com/pricing
- https://render.com/docs/notifications
- https://render.com/docs/blueprint-spec

## Crucial limitations / next real milestones

**A successful external HTTP check cannot tell whether the Instagram
worker, webhook, shared DB, alert dispatcher or authenticated Incident
Center is operational.** The existing queue/alert/episode prototypes
are gated CI-only and cannot be deployed against live PostgreSQL.
The prior `instagram_watchdog_policy` consumes independently collected
heartbeats but does not collect them itself. A separate, genuine
heartbeat source and a second independent external supervisor are
still required for Instagram operational readiness.

Before any real monitoring rollout:
1. Obtain the human Render/Postgres security answer and approve isolated
   read/write privileges, schema/migration, freshness/backup and rollback
   for shared production/staging PostgreSQL.
2. Decide whether to use an approved Render cron/background worker for
   bounded DB read-only aggregate observation, with **independent**
   heartbeat generation/storage, or dedicated supported monitoring
   instead. Never point existing CI-only runners at live PostgreSQL.
3. Choose a **named staffed incident owner and backup**, actual
   independent email/Slack recipient and notification failure escalation
   procedure. Verify a real test notification is received before
   treating alerts as live. Browser desktop notifications don't meet
   unattended incident notification requirements.
4. Approve any new Render cost/resource **before** creating it and
   measure latency + provider throttling for a 5-minute interval.
   A 5-minute cron cannot meet the watchdog policy's current 90/120s
   targets; update policy only after proper service/SLA design. Do not
   claim minute-level Instagram detection from this proposal.
5. Only after independent operations + the Meta account's subscription
   blast radius and exact tenant/account mapping are independently
   reviewed may a separate attended **one exact real DM pilot** be
   proposed. Turning on a Meta subscription can ingest other genuine
   customer DMs immediately, even when a worker picks one delivery.

**No action required on your PC for this PR.** Creating or enabling
the real external cron would need explicit owner/cost/recipient approval.
No Render, GitHub Actions schedule or Meta configuration has been changed
to launch the sample.
