"""Phase 2J: Instagram Login DM webhook compatibility using sanitized, synthetic examples.

These are representative payloads based on documented messaging envelopes and
publicly observed event shapes, NOT captured/verified webhooks from our Meta app.
No database, HTTP, access tokens, credentials, WhatsApp or Meta subscriptions.
"""
from copy import deepcopy

import pytest

from backend.app.instagram_event_normalizer import (
    InvalidInstagramWebhook,
    UnsupportedInstagramEvent,
    normalize_instagram_messages,
)


# Realistically shaped but fabricated identifiers. Never use real customer IDs.
BUSINESS = "17841400000000001"
CUSTOMER = "340000000000001"
MID = "aWdfZAG1faXRlbToxOklHTWVzc2FnZA-test-only"


def entry(*items, business=BUSINESS):
    return {"id": business, "time": 1792000000222, "messaging": list(items)}


def envelope(*entries):
    return {"object": "instagram", "entry": list(entries)}


def inbound(*, message=None, extra=None, sender=CUSTOMER, recipient=BUSINESS):
    result = {
        "sender": {"id": sender},
        "recipient": {"id": recipient},
        "timestamp": 1792000000123,
        "message": {"mid": MID, "text": "Hello from a guest"} if message is None else message,
    }
    if extra:
        result.update(extra)
    return result


def test_instagram_business_login_text_dm_with_meta_shaped_ids():
    item = inbound()
    original = envelope(entry(item))
    snapshot = deepcopy(original)
    [dm] = normalize_instagram_messages(original)

    assert dm.business_account_id == BUSINESS
    assert dm.instagram_scoped_customer_id == CUSTOMER
    assert dm.message_id == MID
    assert dm.timestamp_ms == 1792000000123
    assert dm.direction == "inbound"
    assert dm.text == "Hello from a guest"
    assert dm.attachments == ()
    assert original == snapshot  # Side-effect free


def test_business_echo_requires_explicit_echo_marker():
    item = inbound(
        sender=BUSINESS,
        recipient=CUSTOMER,
        message={"mid": MID, "text": "Reply from business", "is_echo": True, "app_id": 1000},
    )
    [event] = normalize_instagram_messages(envelope(entry(item)))
    assert event.direction == "outbound"
    assert event.instagram_scoped_customer_id == CUSTOMER

    item["message"]["is_echo"] = False
    with pytest.raises(InvalidInstagramWebhook):
        normalize_instagram_messages(envelope(entry(item)))

    item["message"].pop("is_echo")
    with pytest.raises(InvalidInstagramWebhook):
        normalize_instagram_messages(envelope(entry(item)))


def test_business_like_sender_cannot_be_misread_as_customer_inbound():
    item = inbound(message={"mid": MID, "text": "Spoof", "is_echo": True})
    with pytest.raises(InvalidInstagramWebhook):
        normalize_instagram_messages(envelope(entry(item)))


@pytest.mark.parametrize("kind", ["image", "video", "audio", "share", "ig_post"])
def test_media_attachment_types_preserve_metadata_for_authorized_api_only(kind):
    attachment = {
        "type": kind,
        "payload": {
            "url": "https://cdn.example.invalid/synthetic-media",
            "ig_post_media_id": "18000000000000001",
        },
    }
    item = inbound(message={"mid": MID, "attachments": [attachment]})
    [result] = normalize_instagram_messages(envelope(entry(item)))
    assert result.direction == "inbound"
    assert result.text is None
    assert result.attachments == (attachment,)


def test_text_quick_reply_and_story_reply_do_not_become_separate_messages():
    # The current Inbox stores the text, not these extra presentation contexts.
    item = inbound(
        message={
            "mid": MID,
            "text": "Is your boat available?",
            "quick_reply": {"payload": "PRIVATE_CRUISE"},
        },
        extra={"reply_to": {"story": {"id": "18000000000000001"}}},
    )
    result = normalize_instagram_messages(envelope(entry(item)))
    assert len(result) == 1
    assert result[0].text == "Is your boat available?"


@pytest.mark.parametrize("other", [
    {"read": {"mid": MID, "watermark": 1792000000123}},
    {"reaction": {"mid": MID, "action": "react", "reaction": "love", "emoji": "❤️"}},
    {"message_edit": {"mid": MID, "text": "Updated", "num_edit": 1}},
    {"postback": {"mid": MID, "title": "Continue", "payload": "START"}},
    {"unsend": {"mid": MID}},
])
def test_non_message_events_alone_are_rejected_instead_of_acknowledged_as_dm(other):
    item = {
        "sender": {"id": CUSTOMER},
        "recipient": {"id": BUSINESS},
        "timestamp": 1792000000123,
        **other,
    }
    with pytest.raises(UnsupportedInstagramEvent):
        normalize_instagram_messages(envelope(entry(item)))


@pytest.mark.parametrize("additional", [
    {"reaction": {"mid": MID, "action": "react"}},
    {"read": {"mid": MID}},
    {"postback": {"payload": "START"}},
])
def test_mixed_event_keys_never_turn_into_a_plain_text_dm(additional):
    item = inbound(extra=additional)
    with pytest.raises(UnsupportedInstagramEvent):
        normalize_instagram_messages(envelope(entry(item)))


@pytest.mark.parametrize("message_update", [
    {"is_deleted": True},
    {"is_unsupported": True},
])
def test_removed_or_unsupported_message_with_text_is_quarantinable(message_update):
    item = inbound()
    item["message"].update(message_update)
    with pytest.raises(UnsupportedInstagramEvent):
        normalize_instagram_messages(envelope(entry(item)))


def test_unsubscribed_comment_style_changes_and_standby_do_not_route_as_dms():
    normal = entry(inbound())
    for other in [
        {**normal, "changes": [{"field": "comments", "value": {"text": "comment"}}]},
        {**normal, "standby": [inbound()]},
        {"id": BUSINESS, "changes": [{"field": "messages", "value": {}}]},
    ]:
        with pytest.raises(UnsupportedInstagramEvent):
            normalize_instagram_messages(envelope(other))


def test_mixed_valid_and_unsupported_batch_fails_entirely_before_routing():
    valid = entry(inbound())
    invalid = entry({"sender": {"id": CUSTOMER}, "read": {"mid": MID}})
    with pytest.raises(UnsupportedInstagramEvent):
        normalize_instagram_messages(envelope(valid, invalid))


def test_wrong_recipient_fails_closed_even_when_ids_look_like_instagram():
    with pytest.raises(InvalidInstagramWebhook):
        normalize_instagram_messages(
            envelope(entry(inbound(recipient="17841400000000002")))
        )
