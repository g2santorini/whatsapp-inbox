"""Instagram DM processing for the isolated, encrypted webhook queue.

INERT BY DEFAULT: no scheduler, app route, or startup hook invokes this.
The Instagram webhook remains OFF until delivery and authorization are tested.

A future *separate* worker may call process_one_pending_instagram_delivery.
PostgreSQL uses FOR UPDATE SKIP LOCKED; all conversation/message changes and
the delivery completion marker commit in one database transaction. Any
unexpected database exception rolls back the whole delivery for retry.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .instagram_queue_reliability import is_transient_database_failure

from .instagram_event_normalizer import (
    InvalidInstagramWebhook,
    UnsupportedInstagramEvent,
    normalize_instagram_messages,
)


@dataclass(frozen=True)
class InstagramProcessingResult:
    delivery_id: int | None
    status: str
    inserted_messages: int = 0


class _UnroutableAccount(Exception):
    """Signed Instagram delivery without a registered/approved business."""


@dataclass(frozen=True)
class InstagramPilotScope:
    """Explicit one-delivery, one-inbound-message, one-account pilot boundary.

    Supplying a scope can only narrow which encrypted delivery is processed.
    The public webhook, unsupervised worker, and default batch mode do not
    construct a pilot scope. The operator entry point has additional gates.
    """

    delivery_id: int
    tenant_id: int
    channel_account_id: int
    business_account_id: str


def _validate_pilot_scope(scope):
    if scope is None:
        return
    if (
        not isinstance(scope, InstagramPilotScope)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (
                scope.delivery_id, scope.tenant_id, scope.channel_account_id,
            )
        )
        or not isinstance(scope.business_account_id, str)
        or not scope.business_account_id.strip()
        or scope.business_account_id != scope.business_account_id.strip()
    ):
        raise ValueError("Invalid Instagram pilot selection")


def _decode_events(payload_ciphertext: bytes, key: str):
    raw = Fernet(key.encode("ascii")).decrypt(bytes(payload_ciphertext))
    envelope = json.loads(raw)
    return normalize_instagram_messages(envelope)


class InstagramTransientDeliveryFailure(RuntimeError):
    """Sanitized retry signal emitted only AFTER a worker transaction rolls back."""

    def __init__(self, delivery_id: int, expected_attempts: int):
        super().__init__("Retryable Instagram database transaction failed")
        self.delivery_id = delivery_id
        self.expected_attempts = expected_attempts


def process_one_pending_instagram_delivery(
    engine, encryption_key: str, *, pilot_scope: InstagramPilotScope | None = None
):
    """Preserve existing worker API; optionally narrow to one approved DM.

    The scoped path is intended ONLY for a future, separately authorized,
    supervised one-off pilot. No callers enable it at application startup.
    """
    _validate_pilot_scope(pilot_scope)
    tracked = {}
    try:
        return _process_one_pending_instagram_delivery(
            engine, encryption_key, tracked, pilot_scope=pilot_scope
        )
    except DBAPIError as error:
        if tracked and is_transient_database_failure(error):
            raise InstagramTransientDeliveryFailure(
                tracked["id"], tracked["attempts"]
            ) from None
        raise


def _process_one_pending_instagram_delivery(
    engine, encryption_key: str, tracked, *, pilot_scope=None
):
    """Process at most one queued envelope. NEVER invoke on public requests.

    Invalid/unsupported payloads and unregistered business IDs are quarantined
    as encrypted deliveries, without partially writing any messages. Known
    messages are inserted idempotently by (account_id, provider_message_id).
    Duplicate notifications must not increase unread counts.
    """
    if not encryption_key:
        raise ValueError("Instagram webhook encryption key is required")

    with engine.begin() as db:
        select_sql = """
            SELECT id, payload_ciphertext, attempts
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram'
              AND processing_state = 'pending'
              AND (next_attempt_at IS NULL OR next_attempt_at <= CURRENT_TIMESTAMP)
        """
        select_args = {}
        if pilot_scope is not None:
            # Bind the exact selected ID before FOR UPDATE. Never fall back
            # to another pending envelope if this ID is missing or busy.
            select_sql += " AND id = :pilot_delivery_id\n"
            select_args["pilot_delivery_id"] = pilot_scope.delivery_id
        select_sql += " ORDER BY id ASC LIMIT 1"
        if engine.dialect.name == "postgresql":
            select_sql += " FOR UPDATE SKIP LOCKED"
        delivery = db.execute(text(select_sql), select_args).mappings().first()
        if delivery is None:
            return InstagramProcessingResult(None, "idle")

        delivery_id = delivery["id"]
        # Only emit retry context for this locked row if its DB transaction
        # fails. The outer wrapper runs *after* rollback is completed.
        tracked.update(id=int(delivery_id), attempts=int(delivery["attempts"]))
        try:
            events = _decode_events(delivery["payload_ciphertext"], encryption_key)
        except (InvalidInstagramWebhook, UnsupportedInstagramEvent,
                ValueError, TypeError, UnicodeError, json.JSONDecodeError):
            if pilot_scope is not None:
                # An attended single-DM pilot must not mutate an unknown
                # envelope. Leave it encrypted/pending for operator review.
                return InstagramProcessingResult(delivery_id, "blocked")
            # Do not log the raw payload or even event/customer identifiers.
            db.execute(text("""
                UPDATE public.sendro_channel_webhook_deliveries
                SET processing_state = 'quarantined',
                    attempts = attempts + 1,
                    last_error_code = 'unsupported_or_invalid_event',
                    processed_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": delivery_id})
            return InstagramProcessingResult(delivery_id, "quarantined")

        if pilot_scope is not None and (
            len(events) != 1
            or events[0].direction != "inbound"
            or events[0].business_account_id != pilot_scope.business_account_id
        ):
            # No multi-message/batch/echo processing in a single-DM pilot.
            # This also blocks data written for unexpected subscribed accounts.
            return InstagramProcessingResult(delivery_id, "blocked")

        # Resolve *every* business ID before creating any data. Fail closed
        # when an account has not been enrolled or has been disabled.
        accounts = {}
        for business_id in {event.business_account_id for event in events}:
            account_sql = """
                SELECT id, tenant_id
                FROM public.sendro_channel_accounts
                WHERE platform = 'instagram'
                  AND external_account_id = :business_id
                  AND status IN ('testing', 'active')
            """
            if engine.dialect.name == "postgresql":
                account_sql += " FOR UPDATE"
            account = db.execute(text(account_sql), {
                "business_id": business_id,
            }).mappings().first()
            if account is None:
                if pilot_scope is not None:
                    return InstagramProcessingResult(delivery_id, "blocked")
                db.execute(text("""
                    UPDATE public.sendro_channel_webhook_deliveries
                    SET processing_state = 'quarantined',
                        attempts = attempts + 1,
                        last_error_code = 'unregistered_business_account',
                        processed_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """), {"id": delivery_id})
                return InstagramProcessingResult(delivery_id, "quarantined")
            accounts[business_id] = account

        if pilot_scope is not None:
            account = accounts[pilot_scope.business_account_id]
            if (
                account["id"] != pilot_scope.channel_account_id
                or account["tenant_id"] != pilot_scope.tenant_id
            ):
                return InstagramProcessingResult(delivery_id, "blocked")

        # Before writing any conversations, reject provider-ID collisions
        # that point at another customer or direction. This prevents ghost
        # conversations from inconsistent or spoofed replays.
        seen_message_owners = {}
        for event in events:
            key = (event.business_account_id, event.message_id)
            owner = (event.instagram_scoped_customer_id, event.direction)
            if key in seen_message_owners and seen_message_owners[key] != owner:
                if pilot_scope is not None:
                    return InstagramProcessingResult(delivery_id, "blocked")
                db.execute(text("""
                    UPDATE public.sendro_channel_webhook_deliveries
                    SET processing_state = 'quarantined',
                        attempts = attempts + 1,
                        last_error_code = 'message_identity_conflict',
                        processed_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """), {"id": delivery_id})
                return InstagramProcessingResult(delivery_id, "quarantined")
            seen_message_owners[key] = owner

            account_id = accounts[event.business_account_id]["id"]
            previous = db.execute(text("""
                SELECT c.external_customer_id, m.direction
                FROM public.sendro_channel_messages m
                JOIN public.sendro_channel_conversations c
                  ON c.id = m.conversation_id
                 AND c.tenant_id = m.tenant_id
                 AND c.channel_account_id = m.channel_account_id
                WHERE m.channel_account_id = :account_id
                  AND m.provider_message_id = :message_id
            """), {"account_id": account_id, "message_id": event.message_id}).mappings().first()
            if previous is not None and (
                previous["external_customer_id"] != owner[0]
                or previous["direction"] != owner[1]
            ):
                if pilot_scope is not None:
                    return InstagramProcessingResult(delivery_id, "blocked")
                db.execute(text("""
                    UPDATE public.sendro_channel_webhook_deliveries
                    SET processing_state = 'quarantined',
                        attempts = attempts + 1,
                        last_error_code = 'message_identity_conflict',
                        processed_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """), {"id": delivery_id})
                return InstagramProcessingResult(delivery_id, "quarantined")

        # The account's row lock serializes thread creation for one business.
        # Unique constraints also protect against replay from other batches.
        inserted_count = 0
        media_value = (
            "CAST(:media_json AS JSONB)"
            if engine.dialect.name == "postgresql" else "json(:media_json)"
        )

        for event in events:
            account = accounts[event.business_account_id]
            account_id = account["id"]
            tenant_id = account["tenant_id"]
            # Already persisted provider messages cannot create a new thread
            # or count as unread again, even when a duplicate delivery differs.
            already_saved = db.execute(text("""
                SELECT 1 FROM public.sendro_channel_messages
                WHERE channel_account_id = :account_id
                  AND provider_message_id = :message_id
            """), {"account_id": account_id, "message_id": event.message_id}).scalar()
            if already_saved:
                continue
            args = {
                "tenant_id": tenant_id,
                "account_id": account_id,
                "customer_id": event.instagram_scoped_customer_id,
            }

            db.execute(text("""
                INSERT INTO public.sendro_channel_conversations
                    (tenant_id, channel_account_id, external_customer_id)
                VALUES (:tenant_id, :account_id, :customer_id)
                ON CONFLICT (channel_account_id, external_customer_id)
                DO NOTHING
            """), args)
            conversation_id = db.execute(text("""
                SELECT id FROM public.sendro_channel_conversations
                WHERE tenant_id = :tenant_id
                  AND channel_account_id = :account_id
                  AND external_customer_id = :customer_id
            """), args).scalar_one()

            event_at = (
                datetime.fromtimestamp(event.timestamp_ms / 1000, tz=timezone.utc)
                if event.timestamp_ms is not None
                else datetime.now(timezone.utc)
            )
            is_media = bool(event.attachments)
            message_args = {
                **args,
                "conversation_id": conversation_id,
                "message_id": event.message_id,
                "direction": event.direction,
                "message_type": "media" if is_media else "text",
                "content": event.text,
                "media_json": (
                    json.dumps(list(event.attachments), separators=(",", ":"))
                    if is_media else None
                ),
                "event_at": event_at,
            }
            inserted_id = db.execute(text(f"""
                INSERT INTO public.sendro_channel_messages (
                    tenant_id, channel_account_id, conversation_id,
                    provider_message_id, direction, message_type,
                    content, media_json, provider_timestamp
                ) VALUES (
                    :tenant_id, :account_id, :conversation_id,
                    :message_id, :direction, :message_type,
                    :content, {media_value}, :event_at
                )
                ON CONFLICT (channel_account_id, provider_message_id)
                DO NOTHING
                RETURNING id
            """), message_args).scalar_one_or_none()
            if inserted_id is None:
                continue

            inserted_count += 1
            db.execute(text("""
                UPDATE public.sendro_channel_conversations
                SET unread_count = unread_count + :unread_delta,
                    status = CASE
                        WHEN :is_inbound = 1 THEN 'open' ELSE status END,
                    last_message_at = CASE
                        WHEN last_message_at IS NULL
                          OR last_message_at < :event_at
                        THEN :event_at ELSE last_message_at END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :conversation_id AND tenant_id = :tenant_id
                  AND channel_account_id = :account_id
            """), {
                **message_args,
                "unread_delta": 1 if event.direction == "inbound" else 0,
                "is_inbound": 1 if event.direction == "inbound" else 0,
            })

        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET processing_state = 'processed',
                attempts = attempts + 1,
                last_error_code = NULL,
                processed_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {"id": delivery_id})
        return InstagramProcessingResult(delivery_id, "processed", inserted_count)
