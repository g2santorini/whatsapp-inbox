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


def _decode_events(payload_ciphertext: bytes, key: str):
    raw = Fernet(key.encode("ascii")).decrypt(bytes(payload_ciphertext))
    envelope = json.loads(raw)
    return normalize_instagram_messages(envelope)


def process_one_pending_instagram_delivery(engine, encryption_key: str):
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
            SELECT id, payload_ciphertext
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram'
              AND processing_state = 'pending'
            ORDER BY id ASC
            LIMIT 1
        """
        if engine.dialect.name == "postgresql":
            select_sql += " FOR UPDATE SKIP LOCKED"
        delivery = db.execute(text(select_sql)).mappings().first()
        if delivery is None:
            return InstagramProcessingResult(None, "idle")

        delivery_id = delivery["id"]
        try:
            events = _decode_events(delivery["payload_ciphertext"], encryption_key)
        except (InvalidInstagramWebhook, UnsupportedInstagramEvent,
                ValueError, TypeError, UnicodeError, json.JSONDecodeError):
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
