"""Verified WhatsApp destination registry against isolated CI PostgreSQL only.

Replays the manual DDL on the ephemeral GitHub Actions PostgreSQL 16 service,
never against Render/shared data. All business IDs and evidence UUIDs are fake.
The protected Sendro webhook never imports/uses the registry adapter.
"""
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from backend.app.whatsapp_account_routing_preflight import (
    WhatsAppRoutingPreflightError,
    preflight_whatsapp_account_routes,
)
from backend.app.whatsapp_verified_destination_registry import (
    VERIFIED_DESTINATIONS_SQL, load_verified_whatsapp_registry,
)
from backend.tests.test_privacy_whatsapp_ownership_postgres_ci import (
    require_disposable_whatsapp_pg,
)


WA_A, PH_A = "700000001", "800000001"
WA_B, PH_B = "700000002", "800000002"
EA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

ADD_SQL = text("""
    INSERT INTO public.sendro_whatsapp_verified_destinations
      (waba_id, phone_number_id, tenant_id, verified_by_user_id,
       verification_method, evidence_ref, verified_at)
    VALUES
      (:waba, :phone, :tenant, :reviewer,
       'manual-owner-review', CAST(:evidence AS uuid),
       '2026-10-20 10:00:00+00')
""")


def destination(waba=WA_A, phone=PH_A, tenant=71, reviewer=171, evidence=EA):
    return {"waba": waba, "phone": phone, "tenant": tenant,
            "reviewer": reviewer, "evidence": evidence}


@pytest.fixture(scope="module")
def isolated_registry():
    url = os.environ.get("SENDRO_WHATSAPP_PG_CI_URL")
    if not url:
        pytest.skip("Ephemeral GitHub Actions PostgreSQL required")
    approved = require_disposable_whatsapp_pg(url, os.environ)
    engine = create_engine(
        approved, connect_args={"options": "-c lock_timeout=2000 -c statement_timeout=10000"}
    )
    try:
        with engine.begin() as db:
            # Disposable CI fixture. Existing ownership rehearsal uses minimal
            # tenant/membership stubs; extend them to production-shape roles.
            db.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS public.users (
                    id INTEGER PRIMARY KEY,
                    disabled BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)
            db.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS public.sendro_tenants (
                    id BIGINT PRIMARY KEY, display_name TEXT NOT NULL
                )
            """)
            db.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS public.sendro_tenant_users (
                    tenant_id BIGINT NOT NULL REFERENCES public.sendro_tenants(id),
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY(tenant_id, user_id)
                )
            """)
            db.exec_driver_sql("""
                ALTER TABLE public.sendro_tenant_users
                ADD COLUMN IF NOT EXISTS member_role TEXT NOT NULL DEFAULT 'operator'
            """)
            db.exec_driver_sql("""
                ALTER TABLE public.sendro_tenant_users
                ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE
            """)
            db.execute(text("""
                INSERT INTO public.users(id,disabled)
                VALUES (171,FALSE),(172,FALSE),(173,FALSE),(174,FALSE),(175,TRUE)
                ON CONFLICT(id) DO UPDATE SET disabled=EXCLUDED.disabled
            """))
            db.execute(text("""
                INSERT INTO public.sendro_tenants(id,display_name)
                VALUES (71,'Synthetic A'), (72,'Synthetic B')
                ON CONFLICT(id) DO NOTHING
            """))
            db.execute(text("""
                INSERT INTO public.sendro_tenant_users(tenant_id,user_id,member_role,is_active)
                VALUES (71,171,'owner',TRUE), (72,172,'admin',TRUE),
                       (71,173,'operator',TRUE), (71,174,'owner',FALSE),
                       (71,175,'admin',TRUE)
                ON CONFLICT(tenant_id,user_id) DO UPDATE
                  SET member_role=EXCLUDED.member_role,
                      is_active=EXCLUDED.is_active
            """))
        sql = (Path(__file__).parents[2] / "ops" / "db" /
               "20261020_whatsapp_verified_destinations_MANUAL_ONLY.sql"
               ).read_text(encoding="utf-8")
        assert "CREATE TABLE public.sendro_whatsapp_verified_destinations" in sql
        assert "BEGIN;" in sql and "COMMIT;" in sql
        from psycopg import ClientCursor
        raw = engine.raw_connection()
        try:
            raw.rollback()
            with ClientCursor(raw.driver_connection) as cursor:
                cursor.execute(sql)
            raw.commit()
        finally:
            raw.close()
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def reset_disposable_registry(request):
    if "isolated_registry" not in request.fixturenames:
        yield
        return
    engine = request.getfixturevalue("isolated_registry")
    # TRUNCATE is allowed ONLY on these fabricated ephemeral CI rows, never
    # in Sendro/Render. It deliberately bypasses the immutable-row trigger
    # solely to give each independent test a fresh disposable fixture.
    with engine.begin() as db:
        db.execute(text("TRUNCATE TABLE public.sendro_whatsapp_verified_destinations"))
    yield


