"""Phase 2P: signed HTTP webhook -> PostgreSQL inbox -> gated manual worker -> API.

SYNTHETIC only. No Meta/network calls, no Render DB, no real customers.
Only the strictly guarded, disposable GitHub Actions PostgreSQL service may
execute these tests; the fixture replays the six real SQL migration snapshots.
"""
import hashlib
import hmac
import json
import os
from types import SimpleNamespace

# Never import a real Render/production DATABASE_URL in this test harness.
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app import database, instagram_webhook
from backend.app.instagram_inbox_api import create_instagram_inbox_router
from backend.app.instagram_worker_control import (
    CONFIRM_PHRASE,
    execute_control,
)
from backend.tests.test_instagram_manual_migrations_postgres import replay_engine


SIGNING_SECRET = "phase2p-fabricated-secret-used-only-in-ephemeral-ci"
ENROLLED_BUSINESS = "ig-phase2p-business-a"
SECOND_BUSINESS = "ig-phase2p-business-b"
INBOUND_TEXT = "Synthetic Phase 2P inbound Instagram test"


def synthetic_dm(mid="p2p-mid-1", *, business=ENROLLED_BUSINESS,
                 sender="p2p-synthetic-guest", content=INBOUND_TEXT):
    return {
        "object": "instagram",
        "entry": [{
            "id": business,
            "time": 1792000000100,
            "messaging": [{
                "sender": {"id": sender},
                "recipient": {"id": business},
                "timestamp": 1792000000123,
                "message": {"mid": mid, "text": content},
            }],
        }],
    }


def signed_payload(envelope):
    body = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(SIGNING_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Hub-Signature-256": "sha256=" + signature}


bearer = HTTPBearer()


def synthetic_authenticated_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
):
    user_id = {
        "tenant-a": 101, "tenant-b": 202, "outsider": 303,
    }.get(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid synthetic test identity")
    return SimpleNamespace(id=user_id)


def auth(identity):
    return {"Authorization": "Bearer " + identity}


def count(engine, name):
    # This interpolation is limited to constants below, never user input.
    assert name in (
        "sendro_channel_webhook_deliveries",
        "sendro_channel_messages",
        "sendro_channel_conversations",
    )
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM public.{name}")).scalar_one()


@pytest.fixture
def ci_http(monkeypatch, replay_engine):
    # replay_engine enforces GITHUB_ACTIONS + exact local URL/user/port and
    # only connects to disposable sendro_ig_ci. Never call this on Render.
    engine = replay_engine
    with engine.begin() as conn:
        conn.execute(text("""
            TRUNCATE TABLE public.sendro_channel_webhook_deliveries,
                           public.sendro_channel_messages,
                           public.sendro_channel_conversations,
                           public.sendro_channel_accounts,
                           public.sendro_tenant_users,
                           public.sendro_tenants,
                           public.users
            RESTART IDENTITY CASCADE
        """))
        conn.execute(text("INSERT INTO public.users (id) VALUES (101), (202)"))
        conn.execute(text("""
            INSERT INTO public.sendro_tenants(id, slug, display_name)
            VALUES (1, 'phase2p-a', 'CI Tenant A'),
                   (2, 'phase2p-b', 'CI Tenant B')
        """))
        conn.execute(text("""
            INSERT INTO public.sendro_tenant_users
                (tenant_id, user_id, member_role)
            VALUES (1, 101, 'operator'), (2, 202, 'viewer')
        """))
        conn.execute(text("""
            INSERT INTO public.sendro_channel_accounts
                (tenant_id, platform, external_account_id, status, display_name)
            VALUES (1, 'instagram', :business_a, 'testing', '@ci_account_a'),
                   (2, 'instagram', :business_b, 'testing', '@ci_account_b')
        """), {"business_a": ENROLLED_BUSINESS, "business_b": SECOND_BUSINESS})

    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_ENCRYPTION_KEY", key)
    # Production flags are never changed. Local test environment starts OFF.
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "false")
    monkeypatch.setenv("INSTAGRAM_WORKER_MANUAL_ENABLED", "false")

    db_factory = sessionmaker(bind=engine)

    def get_isolated_db():
        with db_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(instagram_webhook.router)
    app.include_router(create_instagram_inbox_router(synthetic_authenticated_user))
    app.dependency_overrides[database.get_db] = get_isolated_db

    with TestClient(app) as client:
        yield client, engine, key, monkeypatch


def allow_ci_ingestion(ci_http):
    client, engine, key, monkeypatch = ci_http
    assert engine.url.database == "sendro_ig_ci"
    assert engine.url.port == 55439
    # This is in-memory pytest environment ONLY, never Render.
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "true")


def manual_once(ci_http):
    _, engine, key, _ = ci_http
    return execute_control(
        engine, run_one=True, confirmation=CONFIRM_PHRASE,
        environ={
            "INSTAGRAM_WORKER_MANUAL_ENABLED": "true",
            "INSTAGRAM_WEBHOOK_ENCRYPTION_KEY": key,
        },
    )


def test_off_flag_refuses_signed_http_and_bad_signature_never_writes(ci_http):
    client, engine, _, monkeypatch = ci_http
    body, headers = signed_payload(synthetic_dm())
    assert client.post("/webhook/instagram", content=body, headers=headers).status_code == 503
    assert count(engine, "sendro_channel_webhook_deliveries") == 0

    allow_ci_ingestion(ci_http)
    assert client.post("/webhook/instagram", content=body,
                       headers={"X-Hub-Signature-256": "sha256=" + "0" * 64}).status_code == 403
    assert client.post("/webhook/instagram", content=body).status_code == 403
    assert count(engine, "sendro_channel_webhook_deliveries") == 0
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "false")


