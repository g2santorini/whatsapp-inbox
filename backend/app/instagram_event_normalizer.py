"""Strict, side-effect-free Instagram Messaging webhook normalization.

This module is intentionally independent of Sendro's WhatsApp ORM/tables.
It is NOT wired to acknowledge webhook POSTs: the Instagram endpoint still
returns 503 until durable, tenant-scoped persistence is built and reviewed.
"""
from dataclasses import dataclass
from typing import Any


class InvalidInstagramWebhook(ValueError):
    """Malformed Instagram notification or missing routing information."""


class UnsupportedInstagramEvent(ValueError):
    """Meta event kind that Sendro cannot safely persist yet."""


@dataclass(frozen=True)
class InstagramMessageEvent:
    """Single inbound DM or an echo of the business account's outbound DM."""

    business_account_id: str
    instagram_scoped_customer_id: str
    message_id: str
    direction: str
    text: str | None
    attachments: tuple[dict[str, Any], ...]
    timestamp_ms: int | None


def _required_id(source: Any, path: str) -> str:
    if isinstance(source, bool) or not isinstance(source, (str, int)):
        raise InvalidInstagramWebhook(f"Missing/invalid {path}")
    result = str(source).strip()
    if not result:
        raise InvalidInstagramWebhook(f"Missing/invalid {path}")
    return result


def normalize_instagram_messages(payload: Any) -> list[InstagramMessageEvent]:
    """Read every entry and messaging item, or fail instead of dropping events.

    Only Instagram DM message events (including business echoes) are supported
    for this first stage. A delivery receipt, reaction, edit, unsend, referral,
    comment or unsupported envelope must be explicitly handled in a later
    implementation before webhook POSTs can return HTTP 200.
    """
    if not isinstance(payload, dict) or payload.get("object") != "instagram":
        raise InvalidInstagramWebhook("Expected object=instagram")
    entries = payload.get("entry")
    if not isinstance(entries, list):
        raise InvalidInstagramWebhook("Expected entry array")

    normalized: list[InstagramMessageEvent] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise InvalidInstagramWebhook("Invalid entry object")
        business_id = _required_id(entry.get("id"), "entry.id")

        # Comment events are in changes[], not messaging[]; never mistake for DMs.
        if "changes" in entry or "standby" in entry:
            raise UnsupportedInstagramEvent("Non-messaging Instagram entry")

        notifications = entry.get("messaging")
        if not isinstance(notifications, list) or not notifications:
            raise UnsupportedInstagramEvent("Instagram entry has no messaging items")

        for item in notifications:
            if not isinstance(item, dict):
                raise InvalidInstagramWebhook("Invalid messaging item")
            message = item.get("message")
            if not isinstance(message, dict):
                raise UnsupportedInstagramEvent("Instagram event is not a DM message")

            # Do not silently convert other webhook kinds into new DMs when
            # Meta includes message-like fields alongside them.
            if (
                message.get("is_deleted")
                or message.get("is_unsupported") is True
                or any(key in item for key in (
                    "message_edit", "unsend", "reaction", "read", "postback",
                ))
            ):
                raise UnsupportedInstagramEvent("Unsupported Instagram message event")

            message_id = _required_id(message.get("mid"), "message.mid")
            sender = item.get("sender")
            recipient = item.get("recipient")
            if not isinstance(sender, dict) or not isinstance(recipient, dict):
                raise InvalidInstagramWebhook("Missing sender or recipient")
            sender_id = _required_id(sender.get("id"), "sender.id")
            recipient_id = _required_id(recipient.get("id"), "recipient.id")
            is_echo = message.get("is_echo") is True

            if sender_id == business_id and recipient_id != business_id and is_echo:
                # Only the explicitly flagged business echo can represent
                # outbound traffic. Never infer an outgoing message from IDs
                # alone if Meta sent an unexpected event variant.
                direction = "outbound"
                customer_id = recipient_id
            elif recipient_id == business_id and sender_id != business_id and not is_echo:
                direction = "inbound"
                customer_id = sender_id
            else:
                raise InvalidInstagramWebhook("DM routing IDs do not match business account")

            content = message.get("text")
            if content is not None and not isinstance(content, str):
                raise InvalidInstagramWebhook("Message text must be a string")

            raw_attachments = message.get("attachments", [])
            if not isinstance(raw_attachments, list) or not all(
                isinstance(x, dict) for x in raw_attachments
            ):
                raise InvalidInstagramWebhook("Invalid Instagram attachments")

            if not content and not raw_attachments:
                raise UnsupportedInstagramEvent("Empty DM or unsupported message kind")

            raw_timestamp = item.get("timestamp")
            if raw_timestamp is None:
                timestamp_ms = None
            elif isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, (int, str)):
                raise InvalidInstagramWebhook("Invalid message timestamp")
            else:
                try:
                    timestamp_ms = int(raw_timestamp)
                except ValueError as exc:
                    raise InvalidInstagramWebhook("Invalid message timestamp") from exc
                if timestamp_ms < 0:
                    raise InvalidInstagramWebhook("Invalid message timestamp")

            normalized.append(InstagramMessageEvent(
                business_account_id=business_id,
                instagram_scoped_customer_id=customer_id,
                message_id=message_id,
                direction=direction,
                text=content,
                attachments=tuple(raw_attachments),
                timestamp_ms=timestamp_ms,
            ))

    return normalized
