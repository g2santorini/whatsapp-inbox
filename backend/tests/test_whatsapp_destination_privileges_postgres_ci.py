"""Disposable PostgreSQL ROLE/ACL rehearsal; NEVER connect to Render.

The GitHub Actions service below is the sole allowed target. It uses only
synthetic users, WABA/Phone IDs, and credentials. The manual DDL is exercised
unchanged with a distinct NOLOGIN object-owner role. Three LOGIN roles connect
independently (rather than SET ROLE) to test actual permission boundaries.
No live service imports this file and no database role changes are deployed.
"""
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from backend.app.whatsapp_account_routing_preflight import WhatsAppRoutingPreflightError
from backend.app.whatsapp_verified_destination_registry import load_verified_whatsapp_registry


CI_DB = "sendro_wa_acl_ci"
CI_HOST = "127.0.0.1"
CI_PORT = 55441
CI_USER = "sendro_wa_acl_ci"
CI_GATE = "disposable-whatsapp-acl-postgres-only"
OWNER = "sendro_wa_registry_owner_ci"
READER = "sendro_wa_registry_reader_ci"
ATTESTOR = "sendro_wa_registry_attestor_ci"
REVOKER = "sendro_wa_registry_revoker_ci"
FAKE_PASSWORD = "ci-ephemeral-role-password-only"
PHONE_A = "800000011"
WABA_A = "700000011"
PHONE_B = "800000012"
WABA_B = "700000012"
EVIDENCE_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EVIDENCE_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

ADD = text("""
    INSERT INTO public.sendro_whatsapp_verified_destinations
      (waba_id, phone_number_id, tenant_id, verified_by_user_id,
       verification_method, evidence_ref, verified_at)
    VALUES (:waba, :phone, :tenant, :reviewer,
            'manual-owner-review', CAST(:evidence AS uuid),
            '2026-10-20 10:00:00+00')
""")

REVOKE_ONE = text("""
    UPDATE public.sendro_whatsapp_verified_destinations
    SET revoked_at='2026-10-21 10:00:00+00'
    WHERE phone_number_id=:phone
""")


def allowed_ci_database():
    raw = os.environ.get("SENDRO_WHATSAPP_ACL_PG_CI_URL")
    if not raw:
        pytest.skip("Disposable GitHub Actions PostgreSQL service required")
    url = make_url(raw)
    if not (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("SENDRO_WHATSAPP_ACL_PG_CI_APPROVAL") == CI_GATE
        and url.drivername == "postgresql+psycopg"
        and url.host == CI_HOST
        and url.port == CI_PORT
        and url.database == CI_DB
        and url.username == CI_USER
        and url.password == FAKE_PASSWORD
    ):
        raise RuntimeError("Refusing non-disposable WhatsApp ACL database")
    return url


def synthetic_destination(phone=PHONE_A, waba=WABA_A, tenant=71, reviewer=171,
                          evidence=EVIDENCE_A):
    return dict(phone=phone, waba=waba, tenant=tenant, reviewer=reviewer,
                evidence=evidence)


