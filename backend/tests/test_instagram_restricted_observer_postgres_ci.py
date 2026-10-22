"""Real PostgreSQL column-level read-only privilege proof — ephemeral CI ONLY.

The replay_engine fixture first validates the exact GitHub Actions
127.0.0.1:55439/sendro_ig_ci allowlist. Only THEN does this test create
a disposable limited SQL account. It never accesses or mutates Render.
"""
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from backend.app.instagram_restricted_observer import (
    APPROVAL_NAME, EXACT_APPROVAL, ROLE, ReadonlyObserverDenied,
    observe_instagram_queue_read_only,
)
from backend.app.instagram_ingestion import persist_instagram_webhook
from backend.app.instagram_delivery_worker import process_one_pending_instagram_delivery
from backend.app.instagram_queue_reliability import read_instagram_queue_health
from backend.tests.test_instagram_manual_migrations_postgres import (
    replay_engine, payload, store,
)


def flags(**changes):
    return {
        "GITHUB_ACTIONS": "true",
        "SENDRO_INSTAGRAM_PG_CI_APPROVAL": "ephemeral-local-service-only",
        APPROVAL_NAME: EXACT_APPROVAL,
        **changes,
    }


@pytest.fixture
def pg_observer(replay_engine):
    admin = replay_engine
    # Strict existing allowlist in replay_engine ran BEFORE any of this SQL.
    assert admin.url.host == "127.0.0.1"
    assert admin.url.port == 55439
    assert admin.url.database == "sendro_ig_ci"
    assert admin.url.username == "sendro_ci"

    with admin.begin() as db:
        db.execute(text("""
            TRUNCATE public.sendro_channel_webhook_deliveries,
                     public.sendro_channel_messages,
                     public.sendro_channel_conversations,
                     public.sendro_channel_accounts,
                     public.sendro_tenant_users,
                     public.sendro_tenants,
                     public.users RESTART IDENTITY CASCADE
        """))
        db.execute(text("""
            CREATE ROLE sendro_instagram_observer_ro
                LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                NOREPLICATION NOBYPASSRLS NOINHERIT
                PASSWORD 'disposable-observer-password-ci-only'
        """))
        db.execute(text(
            "GRANT USAGE ON SCHEMA public TO sendro_instagram_observer_ro"
        ))
        db.execute(text("""
            GRANT SELECT (
                provider, processing_state, next_attempt_at, received_at
            ) ON public.sendro_channel_webhook_deliveries
            TO sendro_instagram_observer_ro
        """))
    readonly = create_engine(
        "postgresql+psycopg://sendro_instagram_observer_ro:"
        "disposable-observer-password-ci-only@127.0.0.1:55439/sendro_ig_ci",
        connect_args={"options": "-c statement_timeout=4000 -c lock_timeout=500"},
    )
    try:
        yield admin, readonly
    finally:
        readonly.dispose()
        with admin.begin() as db:
            db.execute(text("""
                REVOKE ALL PRIVILEGES ON public.sendro_channel_webhook_deliveries
                FROM sendro_instagram_observer_ro
            """))
            db.execute(text("""
                REVOKE ALL PRIVILEGES (provider, processing_state,
                    next_attempt_at, received_at)
                ON public.sendro_channel_webhook_deliveries
                FROM sendro_instagram_observer_ro
            """))
            db.execute(text(
                "REVOKE USAGE ON SCHEMA public FROM sendro_instagram_observer_ro"
            ))
            db.execute(text("DROP ROLE sendro_instagram_observer_ro"))


def check(ro, *, now=None):
    return observe_instagram_queue_read_only(
        ro, environ=flags(), now=now,
    )


def test_only_four_delivery_metadata_columns_and_no_shared_data(pg_observer):
    admin, ro = pg_observer
    now = datetime.now(timezone.utc)
    report = check(ro, now=now)
    assert report == {
        "mode": "dedicated_postgres_readonly_aggregate",
        "states": {
            "pending": 0, "processing": 0, "processed": 0,
            "quarantined": 0, "failed": 0,
        },
        "due": 0, "deferred": 0,
        "alert_codes": (),
        "operator_notification": "not_configured",
        "heartbeat_persistence": "not_configured",
        "live_pilot_authorized": False,
        "database_writes": "none",
        "meta_access": "none",
    }
    with ro.connect() as db:
        for column in (
            "provider", "processing_state", "next_attempt_at", "received_at",
        ):
            assert db.execute(text("""
                SELECT has_column_privilege(
                    current_user, 'public.sendro_channel_webhook_deliveries',
                    :column, 'SELECT'
                )
            """), {"column": column}).scalar_one()
        for sensitive in (
            "id", "payload_ciphertext", "raw_body_sha256",
            "last_error_code", "processed_at",
        ):
            assert not db.execute(text("""
                SELECT has_column_privilege(
                    current_user, 'public.sendro_channel_webhook_deliveries',
                    :column, 'SELECT'
                )
            """), {"column": sensitive}).scalar_one()


