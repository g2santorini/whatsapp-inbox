"""Regression tests for safe staged WhatsApp webhook delivery handling."""
import hashlib
import hmac
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./sendro_webhook_test_unused.sqlite3")
os.environ.setdefault("SECRET_KEY", "test-only-secret-for-webhook")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test-meta-token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "0000")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models, project_models, task_models
from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.whatsapp_webhook_security import is_valid_meta_webhook_signature


def incoming_payload(whatsapp_id="wamid.unique-123", content="Welcome!"):
    return {
        "entry": [{"changes": [{"value": {
            "contacts": [{"profile": {"name": "Guest"}}],
            "messages": [{
                "id": whatsapp_id,
                "from": "306900001111",
                "type": "text",
                "text": {"body": content},
            }],
        }}]}],
    }


@pytest.fixture
def webhook_client(monkeypatch):
    monkeypatch.delenv("WHATSAPP_WEBHOOK_SIGNATURE_REQUIRED", raising=False)
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as db:
        db.add(models.User(
            username="webhook_test", email="webhook@test.example",
            hashed_password="hashed-for-tests", role="admin", disabled=False,
        ))
        db.commit()

    def testing_db():
        with factory() as session:
            yield session

    original = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = testing_db
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides = original
        engine.dispose()


def test_incoming_replay_does_not_duplicate_message_or_unread_count(webhook_client):
    client, factory = webhook_client
    body = incoming_payload()
    first = client.post("/webhook/whatsapp", json=body)
    assert first.status_code == 200, first.text
    duplicate = client.post("/webhook/whatsapp", json=body)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["duplicate"] is True
    with factory() as db:
        assert db.query(models.Message).count() == 1
        conversation = db.query(models.Conversation).one()
        assert conversation.unread_count == 1


def test_new_messages_with_different_ids_are_not_suppressed(webhook_client):
    client, factory = webhook_client
    assert client.post("/webhook/whatsapp", json=incoming_payload("wamid.first")).status_code == 200
    assert client.post("/webhook/whatsapp", json=incoming_payload("wamid.second")).status_code == 200
    with factory() as db:
        assert db.query(models.Message).count() == 2
        assert db.query(models.Conversation).one().unread_count == 2


def test_hmac_verification_checks_exact_bytes_and_invalid_signatures():
    body = b'{"entry": []}'
    secret = "not-a-real-meta-secret"
    valid = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert is_valid_meta_webhook_signature(body, f"sha256={valid}", secret)
    assert not is_valid_meta_webhook_signature(body + b" ", f"sha256={valid}", secret)
    assert not is_valid_meta_webhook_signature(body, None, secret)
    assert not is_valid_meta_webhook_signature(body, "sha256=invalid", secret)
    assert not is_valid_meta_webhook_signature(body, f"sha256={valid}", "other-secret")


def test_signature_is_enforced_only_when_explicitly_enabled(webhook_client, monkeypatch):
    client, factory = webhook_client
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SIGNATURE_REQUIRED", "true")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "test-meta-secret")
    payload = json.dumps(incoming_payload(), separators=(",", ":")).encode()
    signature = hmac.new(b"test-meta-secret", payload, hashlib.sha256).hexdigest()

    no_sig = client.post("/webhook/whatsapp", content=payload)
    bad_sig = client.post(
        "/webhook/whatsapp",
        content=payload,
        headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
    )
    assert no_sig.status_code == 403
    assert bad_sig.status_code == 403
    with factory() as db:
        assert db.query(models.Message).count() == 0

    ok = client.post(
        "/webhook/whatsapp",
        content=payload,
        headers={"X-Hub-Signature-256": f"sha256={signature}"},
    )
    assert ok.status_code == 200, ok.text
    with factory() as db:
        assert db.query(models.Message).count() == 1


def test_missing_secret_fails_closed_if_verification_enabled(webhook_client, monkeypatch):
    client, factory = webhook_client
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SIGNATURE_REQUIRED", "true")
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    reply = client.post("/webhook/whatsapp", json=incoming_payload())
    assert reply.status_code == 503
    with factory() as db:
        assert db.query(models.Message).count() == 0


def test_unsaved_webhook_is_not_acknowledged_as_success(webhook_client):
    client, factory = webhook_client
    # A missing 'entry' triggers an unexpected payload processing error;
    # it must never be silently acknowledged as successfully persisted.
    reply = client.post("/webhook/whatsapp", json={"entry": []})
    assert reply.status_code == 500
    with factory() as db:
        assert db.query(models.Message).count() == 0


# Full-format synthetic Meta payloads: the bridge is NOT connected to runtime.
# These tests prove the current single-company endpoint still accepts realistic
# signed envelopes while a separate pure preflight can determine future owners.
# The real legacy handler must not be used as a multi-tenant router.


def _full_meta_payload(message_id="wamid.synthetic-live-path", *, is_status=False,
                       is_reaction=False):
    value = {
        "metadata": {
            "display_phone_number": "000-test-number",
            "phone_number_id": "800000001",
        },
    }
    if is_status:
        value["statuses"] = [{
            "id": "wamid.nonexistent-outbound",
            "status": "delivered",
            "timestamp": "1792500000",
        }]
    else:
        value["contacts"] = [{"profile": {"name": "Fabricated Guest"}}]
        message = {
            "id": message_id,
            "from": "306900001111",  # synthetic, not a real guest record
        }
        if is_reaction:
            message["type"] = "reaction"
            message["reaction"] = {
                "message_id": "wamid.synthetic-live-path",
                "emoji": "👍",
            }
        else:
            message["type"] = "text"
            message["text"] = {"body": "Synthetic signed Meta test"}
        value["messages"] = [message]
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "700000001",
            "changes": [{"field": "messages", "value": value}],
        }],
    }


