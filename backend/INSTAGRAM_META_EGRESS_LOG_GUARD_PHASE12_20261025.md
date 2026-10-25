# Instagram Login Phase 12 — Meta HTTP egress log safety gate

**DRAFT ONLY, no merge, no staging/production deploy, no Meta HTTP calls.**
Stacked after Draft PR #94 → #93 → #92 → #91 → #90 → #89 → #88 →
#87 → #86 → #85 → #84.

## Why

Instagram Login's long-lived token exchange and refresh require Meta Graph
GET URLs containing `access_token` query parameters; the initial exchange
also includes `client_secret` in that URL. These are security-sensitive
request targets, even when the application does not deliberately log them.

The GitHub Instagram Login adapters were already unmounted and manually
callable, but **previously lacked an enforced check** that someone had
reviewed egress logs before allowing their HTTP calls. The PR #90
`InstagramOAuthLogAttestations` booleans existed only at the callback/
onboarding HTTP layer and were not required by all direct Meta helpers.

## Changes

- `instagram_meta_egress_guard.py`: new fail-closed prerequisite. Requires
  a typed `InstagramOAuthLogAttestations` object with *all five* assertions
  true (ingress proxy, ASGI access logs, outbound Graph query protection,
  incident telemetry, explicit release approval).
- Independently rejects outgoing Meta HTTP requests whenever common
  `urllib3`, `urllib3.connectionpool`, or `requests` loggers are in
  DEBUG mode, or `http.client.HTTPConnection.debuglevel` is nonzero.
  Refuses the HTTP call **before** transmitting a token, OAuth code or
  App Secret. No logging of credentials, query strings, or HTTP arguments
  is performed by this guard.
- `instagram_login_oauth.py`: both short-lived token POST and read-only
  profile GET require an explicit egress approval.
- `instagram_token_lifecycle.py`: both long-lived token exchange and
  refresh GET require an explicit egress approval. Neither is scheduled.
- `instagram_account_link.py`: the one-use identity verification chain
  requires the approval before its first Meta call and threads it through
  every subsequent provider exchange/profile read.
- `instagram_onboarding_router.py`: the still-unmounted onboarding
  API factory passes the same explicit operational attestations to the
  account-link chain.
- Fully synthetic tests for default refusal, each missing attestation,
  string-based fake approvals, debugging via three HTTP loggers and
  Python HTTP wire debuglevel, zero fake-network invocations on denial,
  original mocked endpoint details, and the full dormant onboarding path.
  Run in the **existing** backend CI job; no additional GitHub jobs.

## Critical limitations and explicit GO/NO-GO

This PR does NOT prove that all traffic is safe from logging. The
assertions are operator-supplied **declarations**, not cryptographic
proof. Developers cannot derive them automatically from a successful
test. App/HTTP clients may be wrapped by unknown telemetry, external
outbound proxies, exception reporting, service mesh, or other libraries.

Even when no Python DEBUG logging is active, provider GET query
parameters can be captured by **intermediate HTTP instrumentation**.
Do not enable any real Meta request unless an independent inspection
confirms safe inbound + outbound URLs, headers, POST bodies and errors.

### Render finding as of 25 October 2026

- Confirmed workspace: **Sendro**, Hobby.
- Backend staging `sendro-backend-staging` on `dev`.
- Staging Start Command now contains `--no-access-log`; the service
  restarted successfully after the owner manually changed it.
- A user-driven synthetic GET to a non-existent staging path returned
  404 as expected, and its fake token was not found in available app
  logs. However zero log entries were available for that specific
  time window, so this is **not** proof of complete ingress/egress
  redaction.
- No real Instagram exchange/refresh endpoints are mounted or called;
  neither the OAuth challenge table nor encrypted token vault is
  installed on the shared database.
- User and assistant have NOT yet independently established that Meta
  GET query parameters cannot appear in outbound proxy/APM/exception
  telemetry. **`egress_meta_query_redaction_verified` must remain False.**

### Before any real authorization

1. Independent inspection of outbound Meta query logging, HTTP client
   DEBUG levels, tracing exporters, exception handlers, outbound proxy,
   Render edge behavior and request-target retention.
2. Confirm a secure path if outbound URLs cannot be fully protected:
   do not activate the OAuth flow; choose an infrastructure solution
   verified to prevent token-query leakage.
3. Owner-approved install of the separate OAuth challenge and encrypted
   vault tables with least-privilege roles following a *fresh verified
   backup/restore* and explicit reviewed SQL; never run the blocked
   `step7_oauth_vault_RELEASE_HOLD.sql` on Render.
4. Verified staging callback ingress/logging, exact Meta app and scope
   registration, authenticated Sendro session binding/MFA/account
   ownership, controlled cleanup, key rotation, rate limits and
   authentic professional account identity.
5. Only after separate signoff: a supervised fake-to-real staging
   onboarding test, no Instagram webhooks/messages/Meta App Review
   submission until the independent channel integration passes.

## Absolute hold

Do not merge Draft PR #95 or any stacked PR into `dev`/`main`.
No Render config mutations, production WhatsApp changes, shared
PostgreSQL reads or writes, Meta secrets, live customer DMs, new
paid services, or real authorization.

Protocol reference:
- https://developers.facebook.com/documentation/instagram-platform/instagram-login/access-tokens
- https://github.com/urllib3/urllib3/blob/main/docs/user-guide.rst
