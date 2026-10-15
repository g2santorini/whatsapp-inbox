"""Phase 2L: real PostgreSQL transaction/concurrency tests in disposable CI only.

This file MUST NOT be run against Render, staging, production, or an external DB.
Only the ephemeral PostgreSQL 16 service on CI loopback port 55439 qualifies.
IDs, encryption keys and payloads below are synthetic.
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.app.instagram_delivery_worker import (
    InstagramTransientDeliveryFailure,
    process_one_pending_instagram_delivery,
)
from backend.app.instagram_ingestion import persist_instagram_webhook
from backend.app.instagram_queue_reliability import (
    read_instagram_queue_health,
    schedule_transient_retry,
)


TEST_URL_ENV = "SENDRO_INSTAGRAM_PG_CI_URL"
TEST_APPROVAL_ENV = "SENDRO_INSTAGRAM_PG_CI_APPROVAL"


def require_ephemeral_ci_postgres(url, environment):
    """Guard BEFORE opening a connection or modifying any schema.

    The temporary CI DB is known by loopback host, an unusual published port,
    its exact DB and user names, and two independent CI-only environment gates.
    """
    candidate = make_url(url)
    if not (
        environment.get("GITHUB_ACTIONS") == "true"
        and environment.get(TEST_APPROVAL_ENV) == "ephemeral-local-service-only"
        and candidate.get_backend_name() == "postgresql"
        and candidate.host in ("127.0.0.1", "localhost")
        and candidate.port == 55439
        and candidate.database == "sendro_ig_ci"
        and candidate.username == "sendro_ci"
    ):
        raise RuntimeError("Refusing non-ephemeral Instagram PostgreSQL test database")
    return candidate


@pytest.mark.parametrize("bad_url", [
    "postgresql+psycopg://sendro_ci:dummy@db.render.com:5432/sendro_ig_ci",
    "postgresql+psycopg://sendro_ci:dummy@127.0.0.1:5432/sendro_ig_ci",
    "postgresql+psycopg://sendro_ci:dummy@127.0.0.1:55439/sendro",
    "postgresql+psycopg://appuser:dummy@127.0.0.1:55439/sendro_ig_ci",
    "sqlite:///fake.db",
])
def test_guard_refuses_external_or_mismatched_database(bad_url):
    with pytest.raises(RuntimeError, match="Refusing non-ephemeral"):
        require_ephemeral_ci_postgres(bad_url, {
            "GITHUB_ACTIONS": "true",
            TEST_APPROVAL_ENV: "ephemeral-local-service-only",
        })


def test_guard_requires_separate_ci_environment_gate():
    url = "postgresql+psycopg://sendro_ci:dummy@127.0.0.1:55439/sendro_ig_ci"
    with pytest.raises(RuntimeError):
        require_ephemeral_ci_postgres(url, {TEST_APPROVAL_ENV: "ephemeral-local-service-only"})
    with pytest.raises(RuntimeError):
        require_ephemeral_ci_postgres(url, {"GITHUB_ACTIONS": "true"})


DDL = (
    """
    CREATE TABLE public.sendro_channel_accounts (
        id BIGINT PRIMARY KEY,
        tenant_id BIGINT NOT NULL,
        platform TEXT NOT NULL,
        external_account_id TEXT NOT NULL,
        status TEXT NOT NULL,
        UNIQUE (platform, external_account_id)
    )
    """,
    """
    CREATE TABLE public.sendro_channel_conversations (
        id BIGSERIAL PRIMARY KEY,
        tenant_id BIGINT NOT NULL,
        channel_account_id BIGINT NOT NULL,
        external_customer_id TEXT NOT NULL,
        contact_name TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        unread_count INTEGER NOT NULL DEFAULT 0,
        last_message_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (channel_account_id, external_customer_id)
    )
    """,
    """
    CREATE TABLE public.sendro_channel_messages (
        id BIGSERIAL PRIMARY KEY,
        tenant_id BIGINT NOT NULL,
        channel_account_id BIGINT NOT NULL,
        conversation_id BIGINT NOT NULL,
        provider_message_id TEXT NOT NULL,
        direction TEXT NOT NULL,
        message_type TEXT NOT NULL,
        content TEXT,
        media_json JSONB,
        provider_timestamp TIMESTAMPTZ,
        UNIQUE (channel_account_id, provider_message_id)
    )
    """,
    """
    CREATE TABLE public.sendro_channel_webhook_deliveries (
        id BIGSERIAL PRIMARY KEY,
        provider TEXT NOT NULL,
        raw_body_sha256 TEXT NOT NULL,
        payload_ciphertext BYTEA NOT NULL,
        processing_state TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error_code TEXT,
        received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        next_attempt_at TIMESTAMPTZ,
        processed_at TIMESTAMPTZ,
        UNIQUE (provider, raw_body_sha256)
    )
    """,
)


@pytest.fixture(scope="session")
def ci_pg_engine():
    url = os.getenv(TEST_URL_ENV)
    if not url:
        pytest.skip("Ephemeral PostgreSQL only: CI URL not supplied")
    approved_url = require_ephemeral_ci_postgres(url, os.environ)
    engine = create_engine(
        approved_url,
        pool_size=6,
        max_overflow=2,
        connect_args={"options": "-c lock_timeout=2500 -c statement_timeout=8000"},
    )
    try:
        with engine.begin() as db:
            for table in (
                "sendro_channel_messages", "sendro_channel_conversations",
                "sendro_channel_accounts", "sendro_channel_webhook_deliveries",
            ):
                db.execute(text("DROP TABLE IF EXISTS public." + table + " CASCADE"))
            for ddl in DDL:
                db.execute(text(ddl))
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def ci_pg(ci_pg_engine):
    with ci_pg_engine.begin() as db:
        db.execute(text("""
            TRUNCATE TABLE public.sendro_channel_webhook_deliveries,
                           public.sendro_channel_messages,
                           public.sendro_channel_conversations,
                           public.sendro_channel_accounts
            RESTART IDENTITY CASCADE
        """))
        db.execute(text("""
            INSERT INTO public.sendro_channel_accounts
                (id, tenant_id, platform, external_account_id, status)
            VALUES
                (10, 1, 'instagram', 'ig-business-1', 'testing'),
                (20, 2, 'instagram', 'ig-business-2', 'active')
        """))
    return ci_pg_engine, Fernet.generate_key().decode("ascii")


def dm(message_id, *, business="ig-business-1", sender="guest-01", media=False):
    message = {"mid": message_id}
    if media:
        message["attachments"] = [
            {"type": "image", "payload": {"url": "https://example.invalid/synthetic.jpg"}}
        ]
    else:
        message["text"] = "Synthetic guest message"
    return {
        "sender": {"id": sender},
        "recipient": {"id": business},
        "timestamp": 1792000000123,
        "message": message,
    }


def envelope(item, *, business="ig-business-1", time=1792000000000):
    return {
        "object": "instagram",
        "entry": [{"id": business, "time": time, "messaging": [item]}],
    }


def store(engine, key, payload):
    persist_instagram_webhook(
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        key, engine,
    )


def query(engine, statement):
    with engine.connect() as db:
        return db.execute(text(statement)).mappings().all()


def test_real_postgres_encrypted_ingestion_media_jsonb_and_idempotency(ci_pg):
    engine, key = ci_pg
    payload = envelope(dm("media-01", media=True))
    store(engine, key, payload)
    store(engine, key, payload)  # Exact raw-body duplicate is deduped.
    assert len(query(engine, "SELECT * FROM public.sendro_channel_webhook_deliveries")) == 1

    result = process_one_pending_instagram_delivery(engine, key)
    assert result.status == "processed"
    assert result.inserted_messages == 1
    messages = query(engine, "SELECT * FROM public.sendro_channel_messages")
    assert len(messages) == 1
    assert messages[0]["message_type"] == "media"
    assert messages[0]["media_json"][0]["type"] == "image"
    assert query(engine, "SELECT unread_count FROM public.sendro_channel_conversations")[0]["unread_count"] == 1

    other_envelope = envelope(dm("media-01", media=True), time=1792000000001)
    store(engine, key, other_envelope)
    assert process_one_pending_instagram_delivery(engine, key).inserted_messages == 0
    assert len(query(engine, "SELECT * FROM public.sendro_channel_messages")) == 1
    assert query(engine, "SELECT unread_count FROM public.sendro_channel_conversations")[0]["unread_count"] == 1


def test_real_postgres_cross_tenant_routing_and_quarantine(ci_pg):
    engine, key = ci_pg
    store(engine, key, envelope(dm("cross-a", sender="same-guest")))
    store(engine, key, envelope(dm("cross-b", sender="same-guest",
                                   business="ig-business-2"),
                                business="ig-business-2"))
    results = [process_one_pending_instagram_delivery(engine, key) for _ in range(2)]
    assert sum(r.inserted_messages for r in results) == 2
    tenants = query(engine, """
        SELECT tenant_id, external_customer_id, channel_account_id
        FROM public.sendro_channel_conversations ORDER BY tenant_id
    """)
    assert [(r["tenant_id"], r["channel_account_id"]) for r in tenants] == [(1, 10), (2, 20)]
    assert all(row["external_customer_id"] == "same-guest" for row in tenants)

    store(engine, key, envelope(dm("unregistered", business="missing"),
                                business="missing"))
    assert process_one_pending_instagram_delivery(engine, key).status == "quarantined"
    assert len(query(engine, "SELECT * FROM public.sendro_channel_messages")) == 2
    assert read_instagram_queue_health(engine)["states"]["quarantined"] == 1


def test_skip_locked_does_not_block_on_another_workers_delivery(ci_pg):
    engine, key = ci_pg
    store(engine, key, envelope(dm("locked-first")))
    store(engine, key, envelope(dm("unlocked-second")))
    with engine.connect() as lock_connection:
        lock_tx = lock_connection.begin()
        try:
            first = lock_connection.execute(text("""
                SELECT id FROM public.sendro_channel_webhook_deliveries
                WHERE provider = 'instagram' ORDER BY id LIMIT 1 FOR UPDATE
            """)).scalar_one()
            with ThreadPoolExecutor(max_workers=1) as pool:
                worker = pool.submit(process_one_pending_instagram_delivery, engine, key)
                result = worker.result(timeout=7)
            assert result.status == "processed"
            assert result.inserted_messages == 1
            remaining = query(engine, """
                SELECT id, processing_state FROM public.sendro_channel_webhook_deliveries
                ORDER BY id
            """)
            assert remaining[0]["id"] == first
            assert remaining[0]["processing_state"] == "pending"
            assert remaining[1]["processing_state"] == "processed"
        finally:
            lock_tx.rollback()

    assert process_one_pending_instagram_delivery(engine, key).inserted_messages == 1
    assert len(query(engine, "SELECT * FROM public.sendro_channel_messages")) == 2


def test_concurrent_postgres_workers_never_duplicate_one_delivery(ci_pg):
    engine, key = ci_pg
    store(engine, key, envelope(dm("single-mid")))
    barrier = threading.Barrier(2)

    def start_together():
        barrier.wait(timeout=7)
        return process_one_pending_instagram_delivery(engine, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start_together) for _ in range(2)]
        results = [f.result(timeout=10) for f in futures]

    assert sum(r.inserted_messages for r in results) == 1
    assert sorted(r.status for r in results) == ["idle", "processed"]
    assert len(query(engine, "SELECT * FROM public.sendro_channel_messages")) == 1
    assert query(engine, "SELECT unread_count FROM public.sendro_channel_conversations")[0]["unread_count"] == 1


def test_concurrent_duplicate_mids_in_two_envelopes_remain_unique(ci_pg):
    engine, key = ci_pg
    store(engine, key, envelope(dm("same-mid"), time=1792000000000))
    store(engine, key, envelope(dm("same-mid"), time=1792000000001))
    barrier = threading.Barrier(2)

    def run_one():
        barrier.wait(timeout=7)
        return process_one_pending_instagram_delivery(engine, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=10) for f in
                   [pool.submit(run_one) for _ in range(2)]]

    assert sum(r.inserted_messages for r in results) == 1
    assert sorted(r.status for r in results) == ["processed", "processed"]
    assert len(query(engine, "SELECT * FROM public.sendro_channel_conversations")) == 1
    assert len(query(engine, "SELECT * FROM public.sendro_channel_messages")) == 1
    assert query(engine, "SELECT unread_count FROM public.sendro_channel_conversations")[0]["unread_count"] == 1


def test_real_postgres_rollback_then_cas_retry_then_success(ci_pg):
    engine, key = ci_pg
    store(engine, key, envelope(dm("rollback-mid")))

    # AFTER INSERT raises a genuine PostgreSQL serialization exception.
    # Entire transaction MUST roll back despite having inserted a message.
    with engine.begin() as db:
        db.execute(text("""
            CREATE FUNCTION public.ci_abort_instagram_insert()
            RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'synthetic serialization failure'
                    USING ERRCODE = '40001';
            END;
            $$
        """))
        db.execute(text("""
            CREATE TRIGGER ci_abort_instagram_insert
            AFTER INSERT ON public.sendro_channel_messages
            FOR EACH ROW EXECUTE FUNCTION public.ci_abort_instagram_insert()
        """))
    try:
        with pytest.raises(InstagramTransientDeliveryFailure) as error:
            process_one_pending_instagram_delivery(engine, key)
    finally:
        with engine.begin() as db:
            db.execute(text("DROP TRIGGER ci_abort_instagram_insert ON public.sendro_channel_messages"))
            db.execute(text("DROP FUNCTION public.ci_abort_instagram_insert()"))

    assert query(engine, "SELECT * FROM public.sendro_channel_messages") == []
    assert query(engine, "SELECT * FROM public.sendro_channel_conversations") == []
    row = query(engine, "SELECT * FROM public.sendro_channel_webhook_deliveries")[0]
    assert row["processing_state"] == "pending"
    assert row["attempts"] == 0

    retry = schedule_transient_retry(
        engine, error.value.delivery_id, error.value.expected_attempts,
        now=datetime.now(timezone.utc),
    )
    assert retry["updated"]
    assert retry["state"] == "pending"
    assert retry["attempts"] == 1
    assert process_one_pending_instagram_delivery(engine, key).status == "idle"
    with engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET next_attempt_at = NULL
            WHERE provider = 'instagram'
        """))
    assert process_one_pending_instagram_delivery(engine, key).inserted_messages == 1
    assert query(engine, "SELECT attempts FROM public.sendro_channel_webhook_deliveries")[0]["attempts"] == 2
    assert query(engine, "SELECT unread_count FROM public.sendro_channel_conversations")[0]["unread_count"] == 1


