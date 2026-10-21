"""CI-only exact failed Instagram delivery recovery: synthetic Postgres proof.

Uses a disposable GitHub Actions Postgres 16 database only. Fixture guard
checks expected host/user/db/CI approval BEFORE any test SQL/DDL. Never
run against the shared Render staging+production database or live Meta.
"""
import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

from backend.app.instagram_failed_recovery_ci import (
    CONFIRM_RECOVERY, InstagramRecoveryBlocked, InstagramRecoveryDisabled,
    recover_one_failed_instagram_ci,
)
from backend.app.instagram_alert_outbox_ci import InstagramAlertOutboxDisabled
from backend.app.instagram_delivery_worker import (
    InstagramPilotScope, process_one_pending_instagram_delivery,
)
from backend.tests.test_instagram_manual_migrations_postgres import (
    payload, replay_engine, seed_business, store,
)


def recovery_flags(**overrides):
    return {
        "GITHUB_ACTIONS": "true",
        "SENDRO_INSTAGRAM_PG_CI_APPROVAL": "ephemeral-local-service-only",
        "INSTAGRAM_ALERT_OUTBOX_CI_ENABLED": "true",
        "INSTAGRAM_MANUAL_RECOVERY_CI_ENABLED": "true",
        **overrides,
    }


@pytest.fixture
def ci_recovery(replay_engine):
    engine = replay_engine
    # Only the exact hard-allowlisted ephemeral CI fixture can reach here.
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
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS public.sendro_ci_instagram_recovery_audit (
                delivery_id BIGINT PRIMARY KEY,
                tenant_id BIGINT NOT NULL,
                channel_account_id BIGINT NOT NULL,
                old_attempts INTEGER NOT NULL,
                old_error_code TEXT NOT NULL,
                raw_body_sha256 CHAR(64) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.execute(text("TRUNCATE public.sendro_ci_instagram_recovery_audit"))
    a = seed_business(engine, tenant="recover-ci-a", business="recover-ci-business-a")
    b = seed_business(engine, tenant="recover-ci-b", business="recover-ci-business-b")
    return engine, Fernet.generate_key().decode("ascii"), a, b


def row(engine, delivery_id):
    with engine.connect() as db:
        return db.execute(text("""
            SELECT id, provider, raw_body_sha256, payload_ciphertext,
                   processing_state, attempts, last_error_code,
                   next_attempt_at, processed_at
            FROM public.sendro_channel_webhook_deliveries WHERE id = :id
        """), {"id": delivery_id}).mappings().one()


def rows(engine, table):
    assert table in (
        "sendro_ci_instagram_recovery_audit",
        "sendro_channel_messages",
        "sendro_channel_conversations",
    )
    with engine.connect() as db:
        return db.execute(text(f"SELECT * FROM public.{table} ORDER BY id")
                          if table != "sendro_ci_instagram_recovery_audit" else
                          text("SELECT * FROM public.sendro_ci_instagram_recovery_audit ORDER BY delivery_id")
                         ).mappings().all()


def make_failed(engine, key, message_id, *, business):
    store(engine, key, payload(message_id, business=business))
    with engine.begin() as db:
        identifier = db.execute(text("""
            SELECT id FROM public.sendro_channel_webhook_deliveries
            WHERE provider='instagram' ORDER BY id DESC LIMIT 1
        """)).scalar_one()
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET processing_state='failed',
                attempts=5,
                processed_at=CURRENT_TIMESTAMP,
                last_error_code='transient_processing_failure'
            WHERE id=:id AND processing_state='pending'
        """), {"id": identifier})
    return identifier


def scope_for(id_, account, business):
    tenant_id, account_id = account
    return InstagramPilotScope(
        delivery_id=id_, tenant_id=tenant_id, channel_account_id=account_id,
        business_account_id=business,
    )


def recover(engine, key, scope, *, digest=None, attempts=5,
            flags=None, confirmation=CONFIRM_RECOVERY):
    expected_digest = digest if digest is not None else row(
        engine, scope.delivery_id
    )["raw_body_sha256"].strip()
    return recover_one_failed_instagram_ci(
        engine, scope=scope, expected_digest=expected_digest,
        expected_attempts=attempts, encryption_key=key,
        environ=flags if flags is not None else recovery_flags(),
        confirmation=confirmation,
    )


def test_recover_only_one_exact_tenant_then_process_scoped_worker_once(ci_recovery):
    engine, key, a, b = ci_recovery
    ida = make_failed(engine, key, "recover-a", business="recover-ci-business-a")
    idb = make_failed(engine, key, "recover-b", business="recover-ci-business-b")
    previous_a = row(engine, ida)
    previous_b = row(engine, idb)

    scope = scope_for(idb, b, "recover-ci-business-b")
    assert recover(engine, key, scope) == {
        "state": "pending", "audit_written": True,
    }
    after_b = row(engine, idb)
    assert after_b["processing_state"] == "pending"
    assert after_b["attempts"] == 5  # NEVER silently reset exhausted evidence.
    assert after_b["payload_ciphertext"] == previous_b["payload_ciphertext"]
    assert after_b["raw_body_sha256"] == previous_b["raw_body_sha256"]
    assert after_b["last_error_code"] == "manual_ci_recovery_once"
    assert row(engine, ida) == previous_a  # no fallback to another company

    [audit] = rows(engine, "sendro_ci_instagram_recovery_audit")
    assert audit["delivery_id"] == idb
    assert audit["tenant_id"] == b[0]
    assert audit["channel_account_id"] == b[1]
    assert audit["old_attempts"] == 5
    assert audit["old_error_code"] == "transient_processing_failure"

    # The recovery function does NOT run the worker. Explicit scoped worker
    # processes only this requeued synthetic event in a separate test step.
    outcome = process_one_pending_instagram_delivery(engine, key, pilot_scope=scope)
    assert outcome.status == "processed" and outcome.inserted_messages == 1
    assert process_one_pending_instagram_delivery(
        engine, key, pilot_scope=scope
    ).status == "idle"
    assert row(engine, ida) == previous_a
    assert row(engine, idb)["attempts"] == 6
    messages = rows(engine, "sendro_channel_messages")
    assert len(messages) == 1
    assert messages[0]["tenant_id"] == b[0]
    assert messages[0]["channel_account_id"] == b[1]
    assert rows(engine, "sendro_channel_conversations")[0]["unread_count"] == 1
    assert len(rows(engine, "sendro_ci_instagram_recovery_audit")) == 1
    with pytest.raises(InstagramRecoveryBlocked):
        recover(engine, key, scope)


def test_bad_key_digest_scope_and_attempts_fail_before_queue_mutation(ci_recovery):
    engine, key, a, b = ci_recovery
    target = make_failed(engine, key, "recover-scoped", business="recover-ci-business-a")
    valid = scope_for(target, a, "recover-ci-business-a")
    wrongs = [
        (scope_for(target, b, "recover-ci-business-a"), key, None, 5),
        (scope_for(target, a, "recover-ci-business-b"), key, None, 5),
        (valid, Fernet.generate_key().decode("ascii"), None, 5),
        (valid, key, "a" * 64, 5),
        (valid, key, None, 6),
    ]
    before = row(engine, target)
    for scope, test_key, digest, attempts in wrongs:
        with pytest.raises(InstagramRecoveryBlocked):
            recover(engine, test_key, scope, digest=digest, attempts=attempts)
        assert row(engine, target) == before
        assert rows(engine, "sendro_ci_instagram_recovery_audit") == []

    # Even correct evidence is rejected if the business is now disabled.
    with engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_channel_accounts SET status='disabled'
            WHERE id=:account
        """), {"account": a[1]})
    with pytest.raises(InstagramRecoveryBlocked):
        recover(engine, key, valid)
    assert row(engine, target) == before
    assert rows(engine, "sendro_ci_instagram_recovery_audit") == []


