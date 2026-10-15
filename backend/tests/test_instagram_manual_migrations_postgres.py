"""Phase 2M: replay pinned, operator-authored Instagram SQL steps 1–6.

NEVER RUN AGAINST RENDER/STAGING/PRODUCTION.
Only the ephemeral GitHub Actions PostgreSQL service from Phase 2L is allowed.

These SQL snapshots are *authored manual migrations* in open PRs #12–#17,
not evidence that identical migrations were applied to the live database.
"""
import json
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from backend.app.instagram_delivery_worker import process_one_pending_instagram_delivery
from backend.app.instagram_ingestion import persist_instagram_webhook
from backend.app.instagram_queue_reliability import (
    read_instagram_queue_health,
    schedule_transient_retry,
)
from backend.tests.test_instagram_postgres_isolation import (
    TEST_URL_ENV,
    require_ephemeral_ci_postgres,
)


MIGRATIONS_DIR = Path(__file__).parent / "fixtures" / "instagram_migrations"


@pytest.fixture(scope="module")
def replay_engine():
    url = os.environ.get(TEST_URL_ENV)
    if not url:
        pytest.skip("This test can only run in the disposable GitHub PostgreSQL job")

    # Full allowlist before opening *any* database connection.
    approved_url = require_ephemeral_ci_postgres(url, os.environ)
    engine = create_engine(
        approved_url,
        connect_args={"options": "-c lock_timeout=2500 -c statement_timeout=10000"},
    )
    try:
        with engine.begin() as db:
            # Safe because the URL is restricted to the ephemeral GitHub DB.
            for table in (
                "sendro_channel_webhook_deliveries",
                "sendro_channel_messages",
                "sendro_channel_conversations",
                "sendro_channel_accounts",
                "sendro_tenant_users",
                "sendro_tenants",
                "users",
            ):
                db.execute(text(f"DROP TABLE IF EXISTS public.{table} CASCADE"))
            # Existing Sendro application has public.users. A single minimal
            # stub supplies only the FK requirement in this throwaway DB.
            db.execute(text("CREATE TABLE public.users (id INTEGER PRIMARY KEY)"))

        for step in range(1, 7):
            script = (MIGRATIONS_DIR / f"step{step}.sql").read_text(encoding="utf-8")
            assert "BEGIN;" in script and "COMMIT;" in script
            # psycopg ClientCursor uses PostgreSQL's simple-query protocol,
            # supporting the original operator SQL as one multi-command script
            # with its own BEGIN/COMMIT and locally scoped timeout settings.
            raw = engine.raw_connection()
            try:
                from psycopg import ClientCursor
                raw.rollback()
                with ClientCursor(raw.driver_connection) as cursor:
                    cursor.execute(script)
                raw.commit()
            finally:
                raw.close()
        yield engine
    finally:
        engine.dispose()


def read(engine, sql, params=None):
    with engine.connect() as db:
        return db.execute(text(sql), params or {}).mappings().all()


def seed_business(engine, *, tenant="isolated-a", business="ig-ci-business-a"):
    with engine.begin() as db:
        tenant_id = db.execute(text("""
            INSERT INTO public.sendro_tenants (slug, display_name)
            VALUES (:slug, 'CI Only') RETURNING id
        """), {"slug": tenant}).scalar_one()
        account_id = db.execute(text("""
            INSERT INTO public.sendro_channel_accounts
                (tenant_id, platform, external_account_id, status)
            VALUES (:tenant, 'instagram', :business, 'testing')
            RETURNING id
        """), {"tenant": tenant_id, "business": business}).scalar_one()
    return tenant_id, account_id


def payload(mid, *, business="ig-ci-business-a", sender="guest-test", media=False):
    message = {"mid": mid}
    if media:
        message["attachments"] = [{
            "type": "image", "payload": {"url": "https://example.invalid/test.jpg"},
        }]
    else:
        message["text"] = "Synthetic message – no customer data"
    return {
        "object": "instagram",
        "entry": [{
            "id": business,
            "messaging": [{
                "sender": {"id": sender},
                "recipient": {"id": business},
                "timestamp": 1792000000123,
                "message": message,
            }],
        }],
    }


def store(engine, key, body):
    persist_instagram_webhook(json.dumps(body).encode("utf-8"), key, engine)


