# Instagram Login Phase 4 — authorized encrypted-code claim (23 October 2026)

**Status: DRAFT / DORMANT / NOT DEPLOYED.** Stacked after PR #86 → #85 → #84.

## What this adds

- `backend/app/instagram_oauth_completion.py` permits a fresh-MFA, active tenant **owner/admin** to claim the previously encrypted provider code only once.
- It revalidates the signed Sendro JWT against the current authorization version, current user status and actual membership (not a browser-supplied admin flag).
- An atomic `DELETE ... RETURNING` matches **state digest + same user + same tenant + unexpired + received code**. Once the caller **commits the transaction**, replay is denied across workers.
- Fernet decrypts only after authorization and database selection. A redacted representation avoids accidental secret output in ordinary object logging. Nevertheless, the plaintext code exists briefly in server memory, so it must never be logged, serialized to API responses, or persisted.
- The module does **not** invoke Meta, exchange/refresh tokens, or create a usable Instagram account. It is **not** imported from Sendro's FastAPI main.
- Existing backend CI now explicitly invokes all four Instagram OAuth suites (including three previously absent from the default CI suite), without a separate paid runner/job.

## Important integration contract

A future endpoint may call the new helper only after real Sendro `get_current_active_user` and strict staging/user-session binding. On success, the **outer** transaction must commit before an authorized token exchange; do not perform a network request inside a DB transaction. If that step fails, restart the OAuth authorization rather than replaying the consumed code. The eventual authorization code must be exchanged server-side and the resulting Instagram token encrypted **before** any account connection is shown as successful.

The existing callback GET is still **unmounted** and can leak the Meta code into reverse-proxy/server access logs if enabled without query redaction. No registration with Meta or App Review screencast is appropriate yet.

## Next blockers — not implemented

1. Security review and enforcement of query-string access-log redaction end-to-end, then real authenticated callback bridge with CSRF/session-origin protection and one-time state.
2. Hardened migration and DB ACL for new OAuth challenge table and the eventual encrypted token store, after verified backup/restore and separate permission to change the **shared staging/production** PostgreSQL.
3. Instagram Login API long-lived access-token exchange/expiry/refresh/revocation; separate encrypted vault and tenant/account conflict safeguards. Do not store plaintext tokens in `sendro_channel_accounts`, web browsers or GitHub.
4. Real staging UI `Connect Instagram`; secure profile display and a genuine Meta-review screencast once an authorized test account connects.

## Absolute operational HOLD

- No merge to `dev` or `main`; `dev` auto-deploys and shares production DB.
- No real DB data reads/writes or schema alteration, Render changes, paid service, Meta subscription/publication, Instagram DM reception, or outbound messaging.
- WhatsApp production and Sunset Oia customer data unchanged.
- Unit tests with disposable fixtures are evidence about isolated code behavior, **not** confirmation of safe real-world Instagram onboarding.
