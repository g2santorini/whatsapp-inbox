"""Synthetic continuous-episode dedupe and privileged audited ack tests.

Every fixture writes ONLY to the ephemeral CI PostgreSQL service after the
existing strict URL/CI-flag verifier. No real operator, notification, Meta
subscription, Render DB or customer records are accessed.
"""
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine, text

from backend.app.instagram_alert_episode_ci import (
    InstagramEpisodeDisabled, InstagramEpisodeFailure,
    observe_ci_instagram_episodes, read_ci_episode_status,
)
from backend.app.instagram_alert_staff_ack_ci import (
    CONFIRM_ACK, InstagramAckDisabled, InstagramAckDenied,
    acknowledge_ci_incident_as_responder,
)
from backend.app.instagram_alert_dispatch_ci import (
    attempt_ci_alert_delivery, read_ci_dispatch_status,
)
from backend.app.instagram_alert_outbox_ci import InstagramAlertOutboxDisabled
from backend.app.instagram_delivery_worker import process_one_pending_instagram_delivery
from backend.tests.test_instagram_alert_dispatch_ci import (
    ci_dispatch, dispatch_flags,
)
from backend.tests.test_instagram_alert_outbox_ci import ci_alerts
from backend.tests.test_instagram_postgres_supervision_ci import ci_supervisor
from backend.tests.test_instagram_manual_migrations_postgres import (
    replay_engine, payload, store,
)


def flags(**overrides):
    requested = {
        "INSTAGRAM_ALERT_EPISODE_CI_ENABLED": "true",
        "INSTAGRAM_ALERT_ACK_CI_ENABLED": "true",
    }
    requested.update(overrides)
    return dispatch_flags(**requested)


