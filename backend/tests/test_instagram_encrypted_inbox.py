"""Instagram webhook encrypted persistence; synthetic payloads and isolated DB."""
import hashlib
import hmac
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./instagram_inbox_test_unused.sqlite3")

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend.app import instagram_webhook
from backend.app.instagram_ingestion import (
    MAX_INSTAGRAM_WEBHOOK_BODY_BYTES,
    persist_instagram_webhook,
)


SAMPLE_PAYLOAD = (
    b'{"object":"instagram","entry":[{"id":"business-test","messaging":'
    b'[{"sender":{"id":"customer-test"},"recipient":{"id":"business-test"},'
    b'"message":{"mid":"ig-test-id","text":"Private guest message"}}]}]}'
)


@pytest.fixture
def inbox_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as db:
        db.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        db.exec_driver_sql("""
            CREATE TABLE public.sendro_channel_webhook_deliveries (
                id INTEGER PRIMARY KEY,
                provider VARCHAR(20) NOT NULL,
                raw_body_sha256 CHAR(64) NOT NULL,
                payload_ciphertext BLOB NOT NULL,
                processing_state VARCHAR(16) NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, raw_body_sha256)
            )
        """)
    try:
        yield engine
    finally:
        engine.dispose()


def signed_headers(raw_body: bytes, secret: str):
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": "sha256=" + digest}


def get_saved_items(engine):
    with engine.connect() as db:
        return db.execute(text("""
            SELECT provider, raw_body_sha256, payload_ciphertext,
                   processing_state, attempts
            FROM public.sendro_channel_webhook_deliveries ORDER BY id
        """)).mappings().all()


def test_storage_encrypts_before_commit_and_deduplicates_exact_body(inbox_engine):
    key = Fernet.generate_key().decode()
    persist_instagram_webhook(SAMPLE_PAYLOAD, key, inbox_engine)
    persist_instagram_webhook(SAMPLE_PAYLOAD, key, inbox_engine)

    rows = get_saved_items(inbox_engine)
    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "instagram"
    assert row["raw_body_sha256"] == hashlib.sha256(SAMPLE_PAYLOAD).hexdigest()
    assert row["processing_state"] == "pending"
    assert row["attempts"] == 0
    assert b"Private guest message" not in row["payload_ciphertext"]
    assert Fernet(key).decrypt(row["payload_ciphertext"]) == SAMPLE_PAYLOAD


def test_different_deliveries_are_stored_separately(inbox_engine):
    key = Fernet.generate_key().decode()
    persist_instagram_webhook(SAMPLE_PAYLOAD, key, inbox_engine)
    persist_instagram_webhook(SAMPLE_PAYLOAD.replace(b"ig-test-id", b"ig-test-id-2"), key, inbox_engine)
    assert len(get_saved_items(inbox_engine)) == 2


@pytest.mark.parametrize("payload", [
    b"",
    b'{"object":"instagram"}',
    b'{"object":"whatsapp_business_account","entry":[]}',
    b'{"object":"instagram","entry":{}}',
    b'not-json',
    b'{"object":"instagram","entry":[]}' + b' ' * MAX_INSTAGRAM_WEBHOOK_BODY_BYTES,
])
def test_invalid_payloads_never_write(inbox_engine, payload):
    with pytest.raises(ValueError):
        persist_instagram_webhook(payload, Fernet.generate_key().decode(), inbox_engine)
    assert get_saved_items(inbox_engine) == []


def test_bad_encryption_key_never_writes(inbox_engine):
    with pytest.raises(ValueError):
        persist_instagram_webhook(SAMPLE_PAYLOAD, "NOT-A-FERNET-KEY", inbox_engine)
    assert get_saved_items(inbox_engine) == []


def test_failed_insert_is_not_acknowledged_by_storage():
    broken_db = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    try:
        with pytest.raises(Exception):
            persist_instagram_webhook(SAMPLE_PAYLOAD, Fernet.generate_key().decode(), broken_db)
    finally:
        broken_db.dispose()


@pytest.fixture
def webhook_client(monkeypatch, inbox_engine):
    # Override the real engine to ensure the HTTP tests NEVER touch Render DB.
    from backend.app import database

    monkeypatch.setattr(database, "engine", inbox_engine)
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "test-only-ig-signing-secret")
    monkeypatch.delenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", raising=False)
    monkeypatch.delenv("INSTAGRAM_WEBHOOK_ENCRYPTION_KEY", raising=False)
    app = FastAPI()
    app.include_router(instagram_webhook.router)
    with TestClient(app) as client:
        yield client


def test_route_signed_event_flag_off_preserves_old_503(webhook_client, inbox_engine):
    response = webhook_client.post(
        "/webhook/instagram", content=SAMPLE_PAYLOAD,
        headers=signed_headers(SAMPLE_PAYLOAD, "test-only-ig-signing-secret"),
    )
    assert response.status_code == 503
    assert get_saved_items(inbox_engine) == []


def test_route_rejects_bad_signature_when_flag_enabled(webhook_client, inbox_engine, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "true")
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_ENCRYPTION_KEY", Fernet.generate_key().decode())
    response = webhook_client.post(
        "/webhook/instagram", content=SAMPLE_PAYLOAD,
        headers=signed_headers(SAMPLE_PAYLOAD, "wrong-signing-secret"),
    )
    assert response.status_code == 403
    assert get_saved_items(inbox_engine) == []


def test_route_requires_encryption_key_even_with_valid_signature(webhook_client, inbox_engine, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "true")
    response = webhook_client.post(
        "/webhook/instagram", content=SAMPLE_PAYLOAD,
        headers=signed_headers(SAMPLE_PAYLOAD, "test-only-ig-signing-secret"),
    )
    assert response.status_code == 503
    assert get_saved_items(inbox_engine) == []


def test_route_valid_event_is_durable_before_success(webhook_client, inbox_engine, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "true")
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_ENCRYPTION_KEY", key)
    headers = signed_headers(SAMPLE_PAYLOAD, "test-only-ig-signing-secret")
    first = webhook_client.post("/webhook/instagram", content=SAMPLE_PAYLOAD, headers=headers)
    second = webhook_client.post("/webhook/instagram", content=SAMPLE_PAYLOAD, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert len(get_saved_items(inbox_engine)) == 1
    assert Fernet(key).decrypt(get_saved_items(inbox_engine)[0]["payload_ciphertext"]) == SAMPLE_PAYLOAD


def test_route_missing_database_table_returns_503(webhook_client, inbox_engine, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "true")
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with inbox_engine.begin() as db:
        db.exec_driver_sql("DROP TABLE public.sendro_channel_webhook_deliveries")
    response = webhook_client.post(
        "/webhook/instagram", content=SAMPLE_PAYLOAD,
        headers=signed_headers(SAMPLE_PAYLOAD, "test-only-ig-signing-secret"),
    )
    assert response.status_code == 503


def test_route_refuses_oversized_body(webhook_client, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "true")
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_ENCRYPTION_KEY", Fernet.generate_key().decode())
    oversized = SAMPLE_PAYLOAD + b" " * MAX_INSTAGRAM_WEBHOOK_BODY_BYTES
    response = webhook_client.post(
        "/webhook/instagram", content=oversized,
        headers=signed_headers(oversized, "test-only-ig-signing-secret"),
    )
    assert response.status_code == 413
