"""One-time Instagram failed-delivery recovery rehearsal in disposable CI ONLY.

No startup hooks, CLI, public API, scheduler, Render operations or Meta calls.
Only an explicitly selected synthetic delivery that previously exhausted
transient DB retries can be returned from 'failed' to 'pending'. The original
encrypted payload and previous failure evidence are preserved. An audit row
is inserted in the SAME transaction as the one allowed state change.
No automatic processing occurs here: a separately scoped test worker is needed.
"""
import hashlib
import hmac
import json
import os
import re

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from .instagram_alert_outbox_ci import _require_disposable_ci
from .instagram_delivery_worker import InstagramPilotScope, _validate_pilot_scope
from .instagram_event_normalizer import (
    InvalidInstagramWebhook, UnsupportedInstagramEvent,
    normalize_instagram_messages,
)
from .instagram_queue_reliability import MAX_RETRY_ATTEMPTS


CONFIRM_RECOVERY = "I_APPROVE_ONE_FAILED_INSTAGRAM_CI_RECOVERY"


class InstagramRecoveryDisabled(PermissionError):
    """Exact disposable CI identity, scope, confirmation or gate is absent."""


class InstagramRecoveryBlocked(RuntimeError):
    """Selection, account ownership, evidence or one-time audit did not match."""


def recover_one_failed_instagram_ci(
    engine, *, scope, expected_digest, expected_attempts,
    encryption_key, confirmation=None, environ=None,
):
    """Requeue exactly one confirmed synthetic failed inbound DM, once.

    Fails before opening a connection for wrong CI identity, approval or
    malformed scope. PostgreSQL FOR UPDATE NOWAIT prevents concurrent
    recovery attempts on the same row. One DB transaction validates tenant
    enrollment, decrypts evidence, INSERTs a unique audit row and updates
    exactly the selected delivery. No payload/customer ID is returned.

    This is an isolated *rehearsal* of a possible control, not a secure live
    recovery authorization, durable full activity log or actual DM send.
    """
    flags = dict(os.environ if environ is None else environ)
    _require_disposable_ci(engine, flags)
    if (
        flags.get("INSTAGRAM_MANUAL_RECOVERY_CI_ENABLED") != "true"
        or confirmation != CONFIRM_RECOVERY
        or not isinstance(scope, InstagramPilotScope)
    ):
        raise InstagramRecoveryDisabled("CI recovery needs exact explicit approval")
    try:
        _validate_pilot_scope(scope)
    except ValueError:
        raise InstagramRecoveryDisabled("Invalid CI recovery scope") from None
    if (
        not isinstance(expected_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
        or isinstance(expected_attempts, bool)
        or not isinstance(expected_attempts, int)
        or expected_attempts < MAX_RETRY_ATTEMPTS
        or not isinstance(encryption_key, str)
        or not encryption_key
    ):
        raise InstagramRecoveryDisabled("Invalid CI recovery evidence")

    try:
        with engine.begin() as db:
            row = db.execute(text("""
                SELECT id, raw_body_sha256, payload_ciphertext, attempts,
                       processing_state, last_error_code
                FROM public.sendro_channel_webhook_deliveries
                WHERE provider = 'instagram' AND id = :id
                FOR UPDATE NOWAIT
            """), {"id": scope.delivery_id}).mappings().first()

            if (
                row is None
                or row["processing_state"] != "failed"
                or row["last_error_code"] != "transient_processing_failure"
                or row["attempts"] != expected_attempts
                or not hmac.compare_digest(row["raw_body_sha256"].strip(), expected_digest)
            ):
                raise InstagramRecoveryBlocked("CI recovery selection no longer matches")

            # Verify the encrypted payload is untouched and belongs to the
            # expected one-business, one-tenant inbound message.
            try:
                raw = Fernet(encryption_key.encode("ascii")).decrypt(
                    bytes(row["payload_ciphertext"])
                )
                if not hmac.compare_digest(
                    hashlib.sha256(raw).hexdigest(), expected_digest
                ):
                    raise InstagramRecoveryBlocked("CI recovery digest mismatch")
                events = normalize_instagram_messages(json.loads(raw))
            except (
                InvalidToken, ValueError, TypeError, UnicodeError,
                json.JSONDecodeError, InvalidInstagramWebhook,
                UnsupportedInstagramEvent,
            ):
                raise InstagramRecoveryBlocked(
                    "CI recovery encrypted event is unsupported"
                ) from None

            if (
                len(events) != 1
                or events[0].direction != "inbound"
                or events[0].business_account_id != scope.business_account_id
            ):
                raise InstagramRecoveryBlocked("CI recovery message scope mismatch")

            account = db.execute(text("""
                SELECT id, tenant_id
                FROM public.sendro_channel_accounts
                WHERE platform = 'instagram'
                  AND external_account_id = :business
                  AND status IN ('testing', 'active')
                FOR UPDATE NOWAIT
            """), {"business": scope.business_account_id}).mappings().first()
            if (
                account is None
                or account["id"] != scope.channel_account_id
                or account["tenant_id"] != scope.tenant_id
            ):
                raise InstagramRecoveryBlocked("CI recovery tenant scope mismatch")

            # Unique delivery_id makes a second manual recovery impossible.
            # Do not audit message body, customer/sender ID or decrypted text.
            audit = db.execute(text("""
                INSERT INTO public.sendro_ci_instagram_recovery_audit (
                    delivery_id, tenant_id, channel_account_id,
                    old_attempts, old_error_code, raw_body_sha256
                ) VALUES (
                    :delivery_id, :tenant_id, :account_id,
                    :attempts, :error_code, :digest
                )
                ON CONFLICT (delivery_id) DO NOTHING
                RETURNING delivery_id
            """), {
                "delivery_id": scope.delivery_id,
                "tenant_id": scope.tenant_id,
                "account_id": scope.channel_account_id,
                "attempts": row["attempts"],
                "error_code": row["last_error_code"],
                "digest": expected_digest,
            }).scalar_one_or_none()
            if audit is None:
                raise InstagramRecoveryBlocked("CI recovery already recorded")

            updated = db.execute(text("""
                UPDATE public.sendro_channel_webhook_deliveries
                SET processing_state = 'pending',
                    next_attempt_at = NULL,
                    processed_at = NULL,
                    last_error_code = 'manual_ci_recovery_once'
                WHERE provider = 'instagram' AND id = :id
                  AND processing_state = 'failed'
                  AND attempts = :attempts
                  AND raw_body_sha256 = :digest
                  AND last_error_code = 'transient_processing_failure'
            """), {
                "id": scope.delivery_id,
                "attempts": expected_attempts,
                "digest": expected_digest,
            })
            if updated.rowcount != 1:
                raise InstagramRecoveryBlocked("CI recovery state conflict")
    except InstagramRecoveryBlocked:
        raise
    except Exception:
        # Never surface raw SQL errors, original webhook text or encryption keys.
        raise InstagramRecoveryBlocked("CI recovery not committed") from None

    # Only prepares one exact delivery for separately scoped test processing.
    return {"state": "pending", "audit_written": True}
