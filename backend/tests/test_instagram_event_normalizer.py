"""Pure Instagram webhook parsing tests; no database or live API calls."""
import copy
import pytest

from backend.app.instagram_event_normalizer import (
    InvalidInstagramWebhook,
    UnsupportedInstagramEvent,
    normalize_instagram_messages,
)


def instagram_dm(mid="ig.mid.1", text="Hi", sender="IGSID-101", recipient="IGBUSINESS-1"):
    return {
        "sender": {"id": sender},
        "recipient": {"id": recipient},
        "timestamp": 1791900000123,
        "message": {"mid": mid, "text": text},
    }


def payload_with(*items):
    return {
        "object": "instagram",
        "entry": [{"id": "IGBUSINESS-1", "time": 1791900000200, "messaging": list(items)}],
    }


def test_multiple_entries_and_messages_are_all_preserved():
    obj = payload_with(instagram_dm(), instagram_dm("ig.mid.2", "Second", "IGSID-202"))
    obj["entry"].append({
        "id": "IGBUSINESS-2",
        "messaging": [instagram_dm("ig.mid.3", "Third", "IGSID-303", "IGBUSINESS-2")],
    })
    events = normalize_instagram_messages(obj)
    assert len(events) == 3
    assert [x.message_id for x in events] == ["ig.mid.1", "ig.mid.2", "ig.mid.3"]
    assert [(x.business_account_id, x.instagram_scoped_customer_id) for x in events] == [
        ("IGBUSINESS-1", "IGSID-101"),
        ("IGBUSINESS-1", "IGSID-202"),
        ("IGBUSINESS-2", "IGSID-303"),
    ]
    assert all(event.direction == "inbound" for event in events)
    assert events[0].timestamp_ms == 1791900000123


def test_business_echo_routes_to_customer_not_business_account():
    sent = instagram_dm("ig.mid.echo", "Hi from business", "IGBUSINESS-1", "IGSID-101")
    sent["message"]["is_echo"] = True
    [event] = normalize_instagram_messages(payload_with(sent))
    assert event.direction == "outbound"
    assert event.instagram_scoped_customer_id == "IGSID-101"


def test_media_is_preserved_without_coercing_to_fake_whatsapp_text():
    media = instagram_dm("ig.mid.media", text=None)
    media["message"]["attachments"] = [
        {"type": "image", "payload": {"url": "https://example.invalid/photo.jpg"}}
    ]
    [event] = normalize_instagram_messages(payload_with(media))
    assert event.text is None
    assert event.attachments[0]["type"] == "image"


@pytest.mark.parametrize("mutate", [
    lambda obj: obj.update({"object": "whatsapp_business_account"}),
    lambda obj: obj["entry"][0].update({"id": ""}),
    lambda obj: obj["entry"][0]["messaging"][0]["sender"].update({"id": None}),
    lambda obj: obj["entry"][0]["messaging"][0]["message"].update({"mid": None}),
    lambda obj: obj["entry"][0]["messaging"][0]["message"].update({"text": 88}),
    lambda obj: obj["entry"][0]["messaging"][0]["recipient"].update({"id": "WRONG-BUSINESS"}),
    lambda obj: obj["entry"][0]["messaging"][0].update({"timestamp": "not-a-timestamp"}),
    lambda obj: obj["entry"][0]["messaging"][0]["message"].update({"attachments": ["invalid"]}),
])
def test_invalid_payloads_fail_loudly(mutate):
    obj = payload_with(instagram_dm())
    mutate(obj)
    with pytest.raises(InvalidInstagramWebhook):
        normalize_instagram_messages(obj)


def test_one_unsupported_event_causes_whole_batch_to_fail():
    obj = payload_with(instagram_dm("ok"), {"sender": {"id": "IGSID-101"}, "read": {"watermark": 1}})
    with pytest.raises(UnsupportedInstagramEvent):
        normalize_instagram_messages(obj)


def test_comments_are_not_mistaken_for_dms():
    obj = payload_with(instagram_dm())
    obj["entry"][0]["changes"] = [{"field": "comments", "value": {}}]
    with pytest.raises(UnsupportedInstagramEvent):
        normalize_instagram_messages(obj)


def test_unsends_are_not_mistaken_for_new_dms():
    obj = payload_with(instagram_dm())
    obj["entry"][0]["messaging"][0]["message"]["is_deleted"] = True
    with pytest.raises(UnsupportedInstagramEvent):
        normalize_instagram_messages(obj)


def test_empty_notification_is_valid_but_cannot_be_acknowledged_as_a_message():
    assert normalize_instagram_messages({"object": "instagram", "entry": []}) == []


def test_pure_parser_does_not_mutate_meta_payload():
    obj = payload_with(instagram_dm())
    original = copy.deepcopy(obj)
    normalize_instagram_messages(obj)
    assert obj == original