def _signed_meta_delivery(payload, *, secret):
    raw_body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    header = "sha256=" + digest
    return raw_body, header


def test_signed_full_meta_envelope_matches_standalone_account_preflight(
    webhook_client, monkeypatch,
):
    from backend.app.whatsapp_account_routing_preflight import (
        preflight_whatsapp_account_routes,
    )

    client, factory = webhook_client
    secret = "synthetic-meta-secret-for-contract-test"
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SIGNATURE_REQUIRED", "true")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", secret)
    payload = _full_meta_payload()
    raw, header = _signed_meta_delivery(payload, secret=secret)

    # In the future the signature MUST be verified on this same exact body.
    assert is_valid_meta_webhook_signature(raw, header, secret)
    preflight = preflight_whatsapp_account_routes(
        payload, {("700000001", "800000001"): 71},
        signature_verified=is_valid_meta_webhook_signature(raw, header, secret),
    )
    assert len(preflight) == 1
    assert (preflight[0].tenant_id, preflight[0].event_type) == (71, "message")
    assert preflight[0].phone_number_id == "800000001"

    # The active legacy handler remains unaffected, using only synthetic DB.
    accepted = client.post("/webhook/whatsapp", content=raw,
                           headers={"X-Hub-Signature-256": header})
    assert accepted.status_code == 200, accepted.text
    replay = client.post("/webhook/whatsapp", content=raw,
                         headers={"X-Hub-Signature-256": header})
    assert replay.status_code == 200 and replay.json().get("duplicate") is True
    with factory() as db:
        assert db.query(models.Conversation).count() == 1
        assert db.query(models.Message).count() == 1
        assert db.query(models.Conversation).one().unread_count == 1


def test_unsigned_modified_meta_envelope_never_persists_in_synthetic_handler(
    webhook_client, monkeypatch,
):
    from backend.app.whatsapp_account_routing_preflight import (
        WhatsAppRoutingPreflightError, preflight_whatsapp_account_routes,
    )

    client, factory = webhook_client
    secret = "synthetic-meta-secret-for-contract-test"
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SIGNATURE_REQUIRED", "true")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", secret)
    payload = _full_meta_payload()
    raw, header = _signed_meta_delivery(payload, secret=secret)
    tampered = raw.replace(b"800000001", b"800000002")
    assert not is_valid_meta_webhook_signature(tampered, header, secret)
    with pytest.raises(WhatsAppRoutingPreflightError):
        preflight_whatsapp_account_routes(
            json.loads(tampered),
            {("700000001", "800000002"): 72},
            signature_verified=is_valid_meta_webhook_signature(tampered, header, secret),
        )
    denied = client.post("/webhook/whatsapp", content=tampered,
                         headers={"X-Hub-Signature-256": header})
    assert denied.status_code == 403
    with factory() as db:
        assert db.query(models.Message).count() == 0


def test_signed_status_event_is_recognized_without_creating_inbound_message(
    webhook_client, monkeypatch,
):
    from backend.app.whatsapp_account_routing_preflight import (
        preflight_whatsapp_account_routes,
    )

    client, factory = webhook_client
    secret = "synthetic-meta-secret-for-status"
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SIGNATURE_REQUIRED", "true")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", secret)
    payload = _full_meta_payload(is_status=True)
    raw, header = _signed_meta_delivery(payload, secret=secret)
    route = preflight_whatsapp_account_routes(
        payload, {("700000001", "800000001"): 71},
        signature_verified=is_valid_meta_webhook_signature(raw, header, secret),
    )
    assert route[0].event_type == "status"
    result = client.post("/webhook/whatsapp", content=raw,
                         headers={"X-Hub-Signature-256": header})
    assert result.status_code == 200, result.text
    with factory() as db:
        assert db.query(models.Message).count() == 0
        assert db.query(models.Conversation).count() == 0


def test_signed_reaction_still_updates_original_synthetic_message_only(
    webhook_client, monkeypatch,
):
    from backend.app.whatsapp_account_routing_preflight import (
        preflight_whatsapp_account_routes,
    )

    client, factory = webhook_client
    secret = "synthetic-meta-secret-for-reaction"
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SIGNATURE_REQUIRED", "true")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", secret)
    registry = {("700000001", "800000001"): 71}

    def post(payload):
        raw, header = _signed_meta_delivery(payload, secret=secret)
        routes = preflight_whatsapp_account_routes(
            payload, registry,
            signature_verified=is_valid_meta_webhook_signature(raw, header, secret),
        )
        assert routes[0].tenant_id == 71
        return client.post("/webhook/whatsapp", content=raw,
                           headers={"X-Hub-Signature-256": header})

    assert post(_full_meta_payload()).status_code == 200
    assert post(_full_meta_payload(
        message_id="wamid.synthetic-reaction",
        is_reaction=True,
    )).status_code == 200
    with factory() as db:
        messages = db.query(models.Message).all()
        assert len(messages) == 1
        assert messages[0].reaction_emoji == "👍"
        assert db.query(models.Conversation).one().unread_count == 1
