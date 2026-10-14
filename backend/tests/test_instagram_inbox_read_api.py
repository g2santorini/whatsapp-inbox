"""Tenant isolation tests for the read-only Instagram Inbox API.

Synthetic in-memory SQLite only; no connection to the shared Render database.
"""
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import get_db
from backend.app.instagram_inbox_api import create_instagram_inbox_router


bearer = HTTPBearer()


def fake_authenticated_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
):
    users = {"user-a": 1, "user-b": 2, "outsider": 3, "inactive-member": 4}
    user_id = users.get(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid test token")
    return SimpleNamespace(id=user_id)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as db:
        db.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
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
                display_name TEXT,
                status TEXT NOT NULL
            )
        """)
        db.exec_driver_sql("""
            CREATE TABLE public.sendro_channel_conversations (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                channel_account_id INTEGER NOT NULL,
                external_customer_id TEXT NOT NULL,
                contact_name TEXT,
                status TEXT NOT NULL,
                assigned_to_user_id INTEGER,
                unread_count INTEGER NOT NULL,
                last_message_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.exec_driver_sql("""
            CREATE TABLE public.sendro_channel_messages (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                channel_account_id INTEGER NOT NULL,
                conversation_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                message_type TEXT NOT NULL,
                content TEXT,
                media_json TEXT,
                provider_timestamp TEXT,
                delivery_status TEXT,
                is_read BOOLEAN NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.exec_driver_sql("""
            INSERT INTO public.sendro_tenant_users VALUES
                (1, 1, 1, 'operator'),
                (2, 2, 1, 'viewer'),
                (1, 4, 0, 'admin')
        """)
        db.exec_driver_sql("""
            INSERT INTO public.sendro_channel_accounts VALUES
                (10, 1, 'instagram', '@business-a', 'testing'),
                (20, 2, 'instagram', '@business-b', 'active'),
                (30, 1, 'whatsapp', 'Business WA', 'active'),
                (40, 1, 'instagram', '@disabled', 'disabled')
        """)
        db.exec_driver_sql("""
            INSERT INTO public.sendro_channel_conversations VALUES
                (100, 1, 10, 'guest-a', 'Guest A', 'open', NULL, 1,
                 '2026-10-14 12:00:00', '2026-10-14 11:00:00', '2026-10-14 12:00:00'),
                (200, 2, 20, 'guest-b', 'Guest B', 'open', NULL, 0,
                 '2026-10-14 11:00:00', '2026-10-14 10:00:00', '2026-10-14 11:00:00'),
                (300, 1, 30, 'wa-guest', 'WhatsApp', 'open', NULL, 1,
                 '2026-10-14 10:00:00', '2026-10-14 09:00:00', '2026-10-14 10:00:00'),
                (400, 1, 40, 'hidden-guest', 'Hidden', 'open', NULL, 0,
                 '2026-10-14 10:00:00', '2026-10-14 09:00:00', '2026-10-14 10:00:00')
        """)
        db.exec_driver_sql("""
            INSERT INTO public.sendro_channel_messages VALUES
                (1001, 1, 10, 100, 'inbound', 'text', 'IG guest private message', NULL,
                 '2026-10-14 12:00:00', NULL, 0, '2026-10-14 12:00:00'),
                (1002, 1, 10, 100, 'inbound', 'media', NULL, '{"type":"image"}',
                 '2026-10-14 12:05:00', NULL, 0, '2026-10-14 12:05:00'),
                (2001, 2, 20, 200, 'inbound', 'text', 'Other tenant secret', NULL,
                 '2026-10-14 11:00:00', NULL, 0, '2026-10-14 11:00:00'),
                (3001, 1, 30, 300, 'inbound', 'text', 'WhatsApp text', NULL,
                 '2026-10-14 10:00:00', NULL, 0, '2026-10-14 10:00:00'),
                (4001, 1, 40, 400, 'inbound', 'text', 'Disabled IG account', NULL,
                 '2026-10-14 10:00:00', NULL, 0, '2026-10-14 10:00:00')
        """)

    factory = sessionmaker(bind=engine)

    def override_db():
        with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(create_instagram_inbox_router(fake_authenticated_user))
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def auth(name="user-a"):
    return {"Authorization": "Bearer " + name}


def test_list_only_returns_current_tenant_instagram_conversations(client):
    result = client.get("/channels/instagram/conversations?tenant_id=1", headers=auth())
    assert result.status_code == 200, result.text
    assert [item["id"] for item in result.json()] == [100]
    assert result.json()[0]["account_name"] == "@business-a"
    assert result.json()[0]["external_customer_id"] == "guest-a"


def test_member_other_tenant_only_sees_own_instagram_threads(client):
    result = client.get("/channels/instagram/conversations?tenant_id=2", headers=auth("user-b"))
    assert result.status_code == 200
    assert [item["id"] for item in result.json()] == [200]
    assert client.get("/channels/instagram/conversations?tenant_id=1", headers=auth("user-b")).status_code == 403


def test_missing_or_inactive_tenant_membership_fails_closed(client):
    assert client.get("/channels/instagram/conversations?tenant_id=1", headers=auth("outsider")).status_code == 403
    assert client.get("/channels/instagram/conversations?tenant_id=1", headers=auth("inactive-member")).status_code == 403
    assert client.get("/channels/instagram/conversations?tenant_id=1").status_code in (401, 403)


def test_tenant_id_is_required_and_validated(client):
    assert client.get("/channels/instagram/conversations", headers=auth()).status_code == 422
    assert client.get("/channels/instagram/conversations?tenant_id=0", headers=auth()).status_code == 422


def test_message_read_is_scoped_and_hides_media_payload(client):
    result = client.get("/channels/instagram/conversations/100/messages?tenant_id=1", headers=auth())
    assert result.status_code == 200, result.text
    items = result.json()
    assert [m["id"] for m in items] == [1002, 1001]
    assert items[0]["has_media"] is True
    assert "media_json" not in items[0]
    assert items[1]["content"] == "IG guest private message"
    assert "provider_message_id" not in items[1]


def test_other_tenant_message_read_is_denied_or_not_found(client):
    assert client.get("/channels/instagram/conversations/200/messages?tenant_id=1", headers=auth()).status_code == 404
    assert client.get("/channels/instagram/conversations/200/messages?tenant_id=2", headers=auth()).status_code == 403
    assert client.get("/channels/instagram/conversations/300/messages?tenant_id=1", headers=auth()).status_code == 404
    assert client.get("/channels/instagram/conversations/400/messages?tenant_id=1", headers=auth()).status_code == 404
    assert client.get("/channels/instagram/conversations/100/messages?tenant_id=1", headers=auth("outsider")).status_code == 403


def test_message_history_pagination_and_query_limits(client):
    result = client.get("/channels/instagram/conversations/100/messages?tenant_id=1&before_id=1002", headers=auth())
    assert result.status_code == 200
    assert [m["id"] for m in result.json()] == [1001]
    assert client.get("/channels/instagram/conversations/100/messages?tenant_id=1&limit=101", headers=auth()).status_code == 422
    assert client.get("/channels/instagram/conversations?tenant_id=1&limit=101", headers=auth()).status_code == 422