@pytest.fixture
def episode_db(ci_dispatch):
    engine, key = ci_dispatch
    # Exactly allowlisted PostgreSQL, via ci_dispatch -> ci_alerts ->
    # ci_supervisor -> replay_engine before any of this fixture's SQL.
    with engine.begin() as db:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS public.sendro_ci_instagram_alert_episodes (
                alert_code TEXT PRIMARY KEY,
                episode_number BIGINT NOT NULL CHECK (episode_number > 0),
                is_active BOOLEAN NOT NULL,
                observation_count BIGINT NOT NULL CHECK (observation_count > 0),
                first_seen_at TIMESTAMPTZ NOT NULL,
                last_seen_at TIMESTAMPTZ NOT NULL,
                resolved_at TIMESTAMPTZ
            )
        """))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS public.sendro_ci_instagram_incident_responders (
                user_id BIGINT PRIMARY KEY,
                scope TEXT NOT NULL CHECK (scope IN ('global','tenant')),
                responder_role TEXT NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT FALSE,
                can_acknowledge BOOLEAN NOT NULL DEFAULT FALSE,
                approved_until TIMESTAMPTZ NOT NULL
            )
        """))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS public.sendro_ci_instagram_ack_audit (
                alert_code TEXT NOT NULL,
                episode_number BIGINT NOT NULL,
                actor_user_id BIGINT NOT NULL,
                reviewed_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (alert_code, episode_number)
            )
        """))
        db.execute(text("""
            TRUNCATE public.sendro_ci_instagram_ack_audit,
                     public.sendro_ci_instagram_incident_responders,
                     public.sendro_ci_instagram_alert_episodes
        """))
    return engine, key


def t0():
    return datetime.now(timezone.utc) + timedelta(seconds=5)


def observation(engine, time_):
    return observe_ci_instagram_episodes(
        engine, environ=flags(), now=time_,
    )


def episodes(engine):
    return read_ci_episode_status(engine, environ=flags())


def dispatches(engine):
    return read_ci_dispatch_status(engine, environ=flags())


def quarantine(engine, key, mid):
    store(engine, key, payload(mid, business="nonexistent-ci-business"))
    result = process_one_pending_instagram_delivery(engine, key)
    assert result.status == "quarantined"


def grant(engine, uid, now, *, role="incident_responder",
          enabled=True, scope="global", can_ack=True, expiration=3600):
    with engine.begin() as db:
        db.execute(text("""
            INSERT INTO public.sendro_ci_instagram_incident_responders (
                user_id, scope, responder_role, is_active,
                can_acknowledge, approved_until
            ) VALUES (
                :uid, :scope, :role, :enabled, :can_ack, :expiry
            )
        """), {
            "uid": uid, "scope": scope, "role": role, "enabled": enabled,
            "can_ack": can_ack, "expiry": now + timedelta(seconds=expiration),
        })


def acknowledge(engine, code, episode, uid, time_,
                *, confirmation=CONFIRM_ACK, env=None):
    return acknowledge_ci_incident_as_responder(
        engine, code, episode, actor_user_id=uid,
        confirmation=confirmation,
        environ=flags() if env is None else env, now=time_,
    )


def audit_rows(engine):
    with engine.connect() as db:
        return db.execute(text("""
            SELECT alert_code, episode_number, actor_user_id
            FROM public.sendro_ci_instagram_ack_audit
            ORDER BY alert_code, episode_number
        """)).mappings().all()


def test_persistent_alert_creates_one_episode_not_one_email_per_sample(episode_db):
    engine, key = episode_db
    now = t0()
    quarantine(engine, key, "ci-persistent-quarantine")
    assert observation(engine, now) == {
        "active_codes": ("quarantined_deliveries",),
        "new_episodes": 1, "resolved": 0,
    }
    for n in range(1, 12):
        sampled = observation(engine, now + timedelta(seconds=n))
        assert sampled["new_episodes"] == 0
        assert sampled["resolved"] == 0
    [incident] = episodes(engine)
    assert incident["episode_number"] == 1
    assert incident["is_active"] is True
    assert incident["observation_count"] == 12
    [pending] = dispatches(engine)
    assert pending["target_observations"] == 1
    assert pending["status"] == "pending"

    delivered = []
    assert attempt_ci_alert_delivery(
        engine, lambda event: (delivered.append(event), True)[-1],
        environ=flags(), now=now + timedelta(seconds=13),
    ) == "accepted"
    assert delivered == [{"code": "quarantined_deliveries", "observations": 1}]
    grant(engine, 101, now)
    assert acknowledge(engine, "quarantined_deliveries", 1, 101,
                       now + timedelta(seconds=14))
    assert audit_rows(engine)[0]["actor_user_id"] == 101

    for n in range(15, 35):
        assert observation(engine, now + timedelta(seconds=n))["new_episodes"] == 0
    assert attempt_ci_alert_delivery(
        engine, lambda _: pytest.fail("A persistent alert must not resend"),
        environ=flags(), now=now + timedelta(seconds=40),
    ) == "idle"
    assert dispatches(engine)[0]["status"] == "acknowledged"
    assert len(audit_rows(engine)) == 1


def test_episode_resolves_then_recurrence_requires_new_ack_version(episode_db):
    engine, key = episode_db
    now = t0()
    quarantine(engine, key, "ci-first-episode")
    assert observation(engine, now)["new_episodes"] == 1
    assert attempt_ci_alert_delivery(
        engine, lambda _: True, environ=flags(), now=now,
    ) == "accepted"
    grant(engine, 102, now)
    assert acknowledge(engine, "quarantined_deliveries", 1, 102, now)

    # DISPOSABLE CI ONLY: emulate incident resolution by changing the fake
    # delivery state. No live recovery or queue mutation is exposed.
    with engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET processing_state='processed'
            WHERE provider='instagram' AND processing_state='quarantined'
        """))
    assert observation(engine, now + timedelta(seconds=10)) == {
        "active_codes": (), "new_episodes": 0, "resolved": 1,
    }
    assert not episodes(engine)[0]["is_active"]

    quarantine(engine, key, "ci-second-episode")
    assert observation(engine, now + timedelta(seconds=20))["new_episodes"] == 1
    [episode] = episodes(engine)
    assert episode["episode_number"] == 2
    assert episode["observation_count"] == 1
    [current] = dispatches(engine)
    assert current["target_observations"] == 2
    assert current["acknowledged_observations"] == 1
    assert current["status"] == "pending"
    with pytest.raises(InstagramAckDenied):
        acknowledge(engine, "quarantined_deliveries", 1, 102,
                    now + timedelta(seconds=21))
    assert len(audit_rows(engine)) == 1
    assert attempt_ci_alert_delivery(
        engine, lambda _: True, environ=flags(),
        now=now + timedelta(seconds=22),
    ) == "accepted"
    assert acknowledge(engine, "quarantined_deliveries", 2, 102,
                       now + timedelta(seconds=23))
    assert [a["episode_number"] for a in audit_rows(engine)] == [1, 2]


