"""Phase 2K-A: synthetic, isolated queue retry and health tests.

No Render connections, no service scheduling, no Meta traffic or secrets.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend.app.instagram_queue_reliability import (
    read_instagram_queue_health,
    retry_delay_seconds,
    schedule_transient_retry,
)


UTC_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def queue_engine():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as db:
        db.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        db.exec_driver_sql("""
            CREATE TABLE public.sendro_channel_webhook_deliveries (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                processing_state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TIMESTAMP,
                received_at TIMESTAMP NOT NULL,
                processed_at TIMESTAMP,
                last_error_code TEXT
            )
        """)
        db.exec_driver_sql("""
            INSERT INTO public.sendro_channel_webhook_deliveries
                (id, provider, processing_state, attempts, next_attempt_at,
                 received_at)
            VALUES
                (1, 'instagram', 'pending', 0, NULL, '2026-10-15 11:00:00'),
                (2, 'instagram', 'pending', 0, '2999-01-01 00:00:00',
                    '2026-10-15 11:50:00'),
                (3, 'instagram', 'failed', 5, NULL, '2026-10-15 10:00:00'),
                (4, 'instagram', 'quarantined', 1, NULL, '2026-10-15 10:00:00'),
                (5, 'whatsapp', 'pending', 0, NULL, '2026-10-15 11:00:00')
        """)
    try:
        yield engine
    finally:
        engine.dispose()


def get_row(engine, number):
    with engine.connect() as db:
        return db.execute(text("""
            SELECT provider, processing_state, attempts, next_attempt_at,
                   last_error_code
            FROM public.sendro_channel_webhook_deliveries
            WHERE id = :id
        """), {"id": number}).one()


def test_health_reports_due_delayed_terminal_states_without_customer_data(queue_engine):
    health = read_instagram_queue_health(queue_engine, now=UTC_NOW)
    assert health["states"] == {
        "pending": 2, "processing": 0, "processed": 0,
        "quarantined": 1, "failed": 1,
    }
    assert health["due"] == 1
    assert health["deferred"] == 1
    assert health["oldest_due_age_seconds"] == 3600
    assert health["alert_codes"] == [
        "failed_deliveries", "quarantined_deliveries", "stale_pending_delivery",
    ]
    assert "id" not in health
    assert "payload" not in str(health)
    assert get_row(queue_engine, 1).processing_state == "pending"


def test_backlog_alert_has_configurable_limit(queue_engine):
    health = read_instagram_queue_health(
        queue_engine, now=UTC_NOW, backlog_threshold=1, stale_minutes=120,
    )
    assert "pending_backlog" in health["alert_codes"]
    assert "stale_pending_delivery" not in health["alert_codes"]


def test_backoff_is_exponential_capped_and_validated():
    assert [retry_delay_seconds(x) for x in (1, 2, 3, 5, 10)] == [
        30, 60, 120, 480, 3600,
    ]
    for value in (0, -1, 1.5, True, None):
        with pytest.raises(ValueError):
            retry_delay_seconds(value)


def test_schedule_retry_uses_compare_and_swap_and_never_touches_whatsapp(queue_engine):
    first = schedule_transient_retry(queue_engine, 1, 0, now=UTC_NOW)
    assert first["updated"] is True
    assert first["state"] == "pending"
    assert first["attempts"] == 1
    assert first["retry_at"] == UTC_NOW + timedelta(seconds=30)

    pending = get_row(queue_engine, 1)
    assert pending.processing_state == "pending"
    assert pending.attempts == 1
    assert pending.last_error_code == "transient_processing_failure"

    # A stale retry must never increment twice.
    assert schedule_transient_retry(queue_engine, 1, 0, now=UTC_NOW)["updated"] is False
    assert get_row(queue_engine, 1).attempts == 1

    # Different provider and terminal states must never be modified.
    assert schedule_transient_retry(queue_engine, 5, 0, now=UTC_NOW)["updated"] is False
    assert schedule_transient_retry(queue_engine, 3, 5, now=UTC_NOW)["updated"] is False
    assert schedule_transient_retry(queue_engine, 4, 1, now=UTC_NOW)["updated"] is False
    assert get_row(queue_engine, 5).provider == "whatsapp"


def test_exhausted_retries_finish_in_failed_state(queue_engine):
    # Five total failed attempts, each with a fixed expected-attempt CAS.
    for expected in range(5):
        result = schedule_transient_retry(queue_engine, 1, expected, now=UTC_NOW)
        assert result["updated"] is True
        assert result["attempts"] == expected + 1
        if expected < 4:
            assert result["state"] == "pending"
            assert result["retry_at"] == UTC_NOW + timedelta(
                seconds=retry_delay_seconds(expected + 1)
            )
        else:
            assert result["state"] == "failed"
            assert result["retry_at"] is None

    saved = get_row(queue_engine, 1)
    assert saved.processing_state == "failed"
    assert saved.attempts == 5
    assert saved.next_attempt_at is None
    assert schedule_transient_retry(queue_engine, 1, 5, now=UTC_NOW)["updated"] is False


def test_retry_arguments_and_missing_table_fail_closed(queue_engine):
    for kwargs in [
        {"delivery_id": -1, "expected_attempts": 0},
        {"delivery_id": 1, "expected_attempts": -1},
        {"delivery_id": 1, "expected_attempts": 0, "max_attempts": 0},
    ]:
        with pytest.raises(ValueError):
            schedule_transient_retry(queue_engine, now=UTC_NOW, **kwargs)
    with queue_engine.begin() as db:
        db.exec_driver_sql("DROP TABLE public.sendro_channel_webhook_deliveries")
    with pytest.raises(Exception):
        read_instagram_queue_health(queue_engine, now=UTC_NOW)
    with pytest.raises(Exception):
        schedule_transient_retry(queue_engine, 1, 0, now=UTC_NOW)