def test_never_requeue_quarantined_pending_or_nontransient_failed(ci_recovery):
    engine, key, a, b = ci_recovery
    target = make_failed(engine, key, "recover-unsupported", business="recover-ci-business-a")
    scope = scope_for(target, a, "recover-ci-business-a")
    for state, reason in (
        ("quarantined", "unsupported_or_invalid_event"),
        ("failed", "unsupported_or_invalid_event"),
        ("pending", "transient_processing_failure"),
        ("failed", "transient_processing_failure"),
    ):
        with engine.begin() as db:
            db.execute(text("""
                UPDATE public.sendro_channel_webhook_deliveries
                SET processing_state=:state, last_error_code=:reason,
                    attempts=:count WHERE id=:id
            """), {"state": state, "reason": reason, "count": 4
                    if state == "failed" and reason == "transient_processing_failure" else 5,
                    "id": target})
        previous = row(engine, target)
        with pytest.raises(InstagramRecoveryBlocked):
            recover(engine, key, scope)
        assert row(engine, target) == previous
        assert rows(engine, "sendro_ci_instagram_recovery_audit") == []


def test_multi_event_or_outbound_echo_is_not_eligible(ci_recovery):
    engine, key, a, b = ci_recovery
    cases = []
    multiple = payload("multi-1", business="recover-ci-business-a")
    multiple["entry"][0]["messaging"].append(
        payload("multi-2", business="recover-ci-business-a")["entry"][0]["messaging"][0]
    )
    cases.append(multiple)
    echoed = payload("outbound-1", business="recover-ci-business-a")
    msg = echoed["entry"][0]["messaging"][0]
    msg["sender"], msg["recipient"] = msg["recipient"], msg["sender"]
    msg["message"]["is_echo"] = True
    cases.append(echoed)
    for i, body in enumerate(cases):
        store(engine, key, body)
        with engine.begin() as db:
            id_ = db.execute(text("""
                SELECT id FROM public.sendro_channel_webhook_deliveries
                ORDER BY id DESC LIMIT 1
            """)).scalar_one()
            db.execute(text("""
                UPDATE public.sendro_channel_webhook_deliveries
                SET processing_state='failed', attempts=5,
                    last_error_code='transient_processing_failure'
                WHERE id=:id
            """), {"id": id_})
        scope = scope_for(id_, a, "recover-ci-business-a")
        previous = row(engine, id_)
        with pytest.raises(InstagramRecoveryBlocked):
            recover(engine, key, scope)
        assert row(engine, id_) == previous
    assert rows(engine, "sendro_ci_instagram_recovery_audit") == []