def test_signed_ingress_to_manual_worker_to_tenant_inbox_on_real_postgres(ci_http):
    client, engine, key, monkeypatch = ci_http
    body, headers = signed_payload(synthetic_dm())
    allow_ci_ingestion(ci_http)

    accepted = client.post("/webhook/instagram", content=body, headers=headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"status": "stored"}
    assert count(engine, "sendro_channel_webhook_deliveries") == 1
    assert count(engine, "sendro_channel_conversations") == 0
    assert count(engine, "sendro_channel_messages") == 0

    with engine.connect() as conn:
        stored = conn.execute(text("""
            SELECT processing_state, payload_ciphertext FROM
            public.sendro_channel_webhook_deliveries
        """)).mappings().one()
    assert stored["processing_state"] == "pending"
    assert INBOUND_TEXT.encode() not in stored["payload_ciphertext"]
    assert Fernet(key.encode()).decrypt(stored["payload_ciphertext"]) == body

    # Fail-closed production-like gate refuses manual run without flag.
    with pytest.raises(PermissionError, match="disabled"):
        execute_control(engine, run_one=True, confirmation=CONFIRM_PHRASE,
                        environ={"INSTAGRAM_WEBHOOK_ENCRYPTION_KEY": key})

    processed = manual_once(ci_http)
    assert processed["status"] == "processed"
    assert processed["inserted_messages"] == 1
    assert count(engine, "sendro_channel_messages") == 1
    assert count(engine, "sendro_channel_conversations") == 1

    tenants = client.get("/channels/instagram/tenants", headers=auth("tenant-a"))
    assert tenants.status_code == 200
    assert [row["id"] for row in tenants.json()] == [1]
    inbox = client.get("/channels/instagram/conversations?tenant_id=1",
                       headers=auth("tenant-a"))
    assert inbox.status_code == 200, inbox.text
    assert len(inbox.json()) == 1
    conversation = inbox.json()[0]
    assert conversation["unread_count"] == 1
    assert conversation["external_customer_id"] == "p2p-synthetic-guest"
    assert conversation["tenant_id"] == 1

    messages = client.get(
        f'/channels/instagram/conversations/{conversation["id"]}/messages?tenant_id=1',
        headers=auth("tenant-a"),
    )
    assert messages.status_code == 200, messages.text
    assert len(messages.json()) == 1
    assert messages.json()[0]["content"] == INBOUND_TEXT
    assert messages.json()[0]["direction"] == "inbound"
    assert "payload_ciphertext" not in str(messages.json())
    assert "provider_message_id" not in messages.json()[0]

    assert client.get("/channels/instagram/conversations?tenant_id=1",
                      headers=auth("tenant-b")).status_code == 403
    assert client.get("/channels/instagram/conversations?tenant_id=1",
                      headers=auth("outsider")).status_code == 403
    assert client.get(
        f'/channels/instagram/conversations/{conversation["id"]}/messages?tenant_id=2',
        headers=auth("tenant-b"),
    ).status_code == 404

    # Deliver the exact same bytes twice more: idempotency is preserved.
    assert client.post("/webhook/instagram", content=body, headers=headers).status_code == 200
    assert count(engine, "sendro_channel_webhook_deliveries") == 1
    assert manual_once(ci_http)["status"] == "idle"

    # Close ingestion again before finishing the test.
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "false")
    assert client.post("/webhook/instagram", content=body, headers=headers).status_code == 503
    assert count(engine, "sendro_channel_messages") == 1


def test_unsupported_signed_batch_quarantines_atomically(ci_http):
    client, engine, _, monkeypatch = ci_http
    payload = synthetic_dm(mid="would-be-valid")
    payload["entry"][0]["messaging"].append({
        "sender": {"id": "p2p-synthetic-guest"},
        "recipient": {"id": ENROLLED_BUSINESS},
        "read": {"mid": "unsupported-read"},
    })
    body, headers = signed_payload(payload)
    allow_ci_ingestion(ci_http)
    assert client.post("/webhook/instagram", content=body, headers=headers).status_code == 200
    outcome = manual_once(ci_http)
    assert outcome["status"] == "quarantined"
    assert outcome["inserted_messages"] == 0
    assert count(engine, "sendro_channel_messages") == 0
    assert count(engine, "sendro_channel_conversations") == 0
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT processing_state, last_error_code FROM
            public.sendro_channel_webhook_deliveries
        """)).mappings().one()
    assert row["processing_state"] == "quarantined"
    assert row["last_error_code"] == "unsupported_or_invalid_event"
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "false")


def test_multi_tenant_signed_batch_never_cross_routes(ci_http):
    client, engine, _, monkeypatch = ci_http
    other = synthetic_dm("mid-other", business=SECOND_BUSINESS)
    first = synthetic_dm("mid-first", business=ENROLLED_BUSINESS)
    batch = {"object": "instagram", "entry": first["entry"] + other["entry"]}
    body, headers = signed_payload(batch)
    allow_ci_ingestion(ci_http)
    assert client.post("/webhook/instagram", content=body, headers=headers).status_code == 200
    assert manual_once(ci_http)["inserted_messages"] == 2
    with engine.connect() as conn:
        conv = conn.execute(text("""
            SELECT tenant_id, external_customer_id
            FROM public.sendro_channel_conversations ORDER BY tenant_id
        """)).mappings().all()
    assert [(r["tenant_id"], r["external_customer_id"]) for r in conv] == [
        (1, "p2p-synthetic-guest"), (2, "p2p-synthetic-guest")
    ]
    assert client.get("/channels/instagram/conversations?tenant_id=2",
                      headers=auth("tenant-a")).status_code == 403
    assert client.get("/channels/instagram/conversations?tenant_id=2",
                      headers=auth("tenant-b")).status_code == 200
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "false")