def test_fake_delivery_quarantine_looks_identical_to_health_policy(pg_observer):
    admin, ro = pg_observer
    key = Fernet.generate_key().decode()
    now = datetime.now(timezone.utc) + timedelta(seconds=2)
    store(admin, key, payload("ci-readonly-unregistered", business="ci-unknown-business"))
    assert process_one_pending_instagram_delivery(admin, key).status == "quarantined"
    expected = read_instagram_queue_health(admin, now=now)
    report = check(ro, now=now)
    assert report["states"] == expected["states"]
    assert report["due"] == expected["due"]
    assert report["deferred"] == expected["deferred"]
    assert report["alert_codes"] == tuple(expected["alert_codes"])
    with admin.connect() as db:
        assert db.execute(text(
            "SELECT COUNT(*) FROM public.sendro_channel_messages"
        )).scalar_one() == 0
        assert db.execute(text(
            "SELECT COUNT(*) FROM public.sendro_channel_conversations"
        )).scalar_one() == 0


def test_pending_stale_and_retry_stats_without_reading_message(pg_observer):
    admin, ro = pg_observer
    key = Fernet.generate_key().decode()
    t = datetime.now(timezone.utc)
    store(admin, key, payload("ci-readonly-stale", business="ci-business"))
    with admin.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET received_at=:received WHERE provider='instagram'
        """), {"received": t - timedelta(minutes=30)})
    before = read_instagram_queue_health(admin, now=t)
    got = check(ro, now=t)
    assert got["alert_codes"] == tuple(before["alert_codes"])
    assert "stale_pending_delivery" in got["alert_codes"]
    assert got["due"] == 1
    assert got["states"]["pending"] == 1


@pytest.mark.parametrize("query", [
    "SELECT id FROM public.sendro_channel_webhook_deliveries",
    "SELECT payload_ciphertext FROM public.sendro_channel_webhook_deliveries",
    "SELECT raw_body_sha256 FROM public.sendro_channel_webhook_deliveries",
    "SELECT * FROM public.sendro_channel_webhook_deliveries",
    "SELECT * FROM public.users",
    "SELECT * FROM public.sendro_channel_messages",
    "DELETE FROM public.sendro_channel_webhook_deliveries",
    "UPDATE public.sendro_channel_webhook_deliveries SET processing_state='failed'",
])
def test_readonly_role_really_cannot_read_pii_or_change_any_rows(pg_observer, query):
    admin, ro = pg_observer
    with pytest.raises(ProgrammingError):
        with ro.begin() as db:
            db.execute(text(query))
    # Our observer still operates after a denied statement.
    assert check(ro)["states"]["pending"] == 0


def test_privilege_escalation_refused_even_on_readonly_transaction(pg_observer):
    admin, ro = pg_observer
    with admin.begin() as db:
        db.execute(text("""
            GRANT SELECT (payload_ciphertext)
            ON public.sendro_channel_webhook_deliveries
            TO sendro_instagram_observer_ro
        """))
    try:
        with pytest.raises(ReadonlyObserverDenied, match="privileges"):
            check(ro)
    finally:
        with admin.begin() as db:
            db.execute(text("""
                REVOKE SELECT (payload_ciphertext)
                ON public.sendro_channel_webhook_deliveries
                FROM sendro_instagram_observer_ro
            """))

    with admin.begin() as db:
        db.execute(text("""
            GRANT UPDATE (processing_state)
            ON public.sendro_channel_webhook_deliveries
            TO sendro_instagram_observer_ro
        """))
    try:
        with pytest.raises(ReadonlyObserverDenied, match="privileges"):
            check(ro)
    finally:
        with admin.begin() as db:
            db.execute(text("""
                REVOKE UPDATE (processing_state)
                ON public.sendro_channel_webhook_deliveries
                FROM sendro_instagram_observer_ro
            """))


def test_fail_closed_without_approval_and_wrong_engine_before_connection(pg_observer):
    admin, ro = pg_observer
    with pytest.raises(ReadonlyObserverDenied):
        observe_instagram_queue_read_only(ro, environ={})
    with pytest.raises(ReadonlyObserverDenied):
        observe_instagram_queue_read_only(ro, environ=flags(
            SENDRO_INSTAGRAM_PG_CI_APPROVAL="unapproved",
        ))
    with pytest.raises(ReadonlyObserverDenied):
        observe_instagram_queue_read_only(ro, environ=flags(
            GITHUB_ACTIONS="false",
        ))
    with pytest.raises(ReadonlyObserverDenied):
        observe_instagram_queue_read_only(admin, environ=flags())
    with pytest.raises(ReadonlyObserverDenied):
        observe_instagram_queue_read_only(ro, environ=flags(),
                                         backlog_threshold=True)
    fake = create_engine(
        "postgresql+psycopg://sendro_instagram_observer_ro:"
        "fake@render.invalid:5432/sendro"
    )
    try:
        with pytest.raises(ReadonlyObserverDenied):
            observe_instagram_queue_read_only(fake, environ=flags())
    finally:
        fake.dispose()
