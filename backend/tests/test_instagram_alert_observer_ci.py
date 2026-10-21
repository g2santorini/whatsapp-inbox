"""CI-only independent Instagram queue observation / durable incident tests.

All IDs, provider events and keys are synthetic. Fixture creation / writes
are restricted to the ephemeral GitHub PostgreSQL 16 service, not Render.
"""
import json

import pytest
from sqlalchemy import create_engine, text

from backend.app.instagram_alert_observer_ci import (
    InstagramAlertObserverDisabled,
    InstagramAlertObserverFailure,
    observe_ephemeral_instagram_alerts,
)
from backend.app.instagram_alert_outbox_ci import InstagramAlertOutboxDisabled
from backend.app.instagram_delivery_worker import (
    process_one_pending_instagram_delivery,
)
from backend.tests.test_instagram_alert_outbox_ci import (
    alert_flags, ci_alerts, read_rows,
)
from backend.tests.test_instagram_postgres_supervision_ci import ci_supervisor
from backend.tests.test_instagram_manual_migrations_postgres import (
    replay_engine, payload, store,
)


def observer_flags(**overrides):
    return alert_flags(INSTAGRAM_ALERT_OBSERVER_CI_ENABLED="true", **overrides)


def observe(engine, **kwargs):
    return observe_ephemeral_instagram_alerts(
        engine, environ=observer_flags(), **kwargs,
    )


def test_independent_observer_requires_extra_ci_flag_and_right_db(ci_alerts):
    engine, key = ci_alerts
    with pytest.raises(InstagramAlertObserverDisabled):
        observe_ephemeral_instagram_alerts(
            engine, environ=alert_flags(),
        )
    for flags in (
        observer_flags(GITHUB_ACTIONS="false"),
        observer_flags(SENDRO_INSTAGRAM_PG_CI_APPROVAL="unapproved"),
        observer_flags(INSTAGRAM_ALERT_OUTBOX_CI_ENABLED="false"),
    ):
        with pytest.raises(InstagramAlertOutboxDisabled):
            observe_ephemeral_instagram_alerts(engine, environ=flags)

    # SQLAlchemy engine creation makes NO network connection.
    fake_db = create_engine("postgresql+psycopg://fake:fake@render.invalid:5432/sendro")
    try:
        with pytest.raises(InstagramAlertOutboxDisabled):
            observe_ephemeral_instagram_alerts(fake_db, environ=observer_flags())
    finally:
        fake_db.dispose()
    assert read_rows(engine) == ()


def test_worker_can_commit_without_alert_then_independent_observer_recovers(ci_alerts):
    engine, key = ci_alerts
    store(engine, key, payload(
        "ci-observer-quarantine", business="ci-observer-unknown-business",
    ))

    # Deliberately invoke the worker BY ITSELF: there is no supervisor
    # callback and no alert persistence. This simulates a callback lost
    # after the worker commits, without altering the production system.
    result = process_one_pending_instagram_delivery(engine, key)
    assert result.status == "quarantined"
    assert result.inserted_messages == 0
    assert read_rows(engine) == ()

    first = observe(engine)
    assert first == {
        "alert_codes": ("quarantined_deliveries",), "persisted": 1,
    }
    records = read_rows(engine)
    assert len(records) == 1
    assert records[0]["code"] == "quarantined_deliveries"
    assert records[0]["snapshot"]["states"]["quarantined"] == 1
    assert records[0]["observations"] == 1

    # The independent observer is idempotent at the incident-key level.
    repeated = observe(engine)
    assert repeated == first
    assert len(read_rows(engine)) == 1
    assert read_rows(engine)[0]["observations"] == 2

    with engine.connect() as db:
        queue = db.execute(text("""
            SELECT processing_state, attempts
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram'
        """)).one()
        messages = db.execute(text(
            "SELECT COUNT(*) FROM public.sendro_channel_messages"
        )).scalar_one()
        conversations = db.execute(text(
            "SELECT COUNT(*) FROM public.sendro_channel_conversations"
        )).scalar_one()
    assert queue.processing_state == "quarantined"
    assert queue.attempts == 1
    assert (messages, conversations) == (0, 0)
    serialized = json.dumps(read_rows(engine))
    assert key not in serialized
    assert "ci-observer-unknown-business" not in serialized
    assert "ci-observer-quarantine" not in serialized


def test_processing_state_alerts_without_releasing_or_touching_delivery(ci_alerts):
    engine, key = ci_alerts
    store(engine, key, payload(
        "ci-observer-stranded", business="ig-phase2r-business",
    ))
    # A committed processing state is impossible for the designed worker,
    # but external/legacy writers may leave one in this state.
    with engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET processing_state='processing'
            WHERE provider='instagram' AND processing_state='pending'
        """))
    with engine.connect() as db:
        before = db.execute(text("""
            SELECT processing_state, attempts, payload_ciphertext
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram'
        """)).one()

    result = observe(engine)
    assert result == {
        "alert_codes": ("unresolved_processing_delivery",),
        "persisted": 1,
    }
    assert [a["code"] for a in read_rows(engine)] == [
        "unresolved_processing_delivery",
    ]
    with engine.connect() as db:
        after = db.execute(text("""
            SELECT processing_state, attempts, payload_ciphertext
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram'
        """)).one()
    assert after == before
    assert after.processing_state == "processing"


def test_missing_alert_outbox_fails_closed_and_later_observation_recovers(ci_alerts):
    engine, key = ci_alerts
    store(engine, key, payload(
        "ci-observer-retry", business="ci-observer-unregistered",
    ))
    assert process_one_pending_instagram_delivery(engine, key).status == "quarantined"

    # Mimic storage outage by removing ONLY the ephemeral CI outbox table.
    with engine.begin() as db:
        db.execute(text("DROP TABLE public.sendro_ci_instagram_alert_outbox"))
    with pytest.raises(
        InstagramAlertObserverFailure,
        match="observation or alert persistence unavailable",
    ) as failure:
        observe(engine)
    assert "ci-observer-unregistered" not in str(failure.value)

    with engine.connect() as db:
        row = db.execute(text("""
            SELECT processing_state, attempts, payload_ciphertext
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider='instagram'
        """)).one()
    assert row.processing_state == "quarantined"
    assert row.attempts == 1

    # The fixture's CI-only object is restored; the next manual sample
    # catches the still-present incident. No automatic scheduler exists.
    with engine.begin() as db:
        db.execute(text("""
            CREATE TABLE public.sendro_ci_instagram_alert_outbox (
                alert_code TEXT PRIMARY KEY,
                snapshot JSONB NOT NULL,
                observation_count BIGINT NOT NULL CHECK (observation_count > 0),
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
    assert observe(engine)["persisted"] == 1
    assert read_rows(engine)[0]["code"] == "quarantined_deliveries"


def test_healthy_empty_queue_is_read_only_and_writes_no_alert(ci_alerts):
    engine, key = ci_alerts
    assert observe(engine) == {"alert_codes": (), "persisted": 0}
    assert read_rows(engine) == ()

    # Invalid inspector thresholds must never be silently accepted.
    with pytest.raises(InstagramAlertObserverFailure):
        observe(engine, stale_minutes=0)
    assert read_rows(engine) == ()
