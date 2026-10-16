"""Phase 2R: *ephemeral GitHub Actions PostgreSQL only* supervisor tests.

Uses original six Instagram migrations and synthetic payloads. This fixture
can TRUNCATE/CREATE TRIGGER only after Phase 2L/2M's strict allowlist has
established the CI database. Never run against Render or real customers.
"""
import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

from backend.app.instagram_postgres_supervision import (
    InstagramPostgresSupervisorDisabled,
    InstagramPostgresSupervisorFailure,
    run_ephemeral_postgres_supervised_batch,
)
from backend.tests.test_instagram_manual_migrations_postgres import (
    payload,
    replay_engine,
    seed_business,
    store,
)


def ci_flags(**overrides):
    return {
        "GITHUB_ACTIONS": "true",
        "SENDRO_INSTAGRAM_PG_CI_APPROVAL": "ephemeral-local-service-only",
        "INSTAGRAM_PG_SUPERVISION_CI_ENABLED": "true",
        **overrides,
    }


def run(engine, key, *, alert=None, flags=None, max_deliveries=3):
    return run_ephemeral_postgres_supervised_batch(
        engine, key, environ=flags if flags is not None else ci_flags(),
        max_deliveries=max_deliveries,
        on_alert=alert if alert is not None else lambda event: None,
    )


def queue_state(engine):
    with engine.connect() as db:
        return db.execute(text("""
            SELECT processing_state, attempts, last_error_code
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram' ORDER BY id
        """)).mappings().all()


def row_count(engine, table):
    assert table in {
        "sendro_channel_messages",
        "sendro_channel_conversations",
        "sendro_channel_webhook_deliveries",
    }
    with engine.connect() as db:
        return db.execute(text(f"SELECT COUNT(*) FROM public.{table}")).scalar_one()


@pytest.fixture
def ci_supervisor(replay_engine):
    engine = replay_engine
    with engine.begin() as db:
        db.execute(text("""
            TRUNCATE public.sendro_channel_webhook_deliveries,
                     public.sendro_channel_messages,
                     public.sendro_channel_conversations,
                     public.sendro_channel_accounts,
                     public.sendro_tenant_users,
                     public.sendro_tenants,
                     public.users
            RESTART IDENTITY CASCADE
        """))
    seed_business(
        engine, tenant="phase2r-tenant-a", business="ig-phase2r-business",
    )
    return engine, Fernet.generate_key().decode("ascii")


def test_no_live_runner_gate_defaults_to_denied(ci_supervisor):
    engine, key = ci_supervisor
    for flags in (
        {}, {"GITHUB_ACTIONS": "true"},
        ci_flags(INSTAGRAM_PG_SUPERVISION_CI_ENABLED="false"),
        ci_flags(GITHUB_ACTIONS="false"),
        ci_flags(SENDRO_INSTAGRAM_PG_CI_APPROVAL=""),
    ):
        with pytest.raises(InstagramPostgresSupervisorDisabled):
            run(engine, key, flags=flags)
    assert row_count(engine, "sendro_channel_webhook_deliveries") == 0


def test_refuse_render_urls_sqlite_unsafe_limits_and_missing_alert(ci_supervisor):
    engine, key = ci_supervisor
    # create_engine here does not connect to any host.
    invalid_engines = [
        create_engine("postgresql+psycopg://fake:fake@render.invalid:5432/sendro"),
        create_engine("postgresql+psycopg://fake:fake@127.0.0.1:5432/sendro_ig_ci"),
        create_engine("postgresql+psycopg://fake:fake@127.0.0.1:55439/sendro"),
        create_engine("postgresql+psycopg://fake:fake@127.0.0.1:55439/sendro_ig_ci"),
        create_engine("sqlite://"),
    ]
    try:
        for fake_engine in invalid_engines:
            with pytest.raises(InstagramPostgresSupervisorDisabled):
                run(fake_engine, key)
    finally:
        for fake_engine in invalid_engines:
            fake_engine.dispose()

    for limit in (0, 6, -1, True, 2.5, None):
        with pytest.raises(InstagramPostgresSupervisorDisabled):
            run(engine, key, max_deliveries=limit)
    with pytest.raises(InstagramPostgresSupervisorDisabled):
        run_ephemeral_postgres_supervised_batch(
            engine, key, environ=ci_flags(), on_alert=None,
        )
    assert row_count(engine, "sendro_channel_webhook_deliveries") == 0


