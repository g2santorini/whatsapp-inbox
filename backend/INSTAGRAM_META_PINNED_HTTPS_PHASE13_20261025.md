# Instagram Login Phase 13 — dedicated pinned HTTPS transport

**STATUS: DORMANT DRAFT / NO REAL META OR RENDER REQUESTS.** Stacked
after PR #95 → #94 → #93 → #92 → #91 → #90 → #89 → #88 → #87 →
#86 → #85 → #84. No merge or deployment is authorized.

## Risk addressed

The standard `requests` module and default `requests.Session` trust
environment configuration unless disabled: HTTPS_PROXY, ALL_PROXY, NETRC
authentication, custom REQUESTS_CA_BUNDLE, etc. Those may route the
Instagram Login app secret or access token through unknown intermediaries.

For Meta Instagram Login, two **GET** endpoints transmit sensitive access
tokens (one also transmits the App Secret) in query parameters. Our previous
PR #95 blocked unapproved calls and DEBUG log modes, but once approved it
was still possible for Python's default HTTP client to honor an
unexpected environment proxy or .netrc configuration.

## Implemented in isolated code

- `backend/app/instagram_meta_transport.py`: a private, short-lived
  Requests Session scoped to Instagram Login. It sets
  `trust_env=False`, leaves environment proxy/netrc out, enforces TLS
  certificate verification, removes plain HTTP adapter, denies
  redirects, rejects timeouts outside a bounded range and prevents
  overriding proxy/auth/TLS/redirect options.
- Every real transport request is pinned by **exact URL+method**:
  - `POST https://api.instagram.com/oauth/access_token`
  - `GET https://graph.instagram.com/me`
  - `GET https://graph.instagram.com/access_token`
  - `GET https://graph.instagram.com/refresh_access_token`
  No arbitrary-host requests or automatic retry attempts are allowed.
  Per-call session closes when the call completes.
- `instagram_login_oauth.py` and `instagram_token_lifecycle.py` now
  use the above session by default, instead of the global `requests`
  convenience methods. Existing explicitly injected mock sessions
  remain test-only. The PR #95 **operator-approval egress gate** still
  runs BEFORE the HTTP session is created or any network request starts.
- Synthetic tests monkeypatch Requests' base `Session.request` method;
  they prove proxy/NETRC/environment settings are ignored, the exact
  allowlist is enforced, dangerous kwargs are rejected before
  transmission, and the actual token exchange functions create the
  restricted real session instead of the global default.
- Adds the tests to an already existing backend CI command.
  **No new job, service, GitHub runner or fee.**

## Remaining operational limits / no-go

- Does **not** prevent Render's network edge, any outbound TLS proxy,
  approved observability instrumentation, OS tracing or legitimate Meta
  logging from seeing the final request. HTTPS can protect traffic in
  transit, but external infrastructure must still be verified.
- This code cannot prove the operator booleans in PR #90/95 are true.
  They MUST remain false until independent, real-world inspection of
  log destinations and monitoring/exporters; a synthetic test is not
  that inspection.
- A separately approved outbound proxy might be operationally required
  by infrastructure. This restricted transport deliberately fails to
  honor environment proxies; the real runtime must be reviewed for
  connectivity before any live Meta credentials are used.
- The actual OAuth callback is not mounted and its challenge/token
  vault tables are not installed in shared production/staging PostgreSQL.
  The SQL from PR #94 retains its unconditional RELEASE HOLD.
- The staging backend currently has `--no-access-log` set by the
  operator and the Render workspace is Hobby, but application and
  provider egress log safety have not been fully attested.
- Never merge this stack into `dev`/`main` or deploy or modify
  Render/Meta/DB without separately reviewed operational authorization.
  Do not enable webhooks, DMs, Meta App Review or customer onboarding.

Public transport reference:
https://requests.readthedocs.io/en/latest/user/authentication/
https://requests.readthedocs.io/en/latest/user/advanced/