def count(engine):
    with engine.connect() as db:
        return db.execute(text(
            "SELECT COUNT(*) FROM public.sendro_whatsapp_verified_destinations"
        )).scalar_one()


def test_new_registry_is_empty_and_unverified_account_cannot_route(isolated_registry):
    assert count(isolated_registry) == 0
    with isolated_registry.connect() as db:
        with pytest.raises(WhatsAppRoutingPreflightError, match="Missing"):
            load_verified_whatsapp_registry(db)


def test_active_verified_pairs_resolve_two_tenants_and_revoke_fail_closed(isolated_registry):
    with isolated_registry.begin() as db:
        db.execute(ADD_SQL, destination())
        db.execute(ADD_SQL, destination(WA_B, PH_B, 72, 172, EB))
    with isolated_registry.connect() as db:
        registry = load_verified_whatsapp_registry(db)
        assert dict(registry) == {(WA_A, PH_A): 71, (WA_B, PH_B): 72}
        with pytest.raises(TypeError):
            registry[(WA_A, PH_A)] = 72
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {"id": WA_A, "changes": [{"field": "messages", "value": {
                    "metadata": {"phone_number_id": PH_A},
                    "messages": [{"id": "synthetic-1"}],
                }}]},
                {"id": WA_B, "changes": [{"field": "messages", "value": {
                    "metadata": {"phone_number_id": PH_B},
                    "messages": [{"id": "synthetic-2"}],
                }}]},
            ],
        }
        decisions = preflight_whatsapp_account_routes(
            payload, registry, signature_verified=True
        )
        assert [d.tenant_id for d in decisions] == [71, 72]
    with isolated_registry.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_whatsapp_verified_destinations
            SET revoked_at='2026-10-21 10:00:00+00'
            WHERE phone_number_id=:phone
        """), {"phone": PH_A})
    with isolated_registry.connect() as db:
        registry = load_verified_whatsapp_registry(db)
        assert dict(registry) == {(WA_B, PH_B): 72}
        with pytest.raises(WhatsAppRoutingPreflightError):
            preflight_whatsapp_account_routes(
                payload, registry, signature_verified=True
            )


@pytest.mark.parametrize("bad", [
    destination(tenant=72, reviewer=171),  # mismatched membership
    destination(reviewer=173),  # operator is not an approver
    destination(reviewer=174),  # inactive member
    destination(reviewer=175),  # active membership, but disabled login
    destination(tenant=9999, reviewer=171),  # unknown tenant
    destination(phone="not-an-id"),  # nonnumeric Meta ID
    destination(waba="700000002", phone="1"),  # short ID
    destination(evidence="fabricated-not-uuid"),  # malformed evidence
])
def test_invalid_owner_attestation_or_identifier_rolls_back(isolated_registry, bad):
    with pytest.raises(DBAPIError):
        with isolated_registry.begin() as db:
            db.execute(ADD_SQL, bad)
    assert count(isolated_registry) == 0


def test_duplicate_phone_id_across_businesses_is_not_permitted(isolated_registry):
    with isolated_registry.begin() as db:
        db.execute(ADD_SQL, destination())
    with pytest.raises(DBAPIError):
        with isolated_registry.begin() as db:
            db.execute(ADD_SQL, destination(WA_B, PH_A, 72, 172, EB))
    with isolated_registry.connect() as db:
        registry = load_verified_whatsapp_registry(db)
        assert dict(registry) == {(WA_A, PH_A): 71}


def test_verified_owner_and_evidence_cannot_be_rewritten_or_deleted(isolated_registry):
    with isolated_registry.begin() as db:
        db.execute(ADD_SQL, destination())
    attempts = [
        ("UPDATE public.sendro_whatsapp_verified_destinations "
         "SET tenant_id=72 WHERE phone_number_id=:id"),
        ("UPDATE public.sendro_whatsapp_verified_destinations "
         "SET evidence_ref='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb' "
         "WHERE phone_number_id=:id"),
        ("DELETE FROM public.sendro_whatsapp_verified_destinations "
         "WHERE phone_number_id=:id"),
    ]
    for sql in attempts:
        with pytest.raises(DBAPIError):
            with isolated_registry.begin() as db:
                db.execute(text(sql), {"id": PH_A})
    with isolated_registry.connect() as db:
        assert dict(load_verified_whatsapp_registry(db)) == {(WA_A, PH_A): 71}


def test_revocation_cannot_be_removed_or_reapplied(isolated_registry):
    with isolated_registry.begin() as db:
        db.execute(ADD_SQL, destination())
        db.execute(text("""
            UPDATE public.sendro_whatsapp_verified_destinations
            SET revoked_at='2026-10-21 10:00:00+00'
            WHERE phone_number_id=:id
        """), {"id": PH_A})
    for sql in (
        "SET revoked_at=NULL",
        "SET revoked_at='2026-10-22 10:00:00+00'",
    ):
        with pytest.raises(DBAPIError):
            with isolated_registry.begin() as db:
                db.execute(text(
                    "UPDATE public.sendro_whatsapp_verified_destinations "
                    + sql + " WHERE phone_number_id=:id"
                ), {"id": PH_A})
    with isolated_registry.connect() as db:
        with pytest.raises(WhatsAppRoutingPreflightError):
            load_verified_whatsapp_registry(db)


def test_all_or_nothing_failed_batch_preserves_empty_registry(isolated_registry):
    with pytest.raises(DBAPIError):
        with isolated_registry.begin() as db:
            db.execute(ADD_SQL, destination())
            db.execute(ADD_SQL, destination(WA_B, PH_B, 72, 173, EB))
    assert count(isolated_registry) == 0


def test_read_only_transaction_refuses_insert(isolated_registry):
    with pytest.raises(DBAPIError):
        with isolated_registry.connect() as db:
            with db.begin():
                db.execute(text("SET TRANSACTION READ ONLY"))
                db.execute(ADD_SQL, destination())
    assert count(isolated_registry) == 0


def test_read_only_resolver_is_select_only_and_unmounted(isolated_registry):
    sql = str(VERIFIED_DESTINATIONS_SQL).upper()
    assert "SELECT" in sql and "WHERE REVOKED_AT IS NULL" in sql
    for forbidden in ("INSERT", "UPDATE ", "DELETE ", "DROP ", "SELECT *"):
        assert forbidden not in sql
    live = (Path(__file__).parents[1] / "app" / "main.py").read_text()
    assert "whatsapp_verified_destination_registry" not in live
    with isolated_registry.begin() as db:
        db.execute(ADD_SQL, destination())
    with isolated_registry.connect() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        assert dict(load_verified_whatsapp_registry(db)) == {(WA_A, PH_A): 71}
    assert count(isolated_registry) == 1