def test_batch_is_bounded_and_idempotent_on_real_migration_schema(ci_supervisor):
    engine, key = ci_supervisor
    store(engine, key, payload("ci-p2r-1", business="ig-phase2r-business"))
    store(engine, key, payload("ci-p2r-2", business="ig-phase2r-business"))
    alerts = []
    first = run(engine, key, max_deliveries=1, alert=alerts.append)
    assert first == {
        "processed": 1, "quarantined": 0, "deferred": 0,
        "failed": 0, "messages": 1, "alerts": (),
    }
    assert [row["processing_state"] for row in queue_state(engine)] == [
        "processed", "pending",
    ]
    second = run(engine, key, max_deliveries=2, alert=alerts.append)
    assert second["processed"] == 1
    assert second["messages"] == 1
    assert row_count(engine, "sendro_channel_conversations") == 1
    assert row_count(engine, "sendro_channel_messages") == 2
    with engine.connect() as db:
        unread = db.execute(text("""
            SELECT unread_count FROM public.sendro_channel_conversations
        """)).scalar_one()
    assert unread == 2

    # Same provider message under a distinct signed envelope is not duplicated.
    duplicate = payload("ci-p2r-1", business="ig-phase2r-business")
    duplicate["entry"][0]["time"] = 1792000000555
    store(engine, key, duplicate)
    third = run(engine, key, alert=alerts.append)
    assert third["processed"] == 1 and third["messages"] == 0
    assert row_count(engine, "sendro_channel_messages") == 2
    assert alerts == []
    for secret in (key, "Synthetic message", "ig-phase2r-business"):
        assert secret not in json.dumps([first, second, third])


def test_quarantined_delivery_emits_only_redacted_status_alert(ci_supervisor):
    engine, key = ci_supervisor
    store(engine, key, payload("ci-p2r-unregistered", business="unknown-business"))
    events = []
    result = run(engine, key, alert=events.append)
    assert result["quarantined"] == 1 and result["messages"] == 0
    assert "quarantined_deliveries" in result["alerts"]
    assert len(events) == 1
    assert set(events[0]) == {"codes", "states", "due", "deferred"}
    assert events[0]["states"]["quarantined"] == 1
    assert queue_state(engine)[0]["last_error_code"] == "unregistered_business_account"
    assert row_count(engine, "sendro_channel_conversations") == 0
    assert "unknown-business" not in json.dumps(events)


def test_postgresql_serialization_rollback_and_deferred_retry(ci_supervisor):
    engine, key = ci_supervisor
    store(engine, key, payload("ci-p2r-retry", business="ig-phase2r-business"))
    with engine.begin() as db:
        db.execute(text("""
            CREATE FUNCTION public.ci_p2r_abort_insert()
            RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'fabricated serialization issue'
                    USING ERRCODE = '40001';
            END;
            $$
        """))
        db.execute(text("""
            CREATE TRIGGER ci_p2r_abort_insert
            AFTER INSERT ON public.sendro_channel_messages
            FOR EACH ROW EXECUTE FUNCTION public.ci_p2r_abort_insert()
        """))
    try:
        deferred = run(engine, key, max_deliveries=1)
    finally:
        with engine.begin() as db:
            db.execute(text("""
                DROP TRIGGER ci_p2r_abort_insert
                ON public.sendro_channel_messages
            """))
            db.execute(text("DROP FUNCTION public.ci_p2r_abort_insert()"))

    assert deferred["deferred"] == 1 and deferred["messages"] == 0
    assert row_count(engine, "sendro_channel_messages") == 0
    assert row_count(engine, "sendro_channel_conversations") == 0
    assert queue_state(engine)[0]["attempts"] == 1
    assert queue_state(engine)[0]["processing_state"] == "pending"
    assert run(engine, key)["processed"] == 0  # deferred until due
    with engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET next_attempt_at = NULL WHERE provider = 'instagram'
        """))
    recovered = run(engine, key)
    assert recovered["processed"] == 1 and recovered["messages"] == 1
    assert queue_state(engine)[0]["processing_state"] == "processed"
    assert row_count(engine, "sendro_channel_messages") == 1


def test_failed_alert_callback_stops_after_durable_quarantine(ci_supervisor):
    engine, key = ci_supervisor
    store(engine, key, payload("ci-p2r-quarantine", business="not-enrolled"))
    def broken_callback(event):
        raise RuntimeError("synthetic secure alert transport unavailable")
    with pytest.raises(
        InstagramPostgresSupervisorFailure, match="alert callback failed"
    ) as e:
        run(engine, key, alert=broken_callback)
    assert "synthetic secure alert" not in str(e.value)
    assert queue_state(engine)[0]["processing_state"] == "quarantined"
    assert row_count(engine, "sendro_channel_messages") == 0


def test_wrong_decryption_key_halts_without_ack_or_partial_write(ci_supervisor):
    engine, key = ci_supervisor
    store(engine, key, payload("ci-p2r-wrong-key", business="ig-phase2r-business"))
    other_key = Fernet.generate_key().decode("ascii")
    with pytest.raises(InstagramPostgresSupervisorFailure, match="operator review") as e:
        run(engine, other_key)
    assert key not in str(e.value) and other_key not in str(e.value)
    assert queue_state(engine)[0]["processing_state"] == "pending"
    assert queue_state(engine)[0]["attempts"] == 0
    assert row_count(engine, "sendro_channel_messages") == 0


def test_empty_queue_returns_zero_counts(ci_supervisor):
    engine, key = ci_supervisor
    assert run(engine, key) == {
        "processed": 0, "quarantined": 0, "deferred": 0,
        "failed": 0, "messages": 0, "alerts": (),
    }
