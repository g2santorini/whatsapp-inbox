# Instagram Login Phase 10 — tenant-scoped account metadata status (24 October 2026)

**DRAFT / READ-ONLY / UNMOUNTED / NO RENDER OR META DEPLOYMENT.**
Stacked on #92 → #91 → #90 → #89 → #88 → #87 → #86 → #85 → #84.

## Implemented but inactive

1. `backend/app/instagram_account_status.py`: opt-in GET-only
   `/channels/instagram/account-status?tenant_id=...` router factory.
   The actual Sendro `get_current_active_user` / OAuth2 Bearer dependencies
   must be explicitly injected by a future separately reviewed mount.
   It is **disabled by default** and **not included in main.py**.
   Auth is revalidated using signed JWT/auth-version, MFA proof from the
   last 10 minutes, user status and **active tenant owner/admin membership**.
2. The query joins the actual
   `public.sendro_channel_accounts` registry to the prospective
   `public.sendro_instagram_token_vault` table on exact
   tenant ID, channel account ID and external Instagram account ID.
   It **selects NO ciphertext, token, code, webhook payload, customer message,
   Meta secret, provider account ID or provider credential**.
3. Read response only contains registry label (not an independently
   verified Meta username), channel account ID, registration status
   `testing|active`, an expiry timestamp and a cautious credential status:
   `not_linked`, `stored_unverified`, `expired`. Both
   `messaging_enabled` and `meta_authorization_verified_now` are
   **always false**. Even a nonexpired token does NOT mean Meta approval,
   correct permission, functioning DM transport or a valid connection.
4. Separate `InstagramAccountStatusPreview.jsx` and CSS provide a compact
   staging-only, read-only display alongside the previously disabled
   Connect Instagram card. The parent passes `enabled={false}` and NO
   `statusLoader`; therefore **NO FETCH IS PERFORMED** and the
   panel honestly displays 'not activated' in the future approved staging
   UI. A safe `getInstagramAccountStatus` API adapter exists but is not
   called. A future reviewer may inject a read-only loader after the
   real status endpoint and schema are independently approved.
5. Isolated disposable SQLite/FastAPI tests verify tenant boundaries,
   stale MFA, disabled/developer accounts, viewer denial, wrong provider
   ID/WhatsApp exclusion, token-free response and safe 503 on missing vault
   table. Node tests verify staging-only gating, frontend payload
   validation, unknown states/duplicate IDs/foreign tenant and no secret
   reflection. Both use existing CI jobs (no new runners).

## Strict operational HOLD

- Neither OAuth challenge table nor vault table has been installed.
  Staging and production **share PostgreSQL**. Do not mount this
  endpoint or turn on a loader until actual approved schema, limited DB
  permissions and a separately verified fresh backup/restore are ready.
- Even if a registry row exists, that does not prove a user completed
  Instagram Login. The profile verification chain must be legitimately
  completed and independently checked. A real provider permission/health
  check is NOT performed by this metadata endpoint.
- There is NO live browser session bridge, pending-state persistence,
  registered Meta callback, automatic refresh or actual Instagram DM
  delivery. The Meta App Review screencast must show real authorized
  functionality, not an invented 'Connected' label.
- Real startup integration must inject Sendro's **actual** current user,
  bearer-token and DB dependencies; synthetic tests use explicit fakes.
- Browser does not fetch metadata until `enabled` is reviewed and
  switched on separately. Never use a plaintext Meta credential in API
  output or browser state.
- Existing account labels are registry descriptions, not always Instagram
  usernames. A live verification step must confirm provider identity and
  uniqueness before showing it as a real connected account.
- For Render account access, a workspace selection requires user confirmation.
  No workspace was selected, no service or logs inspected or changed.
- **Do not merge to dev/main or deploy**, do not modify the live shared DB,
  Meta configuration, webhook subscriptions, workers, WhatsApp messages,
  or paid services. CI tests are synthetic and are not a release approval.

### Subsequent priorities

1. Independently inspect staging proxy/ASGI/telemetry log redaction after
   user workspace confirmation; get operational go/no-go evidence.
2. Prepare the minimal manual vault/challenge table schema and limited roles
   with an independently verified backup/restore (no automatic migration).
3. Implement genuine signed tenant-admin session and Meta callback lifecycle,
   securely bind the real Instagram ID to an account registry and avoid
   cross-tenant claims.
4. Only then activate staged read-only account metadata display and,
   subsequently, the actual Connect Instagram button.