def test_no_auth_no_approved_role_no_valid_window_cannot_ack(episode_db):
    engine, key = episode_db
    now = t0()
    quarantine(engine, key, "ci-not-everyone-can-ack")
    observation(engine, now)
    assert attempt_ci_alert_delivery(
        engine, lambda _: True, environ=flags(), now=now,
    ) == "accepted"

    grant(engine, 200, now, role="operator")
    grant(engine, 201, now, scope="tenant")
    grant(engine, 202, now, enabled=False)
    grant(engine, 203, now, can_ack=False)
    grant(engine, 204, now, expiration=-1)
    for uid in (200, 201, 202, 203, 204, 999):
        with pytest.raises(InstagramAckDenied):
            acknowledge(engine, "quarantined_deliveries", 1, uid, now)
    assert len(audit_rows(engine)) == 0
    assert dispatches(engine)[0]["status"] == "accepted"

    grant(engine, 205, now, role="incident_admin", expiration=30)
    with pytest.raises(InstagramAckDenied):
        acknowledge(engine, "quarantined_deliveries", 1, 205,
                    now + timedelta(seconds=31))
    with pytest.raises(InstagramAckDenied):
        acknowledge(engine, "quarantined_deliveries", 1, 205,
                    now, confirmation="clicked accidentally")
    with pytest.raises(InstagramAckDenied):
        acknowledge(engine, "quarantined_deliveries", 2, 205, now)
    assert len(audit_rows(engine)) == 0

    assert acknowledge(engine, "quarantined_deliveries", 1, 205, now)
    with pytest.raises(InstagramAckDenied):
        acknowledge(engine, "quarantined_deliveries", 1, 205, now)
    assert len(audit_rows(engine)) == 1
    assert dispatches(engine)[0]["status"] == "acknowledged"


def test_ack_audit_outage_preserves_unacknowledged_incident(episode_db):
    engine, key = episode_db
    now = t0()
    quarantine(engine, key, "ci-ack-atomic")
    observation(engine, now)
    assert attempt_ci_alert_delivery(
        engine, lambda _: True, environ=flags(), now=now,
    ) == "accepted"
    grant(engine, 206, now)
    # DISPOSABLE CI ONLY: simulate unavailable append-only audit.
    with engine.begin() as db:
        db.execute(text("DROP TABLE public.sendro_ci_instagram_ack_audit"))
    with pytest.raises(InstagramAckDenied, match="unavailable"):
        acknowledge(engine, "quarantined_deliveries", 1, 206, now)
    [record] = dispatches(engine)
    assert record["status"] == "accepted"
    assert record["acknowledged_observations"] == 0


def test_ephemeral_db_identity_and_separate_ack_gate_precede_any_sql(episode_db):
    engine, key = episode_db
    with pytest.raises(InstagramEpisodeDisabled):
        observe_ci_instagram_episodes(
            engine, environ=dispatch_flags(),
        )
    with pytest.raises(InstagramAckDisabled):
        acknowledge_ci_incident_as_responder(
            engine, "quarantined_deliveries", 1,
            actor_user_id=10, confirmation=CONFIRM_ACK,
            environ=flags(INSTAGRAM_ALERT_ACK_CI_ENABLED="false"),
        )
    fake = create_engine("postgresql+psycopg://fake:fake@render.invalid:5432/sendro")
    try:
        with pytest.raises(InstagramAlertOutboxDisabled):
            observe_ci_instagram_episodes(fake, environ=flags())
        with pytest.raises(InstagramAlertOutboxDisabled):
            acknowledge_ci_incident_as_responder(
                fake, "quarantined_deliveries", 1,
                actor_user_id=10, confirmation=CONFIRM_ACK, environ=flags(),
            )
    finally:
        fake.dispose()
    assert episodes(engine) == ()
    assert dispatches(engine) == ()


def test_atomic_staging_rolls_back_if_dispatch_storage_missing(episode_db):
    engine, key = episode_db
    now = t0()
    quarantine(engine, key, "ci-dispatch-storage-missing")
    # Only a CI fixture table is dropped; never a Render table.
    with engine.begin() as db:
        db.execute(text("DROP TABLE public.sendro_ci_instagram_alert_dispatch"))
    with pytest.raises(InstagramEpisodeFailure):
        observation(engine, now)
    assert episodes(engine) == ()  # no half-published episode
    with engine.connect() as db:
        remaining = db.execute(text("""
            SELECT processing_state, attempts
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider='instagram'
        """)).one()
    assert remaining.processing_state == "quarantined"
    assert remaining.attempts == 1
