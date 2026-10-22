# Instagram dedicated PostgreSQL read-only observer — role-verified implementation

**Prepared 2026-10-22. No Render PostgreSQL role or credential created.**
**No service, cron, scheduler, Meta subscription, actual notification,
Instagram worker or live DB read/write was started.** Production/main
remains untouched. The new Python library is NOT imported by
`backend/app/main.py` and has NO CLI or startup hook.

## Why this implementation is a real step forward

Previous CI alert observers read queue health using Sendro's general
application database connection. Production's `sendro_user` is the
shared DB owner and has excessive privileges for monitoring. An
independently started monitor using the same credentials would
potentially expose encrypted message payloads, tenant mapping, or
database mutation abilities.

`backend/app/instagram_restricted_observer.py` introduces a
**genuinely executable single-pass PostgreSQL read-only observation**
function, but it requires a separate login principal
`sendro_instagram_observer_ro` and explicit opt-in. It is not
a database owner or worker.

The observer queries ONLY these four metadata columns from
`public.sendro_channel_webhook_deliveries`:

- `provider`: exact Instagram-only filter
- `processing_state`: pending / processing / processed / quarantined / failed
- `received_at`: aggregate age, never per-delivery data
- `next_attempt_at`: due and deferred aggregate counts

No `id`, `raw_body_sha256`, `payload_ciphertext`,
`last_error_code`, conversation or customer info is selected.
A single aggregate `COUNT ... FILTER` / `MIN` query returns generic
state counts and the five existing queue-health alert codes.
It is explicitly executed inside `SET TRANSACTION READ ONLY` with
a 2.5-second statement timeout and 500ms lock timeout.

### Fail closed before reading

1. The engine's URL must identify the named **separate** observer role,
   use the psycopg PostgreSQL driver and be explicitly opted in. Tests
   require the exact existing GitHub Actions disposable
   `127.0.0.1:55439/sendro_ig_ci` identity and approval flag.
2. Any future live configuration ALSO requires a separate owner
   attestation value, exact database name `sendro`, a non-loopback
   host and SSL mode `require` or `verify-full`. None of those
   settings have been configured in Render; there is no live CLI or
   scheduler to invoke them.
3. The database session must return `current_user = session_user =
   sendro_instagram_observer_ro`, never `sendro_user` or
   `sendro_ci`. SQL role attributes must deny superuser,
   role creation, database creation, replication and bypass-RLS.
4. Database/schema CREATE permissions; table- and column-level DML;
   SELECT privileges over delivery IDs, ciphertext, hashes, error
   details; and whole-table SELECT of `users`/`channel_messages`
   must all be **denied**. Only the four approved metadata columns
   may be readable. Failures return sanitized errors, not connection
   strings, user identifiers or SQL/payload excerpts.

**Note:** A complete live least-privilege audit must additionally
review all DB grants, role memberships, default privileges, pg_hba,
extension capabilities, ownership and network restrictions. The
function's privilege probe is an independent fail-closed layer,
NOT a replacement for a DBA-managed, independently owned role.

## GitHub Actions actual privilege proof

`backend/tests/test_instagram_restricted_observer_postgres_ci.py`
runs ONLY after existing ephemeral PostgreSQL safeguards. There it
creates an actual **temporary login role** with column-level
`GRANT SELECT (provider, processing_state, next_attempt_at, received_at)`
to that one Instagram queue table. It verifies:

- An empty Instagram queue returns only fixed redacted zero counters.
- Fake encrypted ingress + quarantine match the original queue
  reliability status, while no cross-tenant chat is inserted.
- Pending backlog/staleness behavior matches established alert semantics.
- The limited account receives PostgreSQL permission errors when
  trying to query `id`, `payload_ciphertext`,
  `raw_body_sha256`, whole delivery rows, `users` or messages,
  and when attempting `UPDATE`/`DELETE`.
- If someone grants the role extra ciphertext SELECT or column-level
  UPDATE privileges in this **disposable test**, observer execution
  **stops** instead of accepting the elevated privileges.
- No approval, the wrong connection identity, or invalid thresholds
  are rejected before query execution.

Every privilege-changing SQL statement in these tests targets the
temporary GitHub service; none run on Render. The temporary role is
revoked/dropped by the fixture.

## Next real-world blockers, not silently completed by this PR

1. **Human Render/PostgreSQL support resolution** of a truly
   independently managed non-owner role. The current owner-role
   restrictions, independent ownership boundaries and verified backup
   are not signed off. Do not attempt live `CREATE ROLE`,
   `GRANT`, `REVOKE`, schema changes or connection changes.
2. Approved, separately provided least-privilege login, password/TLS
   trust model, strict network access and credential rotation. Do not
   put current `DATABASE_URL`, `sendro_user`, or Meta secrets
   into any observer container.
3. A separate **supervised periodic service** and durable heartbeat,
   independently monitored by the previously designed watchdog;
   this Python function itself has no timer/daemon and does not
   persist a heartbeat.
4. A verified real operational notifier/recipient with independent
   escalation and MFA-based incident access. The browser
   notifications cannot replace out-of-band operator receipt.
5. An operator-approved fresh restore point, Meta account subscription
   impact assessment, exact tenant/account ownership mapping and
   attended bounded first DM pilot.

**This PR is an implementation rehearsal, not a GO signal.**
The first real Instagram DM remains **HOLD**. No additional
hosting/database expense is created by this change.
