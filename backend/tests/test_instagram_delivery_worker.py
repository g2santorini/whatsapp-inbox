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


def test_same_message_id_for_different_customer_in_one_batch_quarantines(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(
        dm("m-shared", sender="guest-123"),
        dm("m-shared", sender="guest-456"),
    ))
    result = process_one_pending_instagram_delivery(engine, key)
    assert result.status == "quarantined"
    assert rows(engine, "sendro_channel_conversations") == []
    assert rows(engine, "sendro_channel_messages") == []
    assert rows(engine, "sendro_channel_webhook_deliveries")[0]["last_error_code"] == "message_identity_conflict"


def test_existing_message_id_cannot_be_replayed_as_another_customer(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("m-original", sender="guest-123")))
    assert process_one_pending_instagram_delivery(engine, key).inserted_messages == 1
    store(engine, key, envelope(dm("m-original", sender="guest-456")))
    result = process_one_pending_instagram_delivery(engine, key)
    assert result.status == "quarantined"
    assert len(rows(engine, "sendro_channel_conversations")) == 1
    assert len(rows(engine, "sendro_channel_messages")) == 1
    assert rows(engine, "sendro_channel_conversations")[0]["unread_count"] == 1


def test_duplicate_message_in_different_envelope_never_creates_other_threads(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("m-1")))
    assert process_one_pending_instagram_delivery(engine, key).inserted_messages == 1
    retry = envelope(dm("m-1"))
    retry["entry"][0]["time"] = 1792000000003
    store(engine, key, retry)
    assert process_one_pending_instagram_delivery(engine, key).inserted_messages == 0
    assert len(rows(engine, "sendro_channel_conversations")) == 1
    assert rows(engine, "sendro_channel_conversations")[0]["unread_count"] == 1



def test_deferred_delivery_is_not_claimed_before_retry_due_time(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("m-deferred")))
    with engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET next_attempt_at = '2999-01-01 00:00:00'
            WHERE provider = 'instagram'
        """))
    assert process_one_pending_instagram_delivery(engine, key).status == "idle"
    assert rows(engine, "sendro_channel_webhook_deliveries")[0]["processing_state"] == "pending"
    assert rows(engine, "sendro_channel_messages") == []

    with engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET next_attempt_at = NULL
            WHERE provider = 'instagram'
        """))
    ready = process_one_pending_instagram_delivery(engine, key)
    assert ready.status == "processed"
    assert ready.inserted_messages == 1
    assert len(rows(engine, "sendro_channel_messages")) == 1



# Phase 2K-B: supervisor tests use this module's isolated SQLite fixture only.
from types import SimpleNamespace
from sqlalchemy.exc import OperationalError, ProgrammingError

from backend.app import instagram_delivery_worker as worker_module
from backend.app.instagram_queue_reliability import is_transient_database_failure
from backend.app.instagram_supervision import (
    InstagramSupervisorDisabled,
    InstagramSupervisorFailure,
    run_isolated_supervised_batch,
)


def isolated_supervisor_flags():
    return {
        "INSTAGRAM_SUPERVISOR_TEST_ENABLED": "true",
        "INSTAGRAM_ISOLATED_DB_APPROVED": "true",
    }


def test_supervision_is_default_locked_even_with_queued_messages(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("locked")))
    with pytest.raises(InstagramSupervisorDisabled):
        run_isolated_supervised_batch(
            engine, key, environ={}, on_alert=lambda event: None,
        )
    assert len(rows(engine, "sendro_channel_messages")) == 0
    assert rows(engine, "sendro_channel_webhook_deliveries")[0]["processing_state"] == "pending"


def test_supervisor_rejects_shared_postgres_even_when_explicitly_enabled(setup_worker):
    _, key = setup_worker
    fake_postgres = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    with pytest.raises(InstagramSupervisorDisabled):
        run_isolated_supervised_batch(
            fake_postgres, key, environ=isolated_supervisor_flags(),
            on_alert=lambda event: None,
        )


@pytest.mark.parametrize("max_deliveries", [0, 26, True, 1.5])
def test_supervisor_rejects_invalid_batch_bounds(setup_worker, max_deliveries):
    engine, key = setup_worker
    with pytest.raises(InstagramSupervisorDisabled):
        run_isolated_supervised_batch(
            engine, key, environ=isolated_supervisor_flags(),
            max_deliveries=max_deliveries, on_alert=lambda event: None,
        )


def test_supervisor_requires_alert_sink(setup_worker):
    engine, key = setup_worker
    with pytest.raises(InstagramSupervisorDisabled):
        run_isolated_supervised_batch(
            engine, key, environ=isolated_supervisor_flags(),
        )


def test_bounded_supervisor_processes_only_max_messages(setup_worker):
    engine, key = setup_worker
    for mid in ("bounded-a", "bounded-b", "bounded-c"):
        store(engine, key, envelope(dm(mid)))
    outcome = run_isolated_supervised_batch(
        engine, key, environ=isolated_supervisor_flags(),
        max_deliveries=2, on_alert=lambda event: None,
    )
    assert outcome["processed"] == 2
    assert outcome["messages"] == 2
    assert len(rows(engine, "sendro_channel_messages")) == 2
    assert [x["processing_state"] for x in rows(engine, "sendro_channel_webhook_deliveries")].count("pending") == 1


