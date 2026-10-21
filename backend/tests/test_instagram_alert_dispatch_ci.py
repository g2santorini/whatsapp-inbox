"""Synthetic transport-acceptance, retry, lease and human-ack proof.

All DB writes occur ONLY after the guarded disposable GitHub Actions
PostgreSQL fixture check. No email, Meta request, real recipient or
Render database is touched.
"""
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine, text

from backend.app.instagram_alert_dispatch_ci import (
    InstagramDispatchDisabled, InstagramDispatchFailure,
    acknowledge_ci_alert, attempt_ci_alert_delivery,
    claim_ci_alert_dispatch, complete_ci_alert_dispatch,
    read_ci_dispatch_status, stage_ci_alert_dispatch,
)
from backend.app.instagram_alert_outbox_ci import (
    InstagramAlertOutboxDisabled, InstagramAlertOutboxInvalid,
    persist_ci_instagram_alerts,
)
from backend.tests.test_instagram_alert_outbox_ci import (
    alert_flags, ci_alerts, valid_alert,
)
from backend.tests.test_instagram_postgres_supervision_ci import ci_supervisor
from backend.tests.test_instagram_manual_migrations_postgres import replay_engine


def dispatch_flags(**overrides):
    return alert_flags(INSTAGRAM_ALERT_DISPATCH_CI_ENABLED="true", **overrides)


