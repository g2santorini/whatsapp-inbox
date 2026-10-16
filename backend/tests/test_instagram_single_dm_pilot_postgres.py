"""Attended one-DM Instagram pilot scope tests on disposable CI PostgreSQL.

All IDs, accounts, event content and keys are synthetic. replay_engine
enforces the exact ephemeral GitHub Actions PostgreSQL URL before ANY
TRUNCATE, DDL, test writes or connections. This test cannot use Render.
"""
import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from backend.app.instagram_delivery_worker import (
    InstagramPilotScope,
    process_one_pending_instagram_delivery,
)
from backend.app.instagram_pilot_operator import (
    CONFIRM_PHRASE,
    InstagramPilotDisabled,
    execute_attended_one_dm_pilot,
)
from backend.tests.test_instagram_manual_migrations_postgres import (
    replay_engine, payload, seed_business, store,
)


@pytest.fixture
def pilot_pg(replay_engine):
    # This is exclusively the hard-allowlisted ephemeral GitHub Actions DB.
    engine = replay_engine
    with engine.begin() as cx:
        cx.execute(text("""
            TRUNCATE public.sendro_channel_webhook_deliveries,
                     public.sendro_channel_messages,
                     public.sendro_channel_conversations,
                     public.sendro_channel_accounts,
                     public.sendro_tenant_users,
                     public.sendro_tenants,
                     public.users
            RESTART IDENTITY CASCADE
        """))
    tenant_a, account_a = seed_business(
        engine, tenant="pilot-ci-a", business="pilot-ci-business-a",
    )
    tenant_b, account_b = seed_business(
        engine, tenant="pilot-ci-b", business="pilot-ci-business-b",
    )
    key = Fernet.generate_key().decode("ascii")
    return engine, key, (tenant_a, account_a), (tenant_b, account_b)


def pending_ids(engine):
    with engine.connect() as cx:
        return [r[0] for r in cx.execute(text("""
            SELECT id FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram' AND processing_state = 'pending'
            ORDER BY id
        """)).all()]


def rows(engine, table):
    assert table in (
        "sendro_channel_webhook_deliveries",
        "sendro_channel_conversations",
        "sendro_channel_messages",
    )
    with engine.connect() as cx:
        return cx.execute(text(
            f"SELECT * FROM public.{table} ORDER BY id"
        )).mappings().all()


def selected(engine, *, delivery_id, tenant_and_account, business):
    tenant, account = tenant_and_account
    return InstagramPilotScope(
        delivery_id=delivery_id, tenant_id=tenant,
        channel_account_id=account, business_account_id=business,
    )


def approved_flags(scope, key):
    return {
        "INSTAGRAM_PILOT_ONE_DM_ENABLED": "true",
        "INSTAGRAM_WORKER_MANUAL_ENABLED": "true",
        "INSTAGRAM_PILOT_DELIVERY_ID": str(scope.delivery_id),
        "INSTAGRAM_PILOT_TENANT_ID": str(scope.tenant_id),
        "INSTAGRAM_PILOT_ACCOUNT_ID": str(scope.channel_account_id),
        "INSTAGRAM_PILOT_BUSINESS_ACCOUNT_ID": scope.business_account_id,
        "INSTAGRAM_WEBHOOK_ENCRYPTION_KEY": key,
    }


def test_disabled_default_rejects_before_any_db_connection(pilot_pg):
    engine, key, ta, tb = pilot_pg
    scope = selected(engine, delivery_id=1, tenant_and_account=ta, business="pilot-ci-business-a")

    class NeverTouchDatabase:
        def __getattribute__(self, name):
            raise AssertionError("DB must not be accessed while pilot is disabled")

    fake_engine = NeverTouchDatabase()
    for bad_env in (
        {},
        {"INSTAGRAM_PILOT_ONE_DM_ENABLED": "true"},
        {**approved_flags(scope, key), "INSTAGRAM_PILOT_ONE_DM_ENABLED": "false"},
        {**approved_flags(scope, key), "INSTAGRAM_WORKER_MANUAL_ENABLED": "false"},
    ):
        with pytest.raises(InstagramPilotDisabled):
            execute_attended_one_dm_pilot(
                fake_engine, scope=scope, confirmation=CONFIRM_PHRASE, environ=bad_env
            )
    assert rows(engine, "sendro_channel_webhook_deliveries") == []


