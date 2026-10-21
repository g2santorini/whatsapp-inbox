# Instagram: single failed-DM recovery and audit rehearsal (CI only)

**2026-10-21 — No live worker, Meta subscription, actual recovery, Render
PostgreSQL write, service configuration change or customer data operation.**

## The narrowly approved synthetic case

One encrypted Instagram webhook delivery became terminal `failed`
after at least five unsuccessful, **transient database** attempts. The
existing worker can no longer select it, but we must not blindly move
arbitrary `quarantined`/unsupported events to a pending conversation.

`backend/app/instagram_failed_recovery_ci.py` exports only the inert,
explicit-call `recover_one_failed_instagram_ci()` library function.
No FastAPI route, CLI, scheduled task, startup code, webhook subscription,
Meta API call, or human-facing recovery button exists.

Before any database connection, it requires all of:
- exact ephemeral GitHub Actions PostgreSQL (`127.0.0.1:55439`,
  user `sendro_ci`, database `sendro_ig_ci`);
- `GITHUB_ACTIONS=true`,
  `SENDRO_INSTAGRAM_PG_CI_APPROVAL=ephemeral-local-service-only`,
  `INSTAGRAM_ALERT_OUTBOX_CI_ENABLED=true`;
- additional `INSTAGRAM_MANUAL_RECOVERY_CI_ENABLED=true` plus the explicit
  exact confirmation `I_APPROVE_ONE_FAILED_INSTAGRAM_CI_RECOVERY`;
- exact `InstagramPilotScope` delivery ID, tenant ID, channel account ID,
  business account ID, expected original raw-body SHA-256 and current
  exhausted-attempt count, and the CI-only generated Fernet key.

All event/customer IDs are synthetic. The CI fixture, not the application,
creates a `sendro_ci_instagram_recovery_audit` table on disposable PostgreSQL.

## State transition contract

The function uses PostgreSQL row locks `FOR UPDATE NOWAIT` and one transaction.

1. Lock **only the exact selected** Instagram delivery.
2. Confirm `failed` + `transient_processing_failure` + exact
   expected attempts (at least five) and original payload SHA-256.
3. Decrypt the existing ciphertext, verify its SHA-256 and normalize.
   Allow **exactly one inbound** supported DM from the expected business.
   Reject batch, outgoing echo, unknown/unsupported format, wrong key,
   wrong tenant, mismatched account, disabled/unregistered account.
4. Verify an active/test Instagram account belongs to the exact approved
   tenant and account ID.
5. Insert a unique per-delivery test-only audit record preserving its
   original attempts, prior generic error code, digest and tenant/account
   numeric IDs, but **no plaintext, sender/customer ID or ciphertext**.
6. CAS-update the *same row* from `failed` to `pending`,
   preserve original ciphertext, SHA-256, retry count, and an explicit
   `manual_ci_recovery_once` marker. Audit and state change commit or
   roll back together. Audit uniqueness blocks second recovery.

The function **does not process or acknowledge the message**. The test
explicitly invokes `process_one_pending_instagram_delivery(...,
pilot_scope=exact_scope)` separately, proving only the chosen tenant's
message is inserted once; no fallback to the other tenant's failed DM.

## Rehearsed denial / failure scenarios

- Wrong CI identity, manual gate, confirmation, malformed scope or
  digest refused before DB access.
- Wrong Fernet key, changed digest, attempts mismatch, tenant mismatch,
  business mismatch, disabled account, multi-event envelope, outbound
  echo, pending/quarantined/nontransient failure all refuse recovery
  without changing delivery state.
- Another transaction holds the delivery lock: recovery fails closed
  without waiting/processing a different delivery.
- CI audit storage unavailable: no partial recovery, original
  ciphertext and failed status preserved.
- Repeated recovery of an already audited delivery blocked, even if
  a disposable test artificially sets it back to failed.
- Expected account's synthetic message processed once; another
  company's failed message is left untouched.

## This is NOT production-ready recovery

The raw webhook was only synthetically generated and stored through the
test ingestion path; there is no new Meta signature verification. The
CI gate and literal confirmation phrase are *not real human authorization*.
The dedicated test audit table is not an immutable privileged production
journal and is not installed on the shared Sendro database.

Future real recovery must have operator MFA/role approval, incident context
and independent tenant ownership evidence, secure decryption-key custody,
append-only audited actor/incident identity, durable incident lifecycle,
time-bounded lock coordination with the actual supervised worker, and a
tested atomic recovery workflow that does not expose the pending row to
an unrelated worker. It also needs alert escalation, rate limiting, a
fresh verified backup, and a staffed stop/rollback plan.

**Do not enable Instagram Meta webhook subscriptions, set any CI flags on
Render, create recovery tables on Render or requeue real customer messages.**
The WhatsApp/registry independent owner approval is a separate Render
support dependency.