@pytest.fixture
def ci_dispatch(ci_alerts):
    engine, key = ci_alerts
    # Existing ci_alerts -> ci_supervisor -> replay_engine enforces CI URL
    # before *any* connection. This table exists ONLY in GitHub Actions CI.
    with engine.begin() as db:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS public.sendro_ci_instagram_alert_dispatch (
                alert_code TEXT PRIMARY KEY
                    REFERENCES public.sendro_ci_instagram_alert_outbox(alert_code)
                    ON DELETE RESTRICT,
                target_observations BIGINT NOT NULL CHECK (target_observations > 0),
                accepted_observations BIGINT NOT NULL DEFAULT 0
                    CHECK (accepted_observations >= 0),
                acknowledged_observations BIGINT NOT NULL DEFAULT 0
                    CHECK (acknowledged_observations >= 0),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN (
                        'pending', 'leased', 'accepted', 'acknowledged', 'failed'
                    )),
                attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
                available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                lease_token VARCHAR(32),
                lease_until TIMESTAMPTZ,
                last_error_code TEXT,
                sent_at TIMESTAMPTZ,
                acknowledged_at TIMESTAMPTZ,
                CONSTRAINT ck_ci_dispatch_observations CHECK (
                    acknowledged_observations <= accepted_observations AND
                    accepted_observations <= target_observations
                )
            )
        """))
        db.execute(text("TRUNCATE public.sendro_ci_instagram_alert_dispatch"))
    return engine, key


def incident(engine, code="quarantined_deliveries"):
    assert persist_ci_instagram_alerts(
        engine, valid_alert(code), environ=alert_flags()
    ) == 1


def statuses(engine):
    return read_ci_dispatch_status(engine, environ=dispatch_flags())


def test_block_all_non_disposable_engine_before_connection(ci_dispatch):
    engine, key = ci_dispatch
    with pytest.raises(InstagramDispatchDisabled):
        stage_ci_alert_dispatch(engine, environ=alert_flags())
    with pytest.raises(InstagramAlertOutboxDisabled):
        stage_ci_alert_dispatch(engine, environ=dispatch_flags(GITHUB_ACTIONS="false"))

    for url in (
        "postgresql+psycopg://wrong:wrong@render.invalid:5432/sendro",
        "postgresql+psycopg://sendro_ci:wrong@127.0.0.1:5432/sendro_ig_ci",
        "postgresql+psycopg://someone:wrong@127.0.0.1:55439/sendro_ig_ci",
        "sqlite://",
    ):
        fake = create_engine(url)  # Does not open network connection.
        try:
            with pytest.raises(InstagramAlertOutboxDisabled):
                stage_ci_alert_dispatch(fake, environ=dispatch_flags())
            with pytest.raises(InstagramAlertOutboxDisabled):
                attempt_ci_alert_delivery(
                    fake, lambda event: True, environ=dispatch_flags()
                )
        finally:
            fake.dispose()
    assert statuses(engine) == ()


def test_acceptance_is_not_human_acknowledgment(ci_dispatch):
    engine, key = ci_dispatch
    incident(engine)
    assert stage_ci_alert_dispatch(engine, environ=dispatch_flags()) == 1
    events = []
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    assert attempt_ci_alert_delivery(
        engine, lambda event: (events.append(event), True)[-1],
        environ=dispatch_flags(), now=now,
    ) == "accepted"
    assert events == [{"code": "quarantined_deliveries", "observations": 1}]
    assert set(events[0]) == {"code", "observations"}
    [row] = statuses(engine)
    assert row["status"] == "accepted"
    assert row["accepted_observations"] == 1
    assert row["acknowledged_observations"] == 0
    assert attempt_ci_alert_delivery(
        engine, lambda _: pytest.fail("No duplicate notification"),
        environ=dispatch_flags(), now=now,
    ) == "idle"
    assert not acknowledge_ci_alert(
        engine, "quarantined_deliveries", 2,
        environ=dispatch_flags(), now=now,
    )
    assert acknowledge_ci_alert(
        engine, "quarantined_deliveries", 1,
        environ=dispatch_flags(), now=now,
    )
    assert not acknowledge_ci_alert(
        engine, "quarantined_deliveries", 1,
        environ=dispatch_flags(), now=now,
    )
    [row] = statuses(engine)
    assert row["status"] == "acknowledged"
    assert row["acknowledged_observations"] == 1
    assert key not in json.dumps(statuses(engine))


def test_transport_failure_retries_after_backoff_and_preserves_incident(ci_dispatch):
    engine, key = ci_dispatch
    incident(engine)
    stage_ci_alert_dispatch(engine, environ=dispatch_flags())
    t0 = datetime.now(timezone.utc) + timedelta(seconds=3)

    def fake_transport_failure(payload):
        raise RuntimeError("synthetic transport credentials unavailable")

    assert attempt_ci_alert_delivery(
        engine, fake_transport_failure, environ=dispatch_flags(), now=t0
    ) == "deferred"
    [row] = statuses(engine)
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["accepted_observations"] == 0
    assert attempt_ci_alert_delivery(
        engine, lambda _: pytest.fail("Must respect retry delay"),
        environ=dispatch_flags(), now=t0 + timedelta(seconds=20),
    ) == "idle"
    assert attempt_ci_alert_delivery(
        engine, lambda _: True, environ=dispatch_flags(),
        now=t0 + timedelta(seconds=31),
    ) == "accepted"
    [row] = statuses(engine)
    assert row["status"] == "accepted"
    assert row["attempts"] == 0
    assert row["acknowledged_observations"] == 0


def test_three_failed_attempts_remain_terminal_until_new_incident_version(ci_dispatch):
    engine, key = ci_dispatch
    incident(engine, code="failed_deliveries")
    stage_ci_alert_dispatch(engine, environ=dispatch_flags())
    t0 = datetime.now(timezone.utc) + timedelta(seconds=3)
    for i in range(3):
        assert attempt_ci_alert_delivery(
            engine, lambda _: False, environ=dispatch_flags(),
            now=t0 + timedelta(seconds=31 * i),
        ) == "deferred"
    [row] = statuses(engine)
    assert row["status"] == "failed"
    assert row["attempts"] == 3
    assert row["accepted_observations"] == 0
    assert attempt_ci_alert_delivery(
        engine, lambda _: pytest.fail("Failed incident requires review"),
        environ=dispatch_flags(), now=t0 + timedelta(hours=1),
    ) == "idle"
    assert stage_ci_alert_dispatch(engine, environ=dispatch_flags()) == 0
    assert statuses(engine)[0]["status"] == "failed"
    incident(engine, code="failed_deliveries")
    assert stage_ci_alert_dispatch(engine, environ=dispatch_flags()) == 1
    assert statuses(engine)[0]["status"] == "pending"
    assert statuses(engine)[0]["target_observations"] == 2


def test_crashed_dispatch_lease_expiry_and_stale_token_rejection(ci_dispatch):
    engine, key = ci_dispatch
    incident(engine)
    stage_ci_alert_dispatch(engine, environ=dispatch_flags())
    t0 = datetime.now(timezone.utc) + timedelta(seconds=3)
    first = claim_ci_alert_dispatch(engine, environ=dispatch_flags(), now=t0)
    assert first["code"] == "quarantined_deliveries"
    assert claim_ci_alert_dispatch(
        engine, environ=dispatch_flags(), now=t0 + timedelta(seconds=30)
    ) is None
    second = claim_ci_alert_dispatch(
        engine, environ=dispatch_flags(), now=t0 + timedelta(seconds=61)
    )
    assert second["lease"] != first["lease"]
    assert not complete_ci_alert_dispatch(
        engine, first, accepted=True, environ=dispatch_flags(),
        now=t0 + timedelta(seconds=62),
    )
    assert complete_ci_alert_dispatch(
        engine, second, accepted=True, environ=dispatch_flags(),
        now=t0 + timedelta(seconds=62),
    )
    assert statuses(engine)[0]["status"] == "accepted"
    assert statuses(engine)[0]["accepted_observations"] == 1


def test_later_observation_during_lease_never_silently_acknowledged(ci_dispatch):
    engine, key = ci_dispatch
    incident(engine)
    stage_ci_alert_dispatch(engine, environ=dispatch_flags())
    t0 = datetime.now(timezone.utc) + timedelta(seconds=3)
    claimed = claim_ci_alert_dispatch(engine, environ=dispatch_flags(), now=t0)
    assert claimed["observations"] == 1
    incident(engine)
    assert stage_ci_alert_dispatch(engine, environ=dispatch_flags()) == 1
    assert statuses(engine)[0]["target_observations"] == 2
    assert complete_ci_alert_dispatch(
        engine, claimed, accepted=True, environ=dispatch_flags(), now=t0,
    )
    [row] = statuses(engine)
    assert row["status"] == "pending"
    assert row["target_observations"] == 2
    assert row["accepted_observations"] == 1
    assert not acknowledge_ci_alert(
        engine, "quarantined_deliveries", 1,
        environ=dispatch_flags(), now=t0,
    )
    # Must accept and separately acknowledge the newer version.
    assert attempt_ci_alert_delivery(
        engine, lambda _: True, environ=dispatch_flags(),
        now=t0 + timedelta(seconds=1),
    ) == "accepted"
    assert acknowledge_ci_alert(
        engine, "quarantined_deliveries", 2,
        environ=dispatch_flags(), now=t0 + timedelta(seconds=1),
    )


def test_persistence_of_alert_does_not_write_or_acknowledge_any_dm(ci_dispatch):
    engine, key = ci_dispatch
    # State snapshot is synthetic and contains no real/customer payloads.
    incident(engine)
    before = None
    with engine.connect() as db:
        before = db.execute(text("""
            SELECT COUNT(*) FROM public.sendro_channel_webhook_deliveries
        """)).scalar_one()
    stage_ci_alert_dispatch(engine, environ=dispatch_flags())
    t0 = datetime.now(timezone.utc) + timedelta(seconds=3)
    assert attempt_ci_alert_delivery(
        engine, lambda event: True, environ=dispatch_flags(), now=t0
    ) == "accepted"
    with engine.connect() as db:
        after = db.execute(text("""
            SELECT COUNT(*) FROM public.sendro_channel_webhook_deliveries
        """)).scalar_one()
        messages = db.execute(text("""
            SELECT COUNT(*) FROM public.sendro_channel_messages
        """)).scalar_one()
    assert before == after == 0
    assert messages == 0
    with pytest.raises(InstagramAlertOutboxInvalid):
        acknowledge_ci_alert(
            engine, "made_up_customer_id", 1, environ=dispatch_flags(), now=t0,
        )
