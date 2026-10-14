"""Transactional Instagram worker tests: in-memory DB, synthetic IG IDs, no Render."""
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./instagram_worker_test_unused.sqlite3")

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend.app.instagram_delivery_worker import process_one_pending_instagram_delivery
from backend.app.instagram_ingestion import persist_instagram_webhook


def dm(mid="m-1", sender="guest-123", business="business-1", text_body="Hello", media=None):
    message = {"mid": mid}
    if text_body is not None:
        message["text"] = text_body
    if media is not None:
        message["attachments"] = media
    return {
        "sender": {"id": sender},
        "recipient": {"id": business},
        "timestamp": 1792000000000,
        "message": message,
    }


def envelope(*items, business="business-1"):
    return {"object": "instagram", "entry": [{"id": business, "messaging": list(items)}]}


def store(engine, key, payload):
    persist_instagram_webhook(json.dumps(payload).encode("utf-8"), key, engine)


@pytest.fixture
def setup_worker():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as db:
        db.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        db.exec_driver_sql("""
            CREATE TABLE public.sendro_channel_accounts (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                external_account_id TEXT NOT NULL,
                status TEXT NOT NULL,
                UNIQUE(platform, external_account_id)
            )
        """)
        db.exec_driver_sql("""
            CREATE TABLE public.sendro_channel_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                channel_account_id INTEGER NOT NULL,
                external_customer_id TEXT NOT NULL,
                contact_name TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                unread_count INTEGER NOT NULL DEFAULT 0,
                last_message_at TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_account_id, external_customer_id)
            )
        """)
        db.exec_driver_sql("""
            CREATE TABLE public.sendro_channel_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                channel_account_id INTEGER NOT NULL,
                conversation_id INTEGER NOT NULL,
                provider_message_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                message_type TEXT NOT NULL,
                content TEXT,
                media_json TEXT,
                provider_timestamp TEXT,
                UNIQUE(channel_account_id, provider_message_id)
            )
        """)
        db.exec_driver_sql("""
            CREATE TABLE public.sendro_channel_webhook_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                raw_body_sha256 TEXT NOT NULL,
                payload_ciphertext BLOB NOT NULL,
                processing_state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error_code TEXT,
                received_at TEXT DEFAULT CURRENT_TIMESTAMP,
                next_attempt_at TEXT,
                processed_at TEXT,
                UNIQUE(provider, raw_body_sha256)
            )
        """)
        db.execute(text("""
            INSERT INTO public.sendro_channel_accounts
                (id, tenant_id, platform, external_account_id, status)
            VALUES
                (10, 1, 'instagram', 'business-1', 'testing'),
                (20, 2, 'instagram', 'business-2', 'active'),
                (30, 3, 'instagram', 'business-pending', 'pending')
        """))
    key = Fernet.generate_key().decode()
    yield engine, key
    engine.dispose()


def rows(engine, table, columns="*"):
    with engine.connect() as db:
        return db.execute(text(
            f"SELECT {columns} FROM public.{table} ORDER BY id"
        )).mappings().all()


def test_worker_idle_when_queue_empty(setup_worker):
    engine, key = setup_worker
    result = process_one_pending_instagram_delivery(engine, key)
    assert result.status == "idle"
    assert result.delivery_id is None


def test_incoming_multi_message_batch_increments_unread_once_per_new_mid(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("m-1"), dm("m-2", text_body="Second")))
    result = process_one_pending_instagram_delivery(engine, key)
    assert result.status == "processed"
    assert result.inserted_messages == 2
    assert len(rows(engine, "sendro_channel_conversations")) == 1
    assert rows(engine, "sendro_channel_conversations")[0]["unread_count"] == 2
    assert [m["content"] for m in rows(engine, "sendro_channel_messages")] == ["Hello", "Second"]
    assert rows(engine, "sendro_channel_webhook_deliveries")[0]["processing_state"] == "processed"


def test_provider_duplicate_in_distinct_envelope_does_not_increment_unread(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("m-1")))
    first = process_one_pending_instagram_delivery(engine, key)
    same_mid = envelope(dm("m-1"))
    same_mid["entry"][0]["time"] = 1792000000001
    store(engine, key, same_mid)
    second = process_one_pending_instagram_delivery(engine, key)
    assert first.inserted_messages == 1
    assert second.inserted_messages == 0
    assert rows(engine, "sendro_channel_conversations")[0]["unread_count"] == 1
    assert len(rows(engine, "sendro_channel_messages")) == 1