def test_postgres_deferred_due_guard_and_whatsapp_queue_isolation(ci_pg):
    engine, key = ci_pg
    store(engine, key, envelope(dm("future-mid")))
    with engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET next_attempt_at = CURRENT_TIMESTAMP + interval '20 minutes'
            WHERE provider = 'instagram'
        """))
        db.execute(text("""
            INSERT INTO public.sendro_channel_webhook_deliveries (
                provider, raw_body_sha256, payload_ciphertext
            ) VALUES ('whatsapp', 'synthetic-whatsapp-only', decode('00', 'hex'))
        """))

    assert process_one_pending_instagram_delivery(engine, key).status == "idle"
    health = read_instagram_queue_health(engine)
    assert health["due"] == 0
    assert health["deferred"] == 1

    with engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET next_attempt_at = CURRENT_TIMESTAMP - interval '1 second'
            WHERE provider = 'instagram'
        """))
    assert process_one_pending_instagram_delivery(engine, key).inserted_messages == 1
    whatsapp = query(engine, """
        SELECT provider, processing_state, attempts
        FROM public.sendro_channel_webhook_deliveries
        WHERE provider = 'whatsapp'
    """)
    assert len(whatsapp) == 1
    assert (whatsapp[0]["provider"], whatsapp[0]["processing_state"], whatsapp[0]["attempts"]) == (
        "whatsapp", "pending", 0,
    )
