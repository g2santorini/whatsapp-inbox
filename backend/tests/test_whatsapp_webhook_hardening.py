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
