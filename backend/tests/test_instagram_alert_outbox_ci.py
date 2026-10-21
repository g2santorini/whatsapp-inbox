"""Durable redacted alert proof on *disposable GitHub PostgreSQL only*.

No external transport, account integration, Render DB or real Instagram DM.
The test-only table exists nowhere in production and is never auto-created by
the application. The replay_engine fixture validates CI identity first.
"""
import json

import pytest
from sqlalchemy import create_engine, text

from backend.app.instagram_alert_outbox_ci import (
    InstagramAlertOutboxDisabled,
    InstagramAlertOutboxInvalid,
    persist_ci_instagram_alerts,
    read_ci_instagram_alerts,
)
from backend.app.instagram_postgres_supervision import (
    InstagramPostgresSupervisorFailure,
)
from backend.tests.test_instagram_postgres_supervision_ci import (
    ci_supervisor, run,
)
from backend.tests.test_instagram_manual_migrations_postgres import (
    payload, store,
)


def alert_flags(**updates):
    return {
        "GITHUB_ACTIONS": "true",
        "SENDRO_INSTAGRAM_PG_CI_APPROVAL": "ephemeral-local-service-only",
        "INSTAGRAM_ALERT_OUTBOX_CI_ENABLED": "true",
        **updates,
    }


@pytest.fixture
def ci_alerts(ci_supervisor):
    engine, key = ci_supervisor
    # ci_supervisor -> replay_engine validated exact CI URL/approval before
    # opening a connection. This DDL is ONLY in disposable GitHub Postgres.
    with engine.begin() as db:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS public.sendro_ci_instagram_alert_outbox (
                alert_code TEXT PRIMARY KEY,
                snapshot JSONB NOT NULL,
                observation_count BIGINT NOT NULL CHECK (observation_count > 0),
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.execute(text("TRUNCATE public.sendro_ci_instagram_alert_outbox"))
    return engine, key


def read_rows(engine):
    return read_ci_instagram_alerts(engine, environ=alert_flags())


def valid_alert(*codes):
    return {
        "codes": tuple(codes),
        "states": {
            "pending": 0, "processing": 0, "processed": 0,
            "quarantined": 1, "failed": 0,
        },
        "due": 0,
        "deferred": 0,
    }


def test_reject_all_wrong_ci_identities_before_database_access(ci_alerts):
    engine, key = ci_alerts
    for flags in (
        {}, alert_flags(GITHUB_ACTIONS="false"),
        alert_flags(INSTAGRAM_ALERT_OUTBOX_CI_ENABLED="false"),
        alert_flags(SENDRO_INSTAGRAM_PG_CI_APPROVAL="wrong"),
    ):
        with pytest.raises(InstagramAlertOutboxDisabled):
            persist_ci_instagram_alerts(
                engine, valid_alert("quarantined_deliveries"), environ=flags,
            )
        with pytest.raises(InstagramAlertOutboxDisabled):
            read_ci_instagram_alerts(engine, environ=flags)

    # Creating SQLAlchemy engines does NOT connect to these URLs.
    invalid_urls = (
        "postgresql+psycopg://fake:fake@host.invalid:5432/sendro",
        "postgresql+psycopg://sendro_ci:fake@127.0.0.1:5432/sendro_ig_ci",
        "postgresql+psycopg://sendro_ci:fake@127.0.0.1:55439/sendro",
        "postgresql+psycopg://someone_else:fake@127.0.0.1:55439/sendro_ig_ci",
        "sqlite://",
    )
    for url in invalid_urls:
        unused_engine = create_engine(url)
        try:
            with pytest.raises(InstagramAlertOutboxDisabled):
                persist_ci_instagram_alerts(
                    unused_engine, valid_alert("failed_deliveries"),
                    environ=alert_flags(),
                )
        finally:
            unused_engine.dispose()
    assert read_rows(engine) == ()


def test_unknown_codes_extra_identifiers_and_noninteger_counts_are_rejected(ci_alerts):
    engine, key = ci_alerts
    attempts = (
        {**valid_alert("quarantined_deliveries"), "customer_id": "private-ci-guest"},
        valid_alert("unknown_code"),
        valid_alert("failed_deliveries", "failed_deliveries"),
        {**valid_alert("quarantined_deliveries"), "states": {"pending": 1}},
        {**valid_alert("quarantined_deliveries"), "due": True},
        {**valid_alert("quarantined_deliveries"), "deferred": -1},
    )
    for bad in attempts:
        with pytest.raises(InstagramAlertOutboxInvalid):
            persist_ci_instagram_alerts(engine, bad, environ=alert_flags())
    assert read_rows(engine) == ()


def test_alert_codes_commit_and_deduplicate_across_connections(ci_alerts):
    engine, key = ci_alerts
    alert = valid_alert("quarantined_deliveries", "unresolved_processing_delivery")
    assert persist_ci_instagram_alerts(engine, alert, environ=alert_flags()) == 2
    assert persist_ci_instagram_alerts(engine, alert, environ=alert_flags()) == 2

    records = read_rows(engine)
    assert [x["code"] for x in records] == [
        "quarantined_deliveries", "unresolved_processing_delivery",
    ]
    assert [x["observations"] for x in records] == [2, 2]
    assert all(
        x["snapshot"]["states"]["quarantined"] == 1 and x["snapshot"]["due"] == 0
        for x in records
    )
    serialized = json.dumps(records)
    for prohibited in ("private-ci-guest", "message_id", "ciphertext", "token"):
        assert prohibited not in serialized


def test_supervisor_alert_callback_failure_keeps_incident_record(ci_alerts):
    engine, key = ci_alerts
    store(engine, key, payload(
        "ci-alert-durable-quarantine", business="ci-alert-unregistered-business",
    ))

    def persist_then_fail(safe_alert):
        # The database commit completes BEFORE simulated notification loss.
        persist_ci_instagram_alerts(engine, safe_alert, environ=alert_flags())
        raise RuntimeError("synthetic delivery transport offline")

    with pytest.raises(InstagramPostgresSupervisorFailure, match="alert callback failed") as exc:
        run(engine, key, alert=persist_then_fail)

    assert "synthetic delivery transport offline" not in str(exc.value)
    records = read_rows(engine)
    assert [row["code"] for row in records] == ["quarantined_deliveries"]
    assert records[0]["snapshot"]["states"]["quarantined"] == 1
    assert records[0]["observations"] == 1
    with engine.connect() as db:
        counts = {
            "queue": db.execute(text("""
                SELECT COUNT(*) FROM public.sendro_channel_webhook_deliveries
                WHERE provider='instagram' AND processing_state='quarantined'
            """)).scalar_one(),
            "messages": db.execute(text(
                "SELECT COUNT(*) FROM public.sendro_channel_messages"
            )).scalar_one(),
            "conversations": db.execute(text(
                "SELECT COUNT(*) FROM public.sendro_channel_conversations"
            )).scalar_one(),
        }
    assert counts == {"queue": 1, "messages": 0, "conversations": 0}
    assert key not in json.dumps(records)
    assert "ci-alert-unregistered-business" not in json.dumps(records)


def test_outbox_never_acknowledges_or_mutates_pending_work(ci_alerts):
    engine, key = ci_alerts
    store(engine, key, payload(
        "ci-alert-still-pending", business="ig-phase2r-business",
    ))
    with engine.connect() as db:
        before = db.execute(text("""
            SELECT processing_state, attempts, payload_ciphertext
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram'
        """)).one()
    alert = valid_alert("pending_backlog")
    alert["states"]["pending"] = 1
    alert["states"]["quarantined"] = 0
    alert["due"] = 1
    persist_ci_instagram_alerts(engine, alert, environ=alert_flags())
    with engine.connect() as db:
        after = db.execute(text("""
            SELECT processing_state, attempts, payload_ciphertext
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram'
        """)).one()
    assert before == after
    assert read_rows(engine)[0]["code"] == "pending_backlog"
