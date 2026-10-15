"""Synthetic Instagram DM: local signed webhook -> encrypted queue -> worker -> read API.

All payloads, IDs, tokens and keys are synthetic. Each test runs against an
isolated, in-memory SQLite database. No Meta traffic or Render database writes.
This exercises the real Instagram webhook, worker and tenant-scoped SQL paths;
the test authentication dependency is deliberately fake (JWT is covered elsewhere).
"""
import hashlib
import hmac
import json
import os
from types import SimpleNamespace

# Never require the production Render DATABASE_URL just to import the app code.
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import database, instagram_webhook
from backend.app.instagram_delivery_worker import process_one_pending_instagram_delivery
from backend.app.instagram_inbox_api import create_instagram_inbox_router


SIGNING_SECRET = "synthetic-signing-secret-not-a-real-credential"
SYNTHETIC_MESSAGE = "Hello from isolated Sendro DM test"
bearer = HTTPBearer()


def fake_authenticated_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
):
    # Only for this in-process integration test. Real auth has separate tests.
    identities = {"tenant-a-user": 101, "tenant-b-user": 202, "outsider": 303}
    user_id = identities.get(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid synthetic token")
    return SimpleNamespace(id=user_id)


def auth(who="tenant-a-user"):
    return {"Authorization": f"Bearer {who}"}


def synthetic_dm(mid="synthetic-mid-1", *, sender="guest-a", business="business-a",
                 message_text=SYNTHETIC_MESSAGE, attachments=None):
    msg = {"mid": mid}
    if message_text is not None:
        msg["text"] = message_text
    if attachments is not None:
        msg["attachments"] = attachments
    return {
        "object": "instagram",
        "entry": [{
            "id": business,
            "messaging": [{
                "sender": {"id": sender},
                "recipient": {"id": business},
                "timestamp": 1792000000000,
                "message": msg,
            }],
        }],
    }


def signed_request(payload):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(SIGNING_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, {"X-Hub-Signature-256": f"sha256={digest}"}


def count_rows(engine, table):
    # Table name is only a fixed literal passed by our tests, never request data.
    with engine.connect() as cx:
        return cx.execute(text(f"SELECT COUNT(*) FROM public.{table}")).scalar_one()


@pytest.fixture
def isolated_instagram(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as db:
        # PostgreSQL production uses public schema; emulate it in memory only.
        db.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        db.exec_driver_sql("""
            CREATE TABLE public.sendro_tenants (
                id INTEGER PRIMARY KEY,
                slug TEXT NOT NULL,
                display_name TEXT NOT NULL
            )
        """)
        db.exec_driver_sql("""
            CREATE TABLE public.sendro_tenant_users (
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                member_role TEXT NOT NULL
            )
        """)
        db.exec_driver_sql("""
            CREATE TABLE public.sendro_channel_accounts (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                external_account_id TEXT NOT NULL,
                display_name TEXT,
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
                assigned_to_user_id INTEGER,
                unread_count INTEGER NOT NULL DEFAULT 0,
                last_message_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
                delivery_status TEXT,
                is_read BOOLEAN NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
                received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                next_attempt_at TEXT,
                processed_at TEXT,
                UNIQUE(provider, raw_body_sha256)
            )
        """)
        db.exec_driver_sql("""
            INSERT INTO public.sendro_tenants (id, slug, display_name)
            VALUES (1, 'tenant-a', 'Synthetic Tenant A'),
                   (2, 'tenant-b', 'Synthetic Tenant B')
        """)
        db.exec_driver_sql("""
            INSERT INTO public.sendro_tenant_users (tenant_id, user_id, is_active, member_role)
            VALUES (1, 101, 1, 'operator'),
                   (2, 202, 1, 'viewer')
        """)
        db.exec_driver_sql("""
            INSERT INTO public.sendro_channel_accounts
                (id, tenant_id, platform, external_account_id, display_name, status)
            VALUES (10, 1, 'instagram', 'business-a', '@synthetic_a', 'testing'),
                   (20, 2, 'instagram', 'business-b', '@synthetic_b', 'active')
        """)

    key = Fernet.generate_key().decode("ascii")
    # These temporary flags only exist in the pytest process. They do not
    # update Render's environment, deploy a worker, or subscribe Meta.
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_ENCRYPTION_KEY", key)
    monkeypatch.delenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", raising=False)
    monkeypatch.delenv("INSTAGRAM_WORKER_MANUAL_ENABLED", raising=False)
    monkeypatch.setattr(database, "engine", engine)

    factory = sessionmaker(bind=engine)

    def isolated_db():
        with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(instagram_webhook.router)
    app.include_router(create_instagram_inbox_router(fake_authenticated_user))
    app.dependency_overrides[database.get_db] = isolated_db

    try:
        with TestClient(app) as client:
            yield client, engine, key, monkeypatch
    finally:
        engine.dispose()


def test_dm_from_signed_http_to_read_only_inbox(isolated_instagram):
    client, engine, key, monkeypatch = isolated_instagram
    body, headers = signed_request(synthetic_dm())

    # By default even a valid signed request must NOT be accepted or stored.
    disabled = client.post("/webhook/instagram", content=body, headers=headers)
    assert disabled.status_code == 503
    assert count_rows(engine, "sendro_channel_webhook_deliveries") == 0

    # Opt in solely inside this isolated pytest process, never in Render.
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "true")
    stored = client.post("/webhook/instagram", content=body, headers=headers)
    assert stored.status_code == 200, stored.text
    assert stored.json()["status"] == "stored"
    assert count_rows(engine, "sendro_channel_messages") == 0

    with engine.connect() as db:
        queued = db.execute(text("""
            SELECT payload_ciphertext, processing_state
            FROM public.sendro_channel_webhook_deliveries
        """)).mappings().one()
    assert queued["processing_state"] == "pending"
    assert SYNTHETIC_MESSAGE.encode() not in queued["payload_ciphertext"]
    assert Fernet(key).decrypt(queued["payload_ciphertext"]) == body

    processed = process_one_pending_instagram_delivery(engine, key)
    assert processed.status == "processed"
    assert processed.inserted_messages == 1
    assert count_rows(engine, "sendro_channel_messages") == 1

    tenant_list = client.get("/channels/instagram/tenants", headers=auth())
    assert tenant_list.status_code == 200, tenant_list.text
    assert [item["id"] for item in tenant_list.json()] == [1]

    conversations = client.get(
        "/channels/instagram/conversations?tenant_id=1", headers=auth()
    )
    assert conversations.status_code == 200, conversations.text
    assert len(conversations.json()) == 1
    conversation = conversations.json()[0]
    assert conversation["tenant_id"] == 1
    assert conversation["channel_account_id"] == 10
    assert conversation["external_customer_id"] == "guest-a"
    assert conversation["unread_count"] == 1

    messages = client.get(
        f'/channels/instagram/conversations/{conversation["id"]}/messages?tenant_id=1',
        headers=auth(),
    )
    assert messages.status_code == 200, messages.text
    assert len(messages.json()) == 1
    assert messages.json()[0]["content"] == SYNTHETIC_MESSAGE
    assert messages.json()[0]["direction"] == "inbound"
    assert messages.json()[0]["has_media"] is False
    assert "payload_ciphertext" not in str(messages.json())
    assert "provider_message_id" not in messages.json()[0]

    # Unrelated users and other tenant memberships cannot read this DM.
    assert client.get(
        "/channels/instagram/conversations?tenant_id=1", headers=auth("outsider")
    ).status_code == 403
    assert client.get(
        "/channels/instagram/conversations?tenant_id=1", headers=auth("tenant-b-user")
    ).status_code == 403
    assert client.get(
        f'/channels/instagram/conversations/{conversation["id"]}/messages?tenant_id=2',
        headers=auth("tenant-b-user"),
    ).status_code == 404


def test_replayed_signed_delivery_is_idempotent(isolated_instagram):
    client, engine, key, monkeypatch = isolated_instagram
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "true")
    body, headers = signed_request(synthetic_dm())
    assert client.post("/webhook/instagram", content=body, headers=headers).status_code == 200
    assert client.post("/webhook/instagram", content=body, headers=headers).status_code == 200
    assert count_rows(engine, "sendro_channel_webhook_deliveries") == 1
    assert process_one_pending_instagram_delivery(engine, key).inserted_messages == 1

    # A different signed envelope containing the same provider message ID
    # may queue again, but must never duplicate a guest DM or unread count.
    changed_payload = synthetic_dm()
    changed_payload["entry"][0]["time"] = 1792000000001
    changed_body, changed_headers = signed_request(changed_payload)
    assert client.post(
        "/webhook/instagram", content=changed_body, headers=changed_headers
    ).status_code == 200
    repeated = process_one_pending_instagram_delivery(engine, key)
    assert repeated.status == "processed"
    assert repeated.inserted_messages == 0
    assert count_rows(engine, "sendro_channel_messages") == 1
    assert count_rows(engine, "sendro_channel_conversations") == 1
    with engine.connect() as db:
        unread = db.execute(text("""
            SELECT unread_count FROM public.sendro_channel_conversations
        """)).scalar_one()
    assert unread == 1


def test_invalid_signature_never_creates_an_encrypted_delivery(isolated_instagram):
    client, engine, _, monkeypatch = isolated_instagram
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "true")
    body, _ = signed_request(synthetic_dm())
    invalid = client.post(
        "/webhook/instagram",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
    )
    assert invalid.status_code == 403
    assert count_rows(engine, "sendro_channel_webhook_deliveries") == 0


def test_signed_media_dm_redacts_url_in_read_api(isolated_instagram):
    client, engine, key, monkeypatch = isolated_instagram
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "true")
    media_url = "https://media.example.invalid/synthetic-image.jpg"
    payload = synthetic_dm(
        mid="synthetic-media-mid",
        message_text=None,
        attachments=[{"type": "image", "payload": {"url": media_url}}],
    )
    body, headers = signed_request(payload)
    assert client.post("/webhook/instagram", content=body, headers=headers).status_code == 200
    assert process_one_pending_instagram_delivery(engine, key).inserted_messages == 1
    conv = client.get(
        "/channels/instagram/conversations?tenant_id=1", headers=auth()
    ).json()[0]
    response = client.get(
        f'/channels/instagram/conversations/{conv["id"]}/messages?tenant_id=1',
        headers=auth(),
    )
    assert response.status_code == 200, response.text
    assert response.json()[0]["has_media"] is True
    assert response.json()[0]["content"] is None
    assert media_url not in response.text
