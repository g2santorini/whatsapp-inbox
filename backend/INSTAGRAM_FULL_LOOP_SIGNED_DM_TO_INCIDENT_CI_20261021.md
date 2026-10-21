# Instagram signed DM → incident → review: CI-only full-loop rehearsal

**Date:** 2026-10-21. **No real Meta messages, subscribers, Render DB,
staff emails/push, new background service, credentials or production deploy.**

## Why this integration test

The previous Sendro Instagram CI phases checked components in isolation:
- Signed, HMAC-verified POST into an encrypted PostgreSQL webhook queue;
- Manual bounded worker processing/quarantine with no unknown-tenant routing;
- Read-only redacted queue-health checks, durable aggregate alert outbox,
  incident episodes, throttled fake dispatch / transport acceptance,
  and separate exact-version audited human confirmation;
- An unmounted Incident Center using signed recent-MFA test principals
  and a separately scoped global incident responder grant;
- The exact original Sendro login/active-user function bodies exercised
  as source-level tests in PR #77.

A passing individual test does NOT prove a coherent cross-component
lifecycle. This file tests their cooperation **in one explicit sequence**
against the same disposable PostgreSQL database.

## Executable scenario

`backend/tests/test_instagram_signed_dm_to_incident_full_loop_ci.py`
reuses existing test fixtures (`episode_db`, `ci_http`) and calls only
explicitly gated test-only code. A synthetic signed webhook from a
**fabricated, deliberately unregistered** Instagram business is chosen so
that processing quarantines it, rather than inserting an inbox chat into
any of the two unrelated enrolled test tenants.

1. A correctly signed but initially disabled webhook is refused with
   HTTP 503, and a wrong HMAC signature is refused with HTTP 403;
   neither operation creates a queue or incident record.
2. The **CI-local only** ingestion toggle is set on in the pytest process;
   POST of the correct signed event returns `stored`.
   Payload is preserved encrypted in the ephemeral queue.
3. The existing bounded test operator executes exactly one manual
   worker run; the unregistered business is quarantined, and **zero**
   conversation/message records are inserted.
4. The test **explicitly** reads aggregate queue health, validates
   five numeric state counts and persists the redacted alert into the
   CI-only durable outbox. It separately invokes the CI-only incident
   observer, creating exactly one episode/dispatch.
5. A different synthetic TestClient GETs the **unmounted** Incident Center.
   Missing authentication, wrong role, missing recent signed MFA and
   missing global responder grant all deny access. Only a separately
   authorized synthetic admin can list the sanitized incident.
6. A fake notification transport fails. The alert remains `pending`
   with a bounded retry delay; **human acknowledgment is still denied**.
   Repeated samples of the persistent problem do not stage new alert
   versions (one continuous episode).
7. A subsequent **fake callback** accepts the alert. Transport
   acceptance does NOT imply human acknowledgment: an explicit
   exact-version authenticated HTTP POST is still required.
   The test confirms one authorized, audited review; invalid episode,
   ordinary operator and duplicate review are rejected.
8. Replaying the same signed webhook is idempotent. The encrypted
   delivery remains quarantined, zero chats are created and no new
   incident episode/audit review is generated. All observable
   outputs are checked not to contain any synthetic DM text, sender,
   business ID, ciphertext, or encryption key.

A second test verifies that an invalid signature never results in an
incident/notification at all, even when a CI-local gate is enabled.

## Deliberate non-goals and gaps

- **There is NO production orchestration.** The test itself manually
  calls worker, outbox persistence, incident observer, fake transport
  and synthetic review. Nothing starts automatically, runs as a daemon
  or sends a real email, push, Slack or Meta message.
- Durable outbox persistence and episode/dispatch staging are **separate
  explicitly invoked steps**, not one atomic cross-component
  transaction. If the test process dies between them, a real system
  would need a durable supervised replay/observer to catch the incident.
- The signed webhook is **synthetic**; the signing secret and Fernet key
  are generated/test-only, not authorized Meta credentials.
- This full-loop test uses the same synthetic signed-MFA user identity
  fixture as PR #76 for the incident HTTP endpoint. PR #77 separately
  exercises actual Sendro auth function bodies on isolated synthetic
  users; no actual production `main.py` startup or live login is part
  of this full-loop test.
- The alert is a **global aggregate**, not tenant-specific. Normal
  Instagram tenant operators must never view it without independent
  global incident responder delegation.
- A quarantined unregistered event is not automatically requeued or
  delivered to another tenant. There is no live recovery button or
  outbound Instagram DM send path.

**Live activation remains BLOCKED.** It requires a securely owned,
independently authorized alert/episode/dispatch schema and migration,
fresh verified backup, actually supervised observer, real operator
notification destination and SLA, session-derived real principal/MFA,
operator recovery/runbook and separately approved Meta pilot. The
Render independent schema ownership question remains a separate
external dependency. Do not mount the CI-only API or set its flags
on Render.