def test_confirmation_and_exact_scope_env_must_match(pilot_pg):
    engine, key, ta, tb = pilot_pg
    scope = selected(engine, delivery_id=17, tenant_and_account=ta, business="pilot-ci-business-a")
    flags = approved_flags(scope, key)
    checks = [
        ("INSTAGRAM_PILOT_DELIVERY_ID", "18"),
        ("INSTAGRAM_PILOT_TENANT_ID", str(tb[0])),
        ("INSTAGRAM_PILOT_ACCOUNT_ID", str(tb[1])),
        ("INSTAGRAM_PILOT_BUSINESS_ACCOUNT_ID", "pilot-ci-business-b"),
    ]
    for name, different_value in checks:
        with pytest.raises(InstagramPilotDisabled):
            execute_attended_one_dm_pilot(
                engine, scope=scope, confirmation=CONFIRM_PHRASE,
                environ={**flags, name: different_value}
            )
    with pytest.raises(InstagramPilotDisabled):
        execute_attended_one_dm_pilot(
            engine, scope=scope, confirmation="wrong", environ=flags
        )
    assert rows(engine, "sendro_channel_webhook_deliveries") == []


def test_only_explicit_selected_id_processed_not_the_first_pending(pilot_pg):
    engine, key, ta, tb = pilot_pg
    store(engine, key, payload("ci-first-a", business="pilot-ci-business-a"))
    store(engine, key, payload("ci-second-b", business="pilot-ci-business-b"))
    before = pending_ids(engine)
    assert len(before) == 2
    scope = selected(engine, delivery_id=before[1], tenant_and_account=tb,
                     business="pilot-ci-business-b")
    result = execute_attended_one_dm_pilot(
        engine, scope=scope, confirmation=CONFIRM_PHRASE, environ=approved_flags(scope, key)
    )
    assert result == {"mode": "attended_one_dm", "status": "processed", "inserted_messages": 1}
    assert pending_ids(engine) == [before[0]]
    assert [(r["tenant_id"], r["channel_account_id"]) for r in
            rows(engine, "sendro_channel_conversations")] == [(tb[0], tb[1])]
    assert rows(engine, "sendro_channel_messages")[0]["content"] == "Synthetic message – no customer data"
    # Already-processed selection never falls back to another pending item.
    duplicate = execute_attended_one_dm_pilot(
        engine, scope=scope, confirmation=CONFIRM_PHRASE, environ=approved_flags(scope, key)
    )
    assert duplicate["status"] == "idle"
    assert pending_ids(engine) == [before[0]]
    assert len(rows(engine, "sendro_channel_messages")) == 1


def test_wrong_account_and_tenant_leave_delivery_pending_without_partial_writes(pilot_pg):
    engine, key, ta, tb = pilot_pg
    store(engine, key, payload("ci-scope-mismatch", business="pilot-ci-business-a"))
    [delivery] = pending_ids(engine)
    # Caller approves tenant B but payload references business A: no writes.
    wrong = selected(engine, delivery_id=delivery, tenant_and_account=tb,
                     business="pilot-ci-business-b")
    assert execute_attended_one_dm_pilot(
        engine, scope=wrong, confirmation=CONFIRM_PHRASE, environ=approved_flags(wrong, key)
    )["status"] == "blocked"
    assert pending_ids(engine) == [delivery]
    assert rows(engine, "sendro_channel_messages") == []
    assert rows(engine, "sendro_channel_conversations") == []
    assert rows(engine, "sendro_channel_webhook_deliveries")[0]["attempts"] == 0

    # Even if business matches, approving another tenant/account is blocked.
    wrong_tenant = selected(engine, delivery_id=delivery, tenant_and_account=tb,
                            business="pilot-ci-business-a")
    assert execute_attended_one_dm_pilot(
        engine, scope=wrong_tenant, confirmation=CONFIRM_PHRASE,
        environ=approved_flags(wrong_tenant, key)
    )["status"] == "blocked"
    assert pending_ids(engine) == [delivery]


