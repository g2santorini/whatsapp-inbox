"""Pure synthetic tests for INERT future WhatsApp account routing preflight.

No Render, Meta, database engine, real customer contacts, or real account IDs.
"""
import copy
import pytest

from backend.app.whatsapp_account_routing_preflight import (
    AccountRoute,
    WhatsAppRoutingPreflightError,
    preflight_whatsapp_account_routes,
)


A_WABA = "700000001"
A_PHONE = "800000001"
B_WABA = "700000002"
B_PHONE = "800000002"
ACCOUNTS = {
    (A_WABA, A_PHONE): 71,
    (B_WABA, B_PHONE): 72,
}


def envelope(*, waba=A_WABA, number=A_PHONE, statuses=False):
    value = {
        "metadata": {
            "phone_number_id": number,
            "display_phone_number": "+30 TEST ONLY DO NOT DIAL",
        },
    }
    if statuses:
        value["statuses"] = [{"id": "fabricated-status", "status": "delivered"}]
    else:
        value["contacts"] = [{"profile": {"name": "synthetic private name"}}]
        value["messages"] = [{
            "id": "synthetic-message",
            "from": "synthetic customer phone",
            "type": "text", "text": {"body": "Private fake contents"},
        }]
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": waba,
            "changes": [{"field": "messages", "value": value}],
        }],
    }


def route(payload, *, accounts=ACCOUNTS, signed=True):
    return preflight_whatsapp_account_routes(
        payload, accounts, signature_verified=signed,
    )


def test_requires_explicit_signature_verification_before_routing():
    for verified in (False, None, 1, "true"):
        with pytest.raises(WhatsAppRoutingPreflightError, match="Signed"):
            route(envelope(), signed=verified)


def test_routes_correct_destination_not_customer_phone():
    output = route(envelope())
    assert output == (
        AccountRoute(0, 0, "message", 71, A_WABA, A_PHONE),
    )
    serialized = repr(output)
    assert "synthetic private name" not in serialized
    assert "synthetic customer phone" not in serialized
    assert "Private fake contents" not in serialized
    assert "DO NOT DIAL" not in serialized
    assert "whatsapp" not in output[0].event_type


def test_same_guest_cannot_cross_tenants_when_destination_differs():
    a = envelope()
    b = envelope(waba=B_WABA, number=B_PHONE)
    assert a["entry"][0]["changes"][0]["value"]["messages"] == (
        b["entry"][0]["changes"][0]["value"]["messages"]
    )
    assert route(a)[0].tenant_id == 71
    assert route(b)[0].tenant_id == 72


def test_status_event_also_requires_exact_business_account_pair():
    result = route(envelope(waba=B_WABA, number=B_PHONE, statuses=True))
    assert result[0].tenant_id == 72
    assert result[0].event_type == "status"


@pytest.mark.parametrize("waba,number", [
    (A_WABA, B_PHONE),
    (B_WABA, A_PHONE),
    ("700000003", A_PHONE),
    (A_WABA, "800000003"),
    (None, A_PHONE),
    (A_WABA, None),
])
def test_unknown_cross_account_and_missing_ids_fail_closed(waba, number):
    with pytest.raises(WhatsAppRoutingPreflightError):
        route(envelope(waba=waba, number=number))


@pytest.mark.parametrize("invalid", [
    {},
    {"object": "instagram", "entry": []},
    {"object": "whatsapp_business_account", "entry": []},
    {"object": "whatsapp_business_account", "entry": [{}]},
    {"object": "whatsapp_business_account", "entry": "not-a-list"},
])
def test_malformed_envelope_fails_closed(invalid):
    with pytest.raises(WhatsAppRoutingPreflightError):
        route(invalid)


def test_missing_metadata_or_ambiguous_message_status_fails_closed():
    source = envelope()
    change = source["entry"][0]["changes"][0]
    for mutation in (
        lambda p: p["entry"][0]["changes"][0]["value"].pop("metadata"),
        lambda p: p["entry"][0]["changes"][0]["value"].update({"statuses": [{}]}),
        lambda p: p["entry"][0]["changes"][0]["value"].pop("messages"),
        lambda p: p["entry"][0]["changes"][0].update({"field": "other"}),
    ):
        payload = copy.deepcopy(source)
        mutation(payload)
        with pytest.raises(WhatsAppRoutingPreflightError):
            route(payload)


def test_multiple_entries_changes_all_decided_or_none_are_returned():
    payload = envelope()
    payload["entry"].append(envelope(waba=B_WABA, number=B_PHONE)["entry"][0])
    result = route(payload)
    assert [(r.tenant_id, r.entry_index) for r in result] == [(71, 0), (72, 1)]
    payload["entry"][1]["changes"][0]["value"]["metadata"]["phone_number_id"] = A_PHONE
    with pytest.raises(WhatsAppRoutingPreflightError):
        route(payload)


def test_empty_or_invalid_server_side_account_registry_rejected():
    for registry in ({}, {(A_WABA, A_PHONE): None}, {(A_WABA, A_PHONE): True}):
        with pytest.raises(WhatsAppRoutingPreflightError):
            route(envelope(), accounts=registry)


def test_input_boundaries_do_not_partial_process_large_envelopes():
    payload = envelope()
    payload["entry"] = payload["entry"] * 33
    with pytest.raises(WhatsAppRoutingPreflightError):
        route(payload)
    payload = envelope()
    payload["entry"][0]["changes"] *= 129
    with pytest.raises(WhatsAppRoutingPreflightError):
        route(payload)


def test_helper_is_inert_and_not_hooked_into_live_application():
    from pathlib import Path
    helper = (Path(__file__).parents[1] / "app" /
              "whatsapp_account_routing_preflight.py").read_text()
    main = (Path(__file__).parents[1] / "app" / "main.py").read_text()
    assert "whatsapp_account_routing_preflight" not in main
    for forbidden in (
        "DATABASE_URL", "create_engine", "SessionLocal", "db.commit",
        "db.add(", "INSERT INTO", "DELETE FROM", "UPDATE public",
        "httpx.", "requests.", "os.environ", "@app.post",
    ):
        assert forbidden not in helper