def test_quarantine_alert_contains_no_customer_ids_or_text(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("do-not-leak", sender="private-customer-id",
                                    business="unknown-business"), business="unknown-business"))
    alerts = []
    outcome = run_isolated_supervised_batch(
        engine, key, environ=isolated_supervisor_flags(),
        on_alert=alerts.append,
    )
    assert outcome["quarantined"] == 1
    assert len(rows(engine, "sendro_channel_messages")) == 0
    assert alerts[0]["codes"] == ("quarantined_deliveries",)
    assert "private-customer-id" not in str(alerts)
    assert "unknown-business" not in str(alerts)


def make_sql_error(cls, state):
    class SyntheticDBFailure(Exception):
        sqlstate = state

    return cls("synthetic database error", {}, SyntheticDBFailure("sanitized"))


def test_transient_classifier_explicitly_whitelists_retryable_sqlstates():
    for state in ("40001", "40P01", "55P03", "08006"):
        assert is_transient_database_failure(
            make_sql_error(OperationalError, state)
        )
    for state in ("42P01", "23505", None):
        assert not is_transient_database_failure(
            make_sql_error(ProgrammingError, state)
        )
    assert not is_transient_database_failure(ValueError("not a DB exception"))


def test_supervision_retries_only_after_rollback_and_can_recover(setup_worker, monkeypatch):
    engine, key = setup_worker
    store(engine, key, envelope(dm("retry-case")))
    original = worker_module._decode_events

    def fail_once(*args):
        raise make_sql_error(OperationalError, "40001")

    monkeypatch.setattr(worker_module, "_decode_events", fail_once)
    outcome = run_isolated_supervised_batch(
        engine, key, environ=isolated_supervisor_flags(),
        on_alert=lambda event: None,
    )
    assert outcome["deferred"] == 1
    assert len(rows(engine, "sendro_channel_messages")) == 0
    row = rows(engine, "sendro_channel_webhook_deliveries")[0]
    assert row["attempts"] == 1
    assert row["next_attempt_at"] is not None
    assert row["processing_state"] == "pending"

    # Simulate retry becoming due, then verify exactly one guest DM persists.
    monkeypatch.setattr(worker_module, "_decode_events", original)
    with engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET next_attempt_at = NULL WHERE provider = 'instagram'
        """))
    second = run_isolated_supervised_batch(
        engine, key, environ=isolated_supervisor_flags(),
        on_alert=lambda event: None,
    )
    assert second["processed"] == 1
    assert second["messages"] == 1
    assert len(rows(engine, "sendro_channel_messages")) == 1
    assert rows(engine, "sendro_channel_conversations")[0]["unread_count"] == 1


def test_last_retry_fails_terminally_and_emits_aggregate_alert(setup_worker, monkeypatch):
    engine, key = setup_worker
    store(engine, key, envelope(dm("final-attempt")))
    with engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET attempts = 4 WHERE provider = 'instagram'
        """))
    monkeypatch.setattr(worker_module, "_decode_events",
        lambda *args: (_ for _ in ()).throw(make_sql_error(OperationalError, "40P01")))
    alerts = []
    result = run_isolated_supervised_batch(
        engine, key, environ=isolated_supervisor_flags(), on_alert=alerts.append,
    )
    assert result["failed"] == 1
    assert rows(engine, "sendro_channel_webhook_deliveries")[0]["attempts"] == 5
    assert rows(engine, "sendro_channel_webhook_deliveries")[0]["processing_state"] == "failed"
    assert "failed_deliveries" in alerts[0]["codes"]
    assert len(rows(engine, "sendro_channel_messages")) == 0


def test_nontransient_db_error_is_never_scheduled_for_retry(setup_worker, monkeypatch):
    engine, key = setup_worker
    store(engine, key, envelope(dm("syntax-failure")))
    monkeypatch.setattr(worker_module, "_decode_events",
        lambda *args: (_ for _ in ()).throw(make_sql_error(ProgrammingError, "42P01")))
    with pytest.raises(InstagramSupervisorFailure, match="operator review"):
        run_isolated_supervised_batch(
            engine, key, environ=isolated_supervisor_flags(),
            on_alert=lambda event: None,
        )
    row = rows(engine, "sendro_channel_webhook_deliveries")[0]
    assert row["attempts"] == 0
    assert row["next_attempt_at"] is None
    assert row["processing_state"] == "pending"


def test_alert_callback_failure_is_not_silenced(setup_worker):
    engine, key = setup_worker
    store(engine, key, envelope(dm("quarantine", business="unknown"), business="unknown"))

    def broken_sink(_event):
        raise RuntimeError("test-only alert endpoint unavailable")

    with pytest.raises(InstagramSupervisorFailure, match="alert callback failed"):
        run_isolated_supervised_batch(
            engine, key, environ=isolated_supervisor_flags(),
            on_alert=broken_sink,
        )
    assert rows(engine, "sendro_channel_webhook_deliveries")[0]["processing_state"] == "quarantined"