def test_multievent_envelope_is_blocked_even_when_all_events_share_account(pilot_pg):
    engine, key, ta, tb = pilot_pg
    body = payload("ci-multi-a", business="pilot-ci-business-a")
    body["entry"][0]["messaging"].append(
        payload("ci-multi-b", business="pilot-ci-business-a")["entry"][0]["messaging"][0]
    )
    store(engine, key, body)
    [delivery] = pending_ids(engine)
    scope = selected(engine, delivery_id=delivery, tenant_and_account=ta,
                     business="pilot-ci-business-a")
    assert execute_attended_one_dm_pilot(
        engine, scope=scope, confirmation=CONFIRM_PHRASE, environ=approved_flags(scope, key)
    )["status"] == "blocked"
    assert pending_ids(engine) == [delivery]
    assert rows(engine, "sendro_channel_messages") == []
    assert rows(engine, "sendro_channel_conversations") == []


def test_unsupported_event_and_invalid_scope_fail_closed_without_write(pilot_pg):
    engine, key, ta, tb = pilot_pg
    bad = payload("ci-unsupported", business="pilot-ci-business-a")
    bad["entry"][0]["messaging"][0].pop("message")
    bad["entry"][0]["messaging"][0]["reaction"] = {"action": "react"}
    store(engine, key, bad)
    [delivery] = pending_ids(engine)
    scope = selected(engine, delivery_id=delivery, tenant_and_account=ta,
                     business="pilot-ci-business-a")
    result = execute_attended_one_dm_pilot(
        engine, scope=scope, confirmation=CONFIRM_PHRASE, environ=approved_flags(scope, key)
    )
    assert result["status"] == "blocked"
    assert pending_ids(engine) == [delivery]
    assert rows(engine, "sendro_channel_messages") == []

    invalid_scopes = [
        InstagramPilotScope(True, ta[0], ta[1], "pilot-ci-business-a"),
        InstagramPilotScope(-1, ta[0], ta[1], "pilot-ci-business-a"),
        InstagramPilotScope(delivery, 0, ta[1], "pilot-ci-business-a"),
        InstagramPilotScope(delivery, ta[0], ta[1], ""),
    ]
    for invalid in invalid_scopes:
        with pytest.raises(ValueError, match="Invalid Instagram pilot selection"):
            process_one_pending_instagram_delivery(
                engine, key, pilot_scope=invalid
            )
    assert pending_ids(engine) == [delivery]


def test_missing_and_deferred_exact_id_never_fallback_to_another(pilot_pg):
    engine, key, ta, tb = pilot_pg
    store(engine, key, payload("ci-deferred", business="pilot-ci-business-a"))
    store(engine, key, payload("ci-other", business="pilot-ci-business-b"))
    first, second = pending_ids(engine)
    with engine.begin() as cx:
        cx.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET next_attempt_at = CURRENT_TIMESTAMP + INTERVAL '20 minutes'
            WHERE id = :id
        """), {"id": first})
    scope = selected(engine, delivery_id=first, tenant_and_account=ta,
                     business="pilot-ci-business-a")
    assert execute_attended_one_dm_pilot(
        engine, scope=scope, confirmation=CONFIRM_PHRASE, environ=approved_flags(scope, key)
    )["status"] == "idle"
    assert len(rows(engine, "sendro_channel_messages")) == 0
    assert pending_ids(engine) == [first, second]

    not_found = selected(engine, delivery_id=999_999, tenant_and_account=ta,
                         business="pilot-ci-business-a")
    assert execute_attended_one_dm_pilot(
        engine, scope=not_found, confirmation=CONFIRM_PHRASE, environ=approved_flags(not_found, key)
    )["status"] == "idle"
    assert pending_ids(engine) == [first, second]


def test_locked_exact_delivery_skips_other_ready_deliveries(pilot_pg):
    engine, key, ta, tb = pilot_pg
    store(engine, key, payload("ci-lock-first", business="pilot-ci-business-a"))
    store(engine, key, payload("ci-lock-other", business="pilot-ci-business-b"))
    first, second = pending_ids(engine)
    scope = selected(engine, delivery_id=first, tenant_and_account=ta,
                     business="pilot-ci-business-a")
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("""
                SELECT id FROM public.sendro_channel_webhook_deliveries
                WHERE id = :id FOR UPDATE
            """), {"id": first})
            result = execute_attended_one_dm_pilot(
                engine, scope=scope, confirmation=CONFIRM_PHRASE,
                environ=approved_flags(scope, key)
            )
            assert result["status"] == "idle"
            assert pending_ids(engine) == [first, second]
            assert rows(engine, "sendro_channel_messages") == []
        finally:
            tx.rollback()