def test_echo_from_business_is_outbound_not_unread(setup_worker):
    engine, key = setup_worker
    echo = dm("m-outbound", "business-1", business="guest-123", text_body="Reply")
    echo["message"]["is_echo"] = True
    store(engine, key, envelope(echo))
    result = process_one_pending_instagram_delivery(engine, key)
    assert result.inserted_messages == 1
    assert rows(engine, "sendro_channel_messages")[0]["direction"] == "outbound"
    assert rows(engine, "sendro_channel_conversations")[0]["unread_count"] == 0


def test_same_customer_id_on_two_business_accounts_stays_tenant_isolated(setup_worker):
    engine, key = setup_worker
    store(engine, key, {
        "object": "instagram",
        "entry": [
            {"id": "business-1", "messaging": [dm("m-1")]},
            {"id": "business-2", "messaging": [dm("m-2", business="business-2")]},
        ],
    })
    result = process_one_pending_instagram_delivery(engine, key)
    assert result.inserted_messages == 2
    convs = rows(engine, "sendro_channel_conversations")
    assert [(r["tenant_id"], r["channel_account_id"], r["external_customer_id"])
            for r in convs] == [(1, 10, "guest-123"), (2, 20, "guest-123")]
    msgs = rows(engine, "sendro_channel_messages")
    assert [(m["tenant_id"], m["channel_account_id"]) for m in msgs] == [(1, 10), (2, 20)]


def test_unknown_business_quarantines_without_any_conversation_writes(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("m-1", business="business-unknown"), business="business-unknown"))
    result = process_one_pending_instagram_delivery(engine, key)
    assert result.status == "quarantined"
    assert rows(engine, "sendro_channel_messages") == []
    assert rows(engine, "sendro_channel_conversations") == []
    delivery = rows(engine, "sendro_channel_webhook_deliveries")[0]
    assert delivery["processing_state"] == "quarantined"
    assert delivery["last_error_code"] == "unregistered_business_account"
    assert delivery["attempts"] == 1
    assert b"Hello" not in delivery["payload_ciphertext"]


def test_pending_disabled_business_cannot_route(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("m-1", business="business-pending"), business="business-pending"))
    assert process_one_pending_instagram_delivery(engine, key).status == "quarantined"
    assert rows(engine, "sendro_channel_messages") == []


def test_mixed_known_and_unknown_accounts_quarantine_atomically(setup_worker):
    engine, key = setup_worker
    store(engine, key, {
        "object": "instagram",
        "entry": [
            {"id": "business-1", "messaging": [dm("m-1")]},
            {"id": "business-unknown", "messaging": [dm("m-2", business="business-unknown")]},
        ],
    })
    result = process_one_pending_instagram_delivery(engine, key)
    assert result.status == "quarantined"
    assert rows(engine, "sendro_channel_messages") == []
    assert rows(engine, "sendro_channel_conversations") == []


def test_unsupported_mixed_event_quarantines_batch_without_loss(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("m-1"), {"sender": {"id": "guest-123"}, "read": {"watermark": 3}}))
    assert process_one_pending_instagram_delivery(engine, key).status == "quarantined"
    assert rows(engine, "sendro_channel_messages") == []
    assert rows(engine, "sendro_channel_webhook_deliveries")[0]["last_error_code"] == "unsupported_or_invalid_event"


def test_media_message_preserves_metadata(setup_worker):
    engine, key = setup_worker
    media = [{"type": "image", "payload": {"url": "https://example.invalid/photo.jpg"}}]
    store(engine, key, envelope(dm("m-media", text_body=None, media=media)))
    result = process_one_pending_instagram_delivery(engine, key)
    assert result.inserted_messages == 1
    saved = rows(engine, "sendro_channel_messages")[0]
    assert saved["message_type"] == "media"
    assert json.loads(saved["media_json"]) == media


def test_invalid_decryption_key_does_not_consume_queue(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("m-1")))
    with pytest.raises(Exception):
        process_one_pending_instagram_delivery(engine, Fernet.generate_key().decode())
    assert rows(engine, "sendro_channel_webhook_deliveries")[0]["processing_state"] == "pending"


def test_database_error_rolls_back_conversation_and_delivery_status(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("m-1")))
    with engine.begin() as db:
        db.exec_driver_sql("DROP TABLE public.sendro_channel_messages")
    with pytest.raises(Exception):
        process_one_pending_instagram_delivery(engine, key)
    assert rows(engine, "sendro_channel_conversations") == []
    assert rows(engine, "sendro_channel_webhook_deliveries")[0]["processing_state"] == "pending"