def test_explicit_confirmation_ci_identity_and_evidence_are_required(ci_recovery):
    engine, key, a, b = ci_recovery
    target = make_failed(engine, key, "recover-authz", business="recover-ci-business-a")
    scope = scope_for(target, a, "recover-ci-business-a")
    original = row(engine, target)
    for flags in (
        {}, recovery_flags(GITHUB_ACTIONS="false"),
        recovery_flags(INSTAGRAM_MANUAL_RECOVERY_CI_ENABLED="false"),
        recovery_flags(SENDRO_INSTAGRAM_PG_CI_APPROVAL="invalid"),
    ):
        with pytest.raises((InstagramRecoveryDisabled, InstagramAlertOutboxDisabled)):
            recover(engine, key, scope, flags=flags)
    with pytest.raises(InstagramRecoveryDisabled):
        recover(engine, key, scope, confirmation="NO")
    with pytest.raises(InstagramRecoveryDisabled):
        recover(engine, key, scope, digest="invalid-digest")
    with pytest.raises(InstagramRecoveryDisabled):
        recover(engine, key, scope, attempts=True)

    fake = create_engine("postgresql+psycopg://fake:fake@host.invalid:5432/sendro")
    try:
        with pytest.raises(InstagramAlertOutboxDisabled):
            recover_one_failed_instagram_ci(
                fake, scope=scope, expected_digest="a" * 64,
                expected_attempts=5, encryption_key=key,
                environ=recovery_flags(), confirmation=CONFIRM_RECOVERY,
            )
    finally:
        fake.dispose()
    assert row(engine, target) == original
    assert rows(engine, "sendro_ci_instagram_recovery_audit") == []


def test_locked_delivery_and_failed_audit_insert_cannot_partially_recover(ci_recovery):
    engine, key, a, b = ci_recovery
    target = make_failed(engine, key, "recover-locked", business="recover-ci-business-a")
    scope = scope_for(target, a, "recover-ci-business-a")
    original = row(engine, target)

    with engine.connect() as lock:
        tx = lock.begin()
        try:
            lock.execute(text("""
                SELECT id FROM public.sendro_channel_webhook_deliveries
                WHERE id=:id FOR UPDATE
            """), {"id": target})
            with pytest.raises(InstagramRecoveryBlocked):
                recover(engine, key, scope)
        finally:
            tx.rollback()
    assert row(engine, target) == original
    assert rows(engine, "sendro_ci_instagram_recovery_audit") == []

    # Simulate audit table outage: fail closed and leave the failed DM alone.
    with engine.begin() as db:
        db.execute(text("DROP TABLE public.sendro_ci_instagram_recovery_audit"))
    with pytest.raises(InstagramRecoveryBlocked):
        recover(engine, key, scope)
    assert row(engine, target) == original


def test_duplicate_audit_rejects_second_attempt_even_if_state_is_reset(ci_recovery):
    engine, key, a, b = ci_recovery
    target = make_failed(engine, key, "recover-no-double", business="recover-ci-business-a")
    scope = scope_for(target, a, "recover-ci-business-a")
    assert recover(engine, key, scope)["audit_written"]
    with engine.begin() as db:
        # Synthetic adversarial state manipulation, DISPOSABLE CI ONLY.
        db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET processing_state='failed', attempts=5,
                last_error_code='transient_processing_failure'
            WHERE id=:id
        """), {"id": target})
    again = row(engine, target)
    with pytest.raises(InstagramRecoveryBlocked):
        recover(engine, key, scope)
    assert row(engine, target) == again
    assert len(rows(engine, "sendro_ci_instagram_recovery_audit")) == 1
