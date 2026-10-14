"""Secure storage for signed Instagram webhook deliveries.

This is an internal, encrypted, durable inbox, NOT a message processor.
Never enable live Instagram webhook subscriptions until a worker can
safely route, deduplicate and persist all event types to the correct tenant.
"""
import hashlib
import json

from cryptography.fernet import Fernet
from sqlalchemy import text


MAX_INSTAGRAM_WEBHOOK_BODY_BYTES = 256 * 1024


def validate_instagram_envelope(raw_body: bytes) -> None:
    """Reject arbitrary/non-Instagram payloads without logging personal data."""
    try:
        envelope = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid Instagram webhook JSON") from exc

    if not isinstance(envelope, dict) or envelope.get("object") != "instagram":
        raise ValueError("Not an Instagram webhook object")
    if not isinstance(envelope.get("entry"), list):
        raise ValueError("Invalid Instagram webhook entry list")


def persist_instagram_webhook(
    raw_body: bytes,
    encryption_key: str,
    database_engine,
) -> None:
    """Commit a signed delivery to durable encrypted storage before acknowledgment.

    Caller MUST verify the raw-body Meta HMAC signature before invoking this.
    Duplicate byte-identical deliveries do not create duplicate rows. This
    function deliberately never decrypts payloads or processes messages.
    """
    if not raw_body or len(raw_body) > MAX_INSTAGRAM_WEBHOOK_BODY_BYTES:
        raise ValueError("Invalid Instagram webhook size")

    validate_instagram_envelope(raw_body)

    # Fernet rejects malformed keys; never expose key material in exceptions.
    cipher = Fernet(encryption_key.encode("ascii"))
    ciphertext = cipher.encrypt(raw_body)
    digest = hashlib.sha256(raw_body).hexdigest()

    # PostgreSQL and SQLite both support ON CONFLICT ... DO NOTHING.
    # Uniqueness must also be guaranteed by the database itself.
    with database_engine.begin() as db:
        db.execute(
            text("""
                INSERT INTO public.sendro_channel_webhook_deliveries
                    (provider, raw_body_sha256, payload_ciphertext)
                VALUES ('instagram', :digest, :ciphertext)
                ON CONFLICT (provider, raw_body_sha256) DO NOTHING
            """),
            {"digest": digest, "ciphertext": ciphertext},
        )