@pytest.fixture(scope="module")
def isolated_acl_database():
    url = allowed_ci_database()
    bootstrap = create_engine(url)
    role_engines = {}
    try:
        with bootstrap.begin() as db:
            db.exec_driver_sql("""
                CREATE TABLE public.sendro_tenants (
                    id BIGINT PRIMARY KEY, display_name TEXT NOT NULL
                )
            """)
            db.exec_driver_sql("""
                CREATE TABLE public.users (
                    id INTEGER PRIMARY KEY, disabled BOOLEAN NOT NULL
                )
            """)
            db.exec_driver_sql("""
                CREATE TABLE public.sendro_tenant_users (
                    tenant_id BIGINT NOT NULL REFERENCES public.sendro_tenants(id),
                    user_id INTEGER NOT NULL REFERENCES public.users(id),
                    member_role TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL,
                    PRIMARY KEY (tenant_id, user_id)
                )
            """)
            db.execute(text("""
                INSERT INTO public.sendro_tenants(id,display_name)
                VALUES (71,'Fabricated A'),(72,'Fabricated B')
            """))
            db.execute(text("""
                INSERT INTO public.users(id,disabled)
                VALUES (171,FALSE),(172,FALSE),(173,FALSE),(174,TRUE)
            """))
            db.execute(text("""
                INSERT INTO public.sendro_tenant_users
                    (tenant_id,user_id,member_role,is_active)
                VALUES (71,171,'owner',TRUE),(72,172,'admin',TRUE),
                       (71,173,'operator',TRUE),(71,174,'admin',TRUE)
            """))
            # All role operations and schema privilege changes are LOCAL TO CI.
            # The Render/shared database is never a possible connection target.
            db.exec_driver_sql(f"CREATE ROLE {OWNER} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS")
            for role in (READER, ATTESTOR, REVOKER):
                db.exec_driver_sql(
                    f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB "
                    f"NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '{FAKE_PASSWORD}'"
                )
            db.exec_driver_sql("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            db.exec_driver_sql(f"GRANT CREATE ON SCHEMA public TO {OWNER}")
            db.exec_driver_sql(f"GRANT REFERENCES ON public.sendro_tenants TO {OWNER}")
            db.exec_driver_sql(f"GRANT REFERENCES ON public.sendro_tenant_users TO {OWNER}")
            db.exec_driver_sql(f"GRANT SELECT ON public.sendro_tenant_users,public.users TO {OWNER}")

        # Run the precise manual SQL as a *distinct* dedicated owner, rather
        # than the role that will serve the webhook. This role cannot login.
        ddl = (Path(__file__).parents[2] / "ops" / "db" /
               "20261020_whatsapp_verified_destinations_MANUAL_ONLY.sql"
               ).read_text(encoding="utf-8")
        assert "CREATE TABLE public.sendro_whatsapp_verified_destinations" in ddl
        from psycopg import ClientCursor
        raw = bootstrap.raw_connection()
        try:
            raw.rollback()
            with ClientCursor(raw.driver_connection) as cursor:
                cursor.execute(f"SET ROLE {OWNER}")
                cursor.execute(ddl)
                cursor.execute("RESET ROLE")
            raw.commit()
        finally:
            raw.close()

        with bootstrap.begin() as db:
            db.exec_driver_sql(
                "REVOKE ALL ON TABLE public.sendro_whatsapp_verified_destinations FROM PUBLIC"
            )
            db.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {READER}, {ATTESTOR}, {REVOKER}")
            db.exec_driver_sql(f"""
                GRANT SELECT (waba_id,phone_number_id,tenant_id,revoked_at)
                ON public.sendro_whatsapp_verified_destinations TO {READER}
            """)
            db.exec_driver_sql(f"""
                GRANT INSERT (waba_id,phone_number_id,tenant_id,
                              verified_by_user_id,verification_method,evidence_ref,verified_at)
                ON public.sendro_whatsapp_verified_destinations TO {ATTESTOR}
            """)
            # Trigger is SECURITY INVOKER; attestor must read only the precise
            # reviewer metadata needed by the validator, not guest messages.
            db.exec_driver_sql(f"""
                GRANT SELECT (tenant_id,user_id,member_role,is_active)
                ON public.sendro_tenant_users TO {ATTESTOR}
            """)
            db.exec_driver_sql(f"GRANT SELECT (id,disabled) ON public.users TO {ATTESTOR}")
            db.exec_driver_sql(f"""
                GRANT SELECT (phone_number_id,revoked_at),
                      UPDATE (revoked_at)
                ON public.sendro_whatsapp_verified_destinations TO {REVOKER}
            """)

        for role in (READER, ATTESTOR, REVOKER):
            role_engines[role] = create_engine(
                url.set(username=role, password=FAKE_PASSWORD),
                connect_args={"options": "-c lock_timeout=2000 -c statement_timeout=10000"},
            )
        yield bootstrap, role_engines
    finally:
        for engine in role_engines.values():
            engine.dispose()
        bootstrap.dispose()


def denied(engine, statement, params=None):
    with pytest.raises(DBAPIError):
        with engine.begin() as db:
            db.execute(text(statement), params or {})


def test_distinct_principals_are_non_admin_and_cannot_own_or_ddl(isolated_acl_database):
    admin, engines = isolated_acl_database
    with admin.connect() as db:
        owner = db.execute(text("""
            SELECT pg_catalog.pg_get_userbyid(relowner)
            FROM pg_catalog.pg_class
            WHERE oid='public.sendro_whatsapp_verified_destinations'::regclass
        """)).scalar_one()
        assert owner == OWNER
    for name, engine in engines.items():
        with engine.connect() as db:
            row = db.execute(text("""
                SELECT current_user AS role_name, r.rolsuper, r.rolcreaterole,
                       r.rolcreatedb, r.rolbypassrls,
                       has_schema_privilege(current_user,'public','CREATE') AS can_create,
                       pg_has_role(current_user, :owner, 'MEMBER') AS is_owner_member
                FROM pg_catalog.pg_roles r WHERE r.rolname=current_user
            """), {"owner": OWNER}).mappings().one()
            assert row["role_name"] == name
            assert not any(row[k] for k in (
                "rolsuper", "rolcreaterole", "rolcreatedb", "rolbypassrls",
                "can_create", "is_owner_member"
            ))
        denied(engine, "CREATE TABLE public.wa_illicit_ddl_ci(id integer)")
        denied(engine, f"SET ROLE {OWNER}")
        denied(engine, "TRUNCATE TABLE public.sendro_whatsapp_verified_destinations")
        denied(engine, "DELETE FROM public.sendro_whatsapp_verified_destinations")


def test_reader_uses_only_approved_metadata_columns(isolated_acl_database):
    _, engines = isolated_acl_database
    reader = engines[READER]
    attestor = engines[ATTESTOR]
    with reader.connect() as db:
        with pytest.raises(WhatsAppRoutingPreflightError, match="Missing"):
            load_verified_whatsapp_registry(db)
    denied(reader, "SELECT evidence_ref FROM public.sendro_whatsapp_verified_destinations")
    denied(reader, "SELECT verified_by_user_id FROM public.sendro_whatsapp_verified_destinations")
    denied(reader, "SELECT * FROM public.users")
    denied(reader, "SELECT * FROM public.sendro_tenant_users")
    denied(reader, """
        INSERT INTO public.sendro_whatsapp_verified_destinations
          (phone_number_id,waba_id,tenant_id) VALUES ('888888888','777777777',71)
    """)
    denied(reader, """
        UPDATE public.sendro_whatsapp_verified_destinations
        SET revoked_at=now()
    """)
    with attestor.begin() as db:
        db.execute(ADD, synthetic_destination())
    with reader.connect() as db:
        assert dict(load_verified_whatsapp_registry(db)) == {(WABA_A, PHONE_A): 71}


def test_attestor_validates_membership_without_any_update_delete_rights(isolated_acl_database):
    _, engines = isolated_acl_database
    attestor = engines[ATTESTOR]
    reader = engines[READER]
    denied(attestor, """
        UPDATE public.sendro_whatsapp_verified_destinations
        SET revoked_at=now()
    """)
    denied(attestor, "SELECT evidence_ref FROM public.sendro_whatsapp_verified_destinations")
    denied(attestor, "ALTER TABLE public.sendro_whatsapp_verified_destinations DISABLE TRIGGER ALL")
    denied(attestor, "TRUNCATE public.sendro_whatsapp_verified_destinations")
    # A syntactically valid UUID is not a substitute for authorized attestation.
    for bad_reviewer in (173, 174):
        with pytest.raises(DBAPIError):
            with attestor.begin() as db:
                db.execute(ADD, synthetic_destination(
                    phone=PHONE_B, waba=WABA_B, reviewer=bad_reviewer,
                    evidence=EVIDENCE_B))
    with pytest.raises(DBAPIError):
        with attestor.begin() as db:
            db.execute(ADD, synthetic_destination(
                phone=PHONE_A, waba=WABA_B, tenant=72, reviewer=172,
                evidence=EVIDENCE_B))
    with reader.connect() as db:
        assert dict(load_verified_whatsapp_registry(db)) == {(WABA_A, PHONE_A): 71}


def test_revoker_can_only_revoke_once_and_reader_fails_closed(isolated_acl_database):
    _, engines = isolated_acl_database
    revoker = engines[REVOKER]
    reader = engines[READER]
    denied(revoker, """
        UPDATE public.sendro_whatsapp_verified_destinations
        SET tenant_id=72 WHERE phone_number_id=:phone
    """, {"phone": PHONE_A})
    denied(revoker, """
        UPDATE public.sendro_whatsapp_verified_destinations
        SET evidence_ref='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        WHERE phone_number_id=:phone
    """, {"phone": PHONE_A})
    denied(revoker, "ALTER TABLE public.sendro_whatsapp_verified_destinations DISABLE TRIGGER ALL")
    with revoker.begin() as db:
        assert db.execute(REVOKE_ONE, {"phone": PHONE_A}).rowcount == 1
    denied(revoker, """
        UPDATE public.sendro_whatsapp_verified_destinations
        SET revoked_at='2026-10-22 10:00:00+00'
        WHERE phone_number_id=:phone
    """, {"phone": PHONE_A})
    denied(revoker, """
        UPDATE public.sendro_whatsapp_verified_destinations
        SET revoked_at=NULL WHERE phone_number_id=:phone
    """, {"phone": PHONE_A})
    with reader.connect() as db:
        with pytest.raises(WhatsAppRoutingPreflightError, match="Missing"):
            load_verified_whatsapp_registry(db)