def test_pinned_migrations_create_all_six_tables_and_tenant_constraints(replay_engine):
    tables = read(replay_engine, """
        SELECT tablename FROM pg_catalog.pg_tables
        WHERE schemaname = 'public'
          AND tablename LIKE 'sendro_%'
        ORDER BY tablename
    """)
    assert [r["tablename"] for r in tables] == [
        "sendro_channel_accounts", "sendro_channel_conversations",
        "sendro_channel_messages", "sendro_channel_webhook_deliveries",
        "sendro_tenant_users", "sendro_tenants",
    ]
    foreign_keys = read(replay_engine, """
        SELECT conname FROM pg_constraint
        WHERE contype = 'f' AND connamespace = 'public'::regnamespace
    """)
    names = {r["conname"] for r in foreign_keys}
    assert "fk_sendro_channel_conversations_account_tenant" in names
    assert "fk_sendro_channel_messages_conversation_scope" in names
    assert "fk_sendro_channel_messages_sender_member" in names


def test_real_migration_rejects_whatsapp_row_in_instagram_only_queue(replay_engine):
    with pytest.raises(IntegrityError):
        with replay_engine.begin() as db:
            db.execute(text("""
                INSERT INTO public.sendro_channel_webhook_deliveries
                    (provider, raw_body_sha256, payload_ciphertext)
                VALUES ('whatsapp', :digest, :encrypted)
            """), {"digest": "a" * 64, "encrypted": b"synthetic"})
    assert read(replay_engine, """
        SELECT * FROM public.sendro_channel_webhook_deliveries
        WHERE provider = 'whatsapp'
    """) == []


def test_true_manual_sql_schema_accepts_encrypted_real_worker_flow(replay_engine):
    engine = replay_engine
    seed_business(engine)
    key = Fernet.generate_key().decode("ascii")
    store(engine, key, payload("full-schema-media", media=True))
    store(engine, key, payload("full-schema-text"))

    first = process_one_pending_instagram_delivery(engine, key)
    second = process_one_pending_instagram_delivery(engine, key)
    assert first.status == second.status == "processed"
    assert first.inserted_messages == second.inserted_messages == 1
    saved = read(engine, """
        SELECT content, media_json, message_type
        FROM public.sendro_channel_messages ORDER BY id
    """)
    assert len(saved) == 2
    assert {r["message_type"] for r in saved} == {"text", "media"}
    assert [r["media_json"] for r in saved if r["message_type"] == "media"][0][0]["type"] == "image"
    counts = read(engine, """
        SELECT unread_count FROM public.sendro_channel_conversations
    """)
    assert counts[0]["unread_count"] == 2
    assert process_one_pending_instagram_delivery(engine, key).status == "idle"

    duplicate = payload("full-schema-media", media=True)
    duplicate["entry"][0]["time"] = 1792000000124
    store(engine, key, duplicate)
    assert process_one_pending_instagram_delivery(engine, key).inserted_messages == 0
    assert len(read(engine, "SELECT id FROM public.sendro_channel_messages")) == 2


def test_real_migration_prevents_cross_tenant_conversation_fk(replay_engine):
    engine = replay_engine
    own_tenant, own_account = seed_business(
        engine, tenant="isolated-own", business="ig-ci-business-own",
    )
    foreign_tenant, foreign_account = seed_business(
        engine, tenant="isolated-foreign", business="ig-ci-business-foreign",
    )
    assert own_tenant != foreign_tenant
    assert own_account != foreign_account
    with pytest.raises(IntegrityError):
        with engine.begin() as db:
            db.execute(text("""
                INSERT INTO public.sendro_channel_conversations
                    (tenant_id, channel_account_id, external_customer_id)
                VALUES (:other_tenant, :account, 'not-allowed')
            """), {"other_tenant": foreign_tenant, "account": own_account})


def test_real_migration_retry_backoff_and_health(replay_engine):
    engine = replay_engine
    key = Fernet.generate_key().decode("ascii")
    store(engine, key, payload("retry-full-schema", business="ig-ci-business-own"))
    row = read(engine, """
        SELECT id, attempts FROM public.sendro_channel_webhook_deliveries
        WHERE processing_state = 'pending'
    """)[0]
    scheduled = schedule_transient_retry(engine, row["id"], row["attempts"])
    assert scheduled["updated"]
    assert scheduled["state"] == "pending"
    health = read_instagram_queue_health(engine)
    assert health["deferred"] >= 1
    assert process_one_pending_instagram_delivery(engine, key).status == "idle"
    with engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET next_attempt_at = NULL WHERE id = :id
        """), {"id": row["id"]})
    assert process_one_pending_instagram_delivery(engine, key).inserted_messages == 1
