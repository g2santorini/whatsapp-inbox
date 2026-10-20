"""Private-schema registry DDL and privilege rehearsal on disposable PostgreSQL 18.3.

Never connects to Render or reads DATABASE_URL. No real account/guest data.
The new registry is empty; no attestation/revocation privileges are activated.
"""
import os
from pathlib import Path

import pytest
from psycopg import ClientCursor, Error as PsycopgError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from backend.app.whatsapp_account_routing_preflight import WhatsAppRoutingPreflightError
from backend.app.whatsapp_verified_destination_registry import (
    load_dedicated_whatsapp_registry,
)

DB = "sendro_wa_private_ci"
PORT = 55443
CI_USER = "sendro_wa_private_ci"
OWNER = "sendro_whatsapp_registry_owner"
READER = "sendro_whatsapp_registry_reader"
LEGACY = "legacy_privileged_ci"
PASSWORD = "disposable-private-whatsapp-ci"
GATE = "disposable-private-whatsapp-postgres-only"


def guarded_url():
    raw = os.environ.get("SENDRO_WHATSAPP_PRIVATE_PG_CI_URL")
    if not raw:
        pytest.skip("Dedicated disposable GitHub PostgreSQL 18.3 required")
    u = make_url(raw)
    if not (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("SENDRO_WHATSAPP_PRIVATE_PG_CI_APPROVAL") == GATE
        and u.drivername == "postgresql+psycopg"
        and u.username == CI_USER
        and u.password == PASSWORD
        and u.host == "127.0.0.1"
        and u.port == PORT
        and u.database == DB
    ):
        raise RuntimeError("Refusing non-disposable WhatsApp registry database")
    return u


def run_manual_script(engine, sql):
    raw = engine.raw_connection()
    try:
        raw.rollback()
        with ClientCursor(raw.driver_connection) as cur:
            cur.execute(sql)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def must_deny(engine, sql):
    with pytest.raises(DBAPIError):
        with engine.begin() as db:
            db.execute(text(sql))


@pytest.fixture(scope="module")
def dedicated_pg():
    url = guarded_url()
    admin = create_engine(url, connect_args={
        "options": "-c lock_timeout=2000 -c statement_timeout=10000"
    })
    roles = {}
    ddl_path = (Path(__file__).parents[2] / "ops" / "db" /
                "20261020_whatsapp_registry_DEDICATED_SCHEMA_MANUAL_ONLY.sql")
    preflight_path = (Path(__file__).parents[2] / "ops" / "db" /
                      "20261020_whatsapp_registry_DEDICATED_READ_ONLY_preflight.sql")
    ddl = ddl_path.read_text(encoding="utf-8")
    preflight = preflight_path.read_text(encoding="utf-8")
    assert "CREATE SCHEMA sendro_whatsapp" in ddl
    assert "INSERT INTO" not in ddl.upper()
    assert "GRANT INSERT" not in ddl.upper()
    assert "SET LOCAL ROLE sendro_whatsapp_registry_owner" in ddl
    try:
        with admin.begin() as db:
            # Dependency subset reproduced from the REAL read-only
            # PostgreSQL 18.3 catalog (20 Oct 2026). Real users has many
            # unrelated columns; no user data or credential column is copied.
            db.execute(text("""
                CREATE TABLE public.sendro_tenants (
                    id BIGINT PRIMARY KEY,
                    slug VARCHAR(100) NOT NULL UNIQUE,
                    display_name VARCHAR(160) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT ck_sendro_tenants_slug
                        CHECK (slug ~ '^[a-z0-9][a-z0-9_-]*
            db.execute(text("""
                INSERT INTO public.users(id,disabled)
                VALUES(171,FALSE),(172,FALSE)
            """))
            db.execute(text("""
                INSERT INTO public.sendro_tenant_users
                (tenant_id,user_id,member_role,is_active)
                VALUES(71,171,'owner',TRUE),(72,172,'admin',TRUE)
            """))
            db.exec_driver_sql(
                f"CREATE ROLE {OWNER} NOLOGIN NOSUPERUSER "
                "NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            )
            db.exec_driver_sql(
                f"CREATE ROLE {READER} LOGIN NOSUPERUSER "
                f"NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '{PASSWORD}'"
            )
            db.exec_driver_sql(
                f"CREATE ROLE {LEGACY} LOGIN NOSUPERUSER "
                f"CREATEDB CREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '{PASSWORD}'"
            )
            db.exec_driver_sql(f"GRANT CREATE ON SCHEMA public TO {LEGACY}")

        # Snapshot existing synthetic business schema before any registry
        # DDL; later assert no legacy columns, constraints, or rows change.
        legacy_shape_sql = text("""
            SELECT COALESCE(
                string_agg(
                    c.relname||':'||a.attname||':'||
                    pg_catalog.format_type(a.atttypid,a.atttypmod)||':'||
                    a.attnotnull::text,
                    ',' ORDER BY c.relname,a.attnum
                ), ''
            ) AS column_signature
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
            WHERE n.nspname='public'
              AND c.relname IN ('users','sendro_tenants','sendro_tenant_users')
              AND a.attnum>0 AND NOT a.attisdropped
        """)
        constraint_shape_sql = text("""
            SELECT COALESCE(
                string_agg(
                    c.conrelid::regclass::text||':'||c.conname||':'||
                    pg_catalog.pg_get_constraintdef(c.oid),
                    ',' ORDER BY c.conrelid::regclass::text,c.conname
                ), ''
            ) AS constraint_signature
            FROM pg_catalog.pg_constraint c
            WHERE c.conrelid IN (
                'public.users'::regclass,
                'public.sendro_tenants'::regclass,
                'public.sendro_tenant_users'::regclass
            )
        """)
        counts_sql = text("""
            SELECT (SELECT COUNT(*) FROM public.sendro_tenants) AS tenants,
                   (SELECT COUNT(*) FROM public.sendro_tenant_users) AS memberships,
                   (SELECT COUNT(*) FROM public.users) AS users
        """)
        with admin.connect() as db:
            original_shapes = (
                db.execute(legacy_shape_sql).scalar_one(),
                db.execute(constraint_shape_sql).scalar_one(),
                tuple(db.execute(counts_sql).one()),
            )
        with admin.connect() as db:
            with db.begin():
                db.execute(text("SET TRANSACTION READ ONLY"))
                report = db.execute(text(preflight)).mappings().one()
                assert report["transaction_read_only"] == "on"
                assert report["valid_columns"] == 7
                assert report["membership_key_exists"] is True
                assert report["schema_shape_ready"] is True
                assert report["owner_role_exists"] is True
                assert report["reader_role_exists"] is True
                assert report["new_schema_exists"] is False

        # A missing REFERENCES grant must abort the WHOLE BEGIN/COMMIT script.
        with pytest.raises(PsycopgError):
            run_manual_script(admin, ddl)
        with admin.connect() as db:
            assert db.execute(text(
                "SELECT pg_catalog.to_regnamespace('sendro_whatsapp')"
            )).scalar_one() is None

        with admin.begin() as db:
            db.exec_driver_sql(
                f"GRANT REFERENCES ON public.sendro_tenants, "
                f"public.sendro_tenant_users TO {OWNER}"
            )
        run_manual_script(admin, ddl)
        with admin.connect() as db:
            assert (
                db.execute(legacy_shape_sql).scalar_one(),
                db.execute(constraint_shape_sql).scalar_one(),
                tuple(db.execute(counts_sql).one()),
            ) == original_shapes, "Registry DDL mutated legacy synthetic schema/rows"
        with admin.connect() as db:
            with db.begin():
                db.execute(text("SET TRANSACTION READ ONLY"))
                after = db.execute(text(preflight)).mappings().one()
                assert after["new_schema_exists"] is True
                assert after["new_table_exists"] is True
                assert after["schema_shape_ready"] is False

        for role in (READER, LEGACY):
            roles[role] = create_engine(
                url.set(username=role, password=PASSWORD),
                connect_args={"options": "-c lock_timeout=2000 -c statement_timeout=10000"},
            )
        yield admin, roles, ddl
    finally:
        for engine in roles.values():
            engine.dispose()
        admin.dispose()


def test_empty_registry_and_nologin_independent_owner(dedicated_pg):
    admin, roles, _ = dedicated_pg
    with admin.connect() as db:
        obj = db.execute(text("""
            SELECT pg_catalog.pg_get_userbyid(c.relowner) AS table_owner,
                   pg_catalog.pg_get_userbyid(n.nspowner) AS schema_owner,
                   (SELECT COUNT(*) FROM sendro_whatsapp.verified_destinations) AS rows
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON c.relnamespace=n.oid
            WHERE n.nspname='sendro_whatsapp' AND c.relname='verified_destinations'
        """)).mappings().one()
        assert obj["table_owner"] == obj["schema_owner"] == OWNER
        assert obj["rows"] == 0
        o = db.execute(text("""
            SELECT rolcanlogin,rolcreatedb,rolcreaterole
            FROM pg_catalog.pg_roles WHERE rolname=:role
        """), {"role": OWNER}).one()
        assert tuple(o) == (False,False,False)
    with roles[READER].connect() as db:
        with pytest.raises(WhatsAppRoutingPreflightError, match="Missing"):
            load_dedicated_whatsapp_registry(db)


def test_reader_and_legacy_cannot_mutate_or_take_ownership(dedicated_pg):
    admin, roles, _ = dedicated_pg
    with roles[READER].connect() as db:
        grants = db.execute(text("""
            SELECT
              has_column_privilege(current_user,
                  'sendro_whatsapp.verified_destinations','waba_id','SELECT') AS routing_read,
              has_table_privilege(current_user,
                  'sendro_whatsapp.verified_destinations','INSERT,UPDATE,DELETE,TRUNCATE') AS writes,
              has_function_privilege(current_user,
                  'sendro_whatsapp.validate_reviewer()','EXECUTE') AS validator_execute,
              has_schema_privilege(current_user,'sendro_whatsapp','CREATE') AS schema_write
        """)).mappings().one()
        assert grants["routing_read"] is True
        assert grants["writes"] is False
        assert grants["validator_execute"] is False
        assert grants["schema_write"] is False
    for engine in (roles[READER],roles[LEGACY]):
        must_deny(engine,"SELECT evidence_ref FROM sendro_whatsapp.verified_destinations")
        must_deny(engine,"INSERT INTO sendro_whatsapp.verified_destinations "
                   "(waba_id,phone_number_id) VALUES ('777777777','888888888')")
        must_deny(engine,"DELETE FROM sendro_whatsapp.verified_destinations")
        must_deny(engine,"TRUNCATE sendro_whatsapp.verified_destinations")
        must_deny(engine,"ALTER TABLE sendro_whatsapp.verified_destinations DISABLE TRIGGER ALL")
        must_deny(engine,f"SET ROLE {OWNER}")
    # A CREATE ROLE principal is not thereby the controlled NOLOGIN owner.
    must_deny(roles[LEGACY],f"GRANT {OWNER} TO {LEGACY}")
    with admin.connect() as db:
        assert db.execute(text(
            "SELECT COUNT(*) FROM sendro_whatsapp.verified_destinations"
        )).scalar_one() == 0


def test_second_install_fails_without_touching_committed_registry(dedicated_pg):
    admin, _, ddl = dedicated_pg
    with pytest.raises(PsycopgError):
        run_manual_script(admin, ddl)
    with admin.connect() as db:
        assert db.execute(text(
            "SELECT COUNT(*) FROM sendro_whatsapp.verified_destinations"
        )).scalar_one() == 0


def test_createrole_self_created_owner_is_not_independent(dedicated_pg):
    """Regression: PostgreSQL CREATEROLE creator gains ADMIN of own new role.

    A non-superuser that *creates* the owner role can immediately grant itself
    SET permission later. This demonstrates why the existing privileged Sendro
    login must NEVER provision the new owner in the real shared database.
    """
    admin, roles, _ = dedicated_pg
    legacy = roles[LEGACY]
    self_owned = "unsafe_selfcreated_registry_owner_ci"

    with legacy.begin() as db:
        db.execute(text(
            f"CREATE ROLE {self_owned} NOLOGIN NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
        ))
        membership = db.execute(text("""
            SELECT am.admin_option,am.set_option,am.inherit_option
            FROM pg_catalog.pg_auth_members am
            JOIN pg_catalog.pg_roles owner ON owner.oid=am.roleid
            JOIN pg_catalog.pg_roles member ON member.oid=am.member
            WHERE owner.rolname=:owner AND member.rolname=:member
        """), {"owner": self_owned, "member": LEGACY}).one()
        assert membership.admin_option is True
        assert membership.set_option is False
        assert membership.inherit_option is False

        # Privilege escalation possible for a creator-owned role: this is
        # intentional PostgreSQL behavior, and the reason for the STOP gate.
        db.execute(text(
            f"GRANT {self_owned} TO {LEGACY} WITH SET TRUE, INHERIT FALSE"
        ))
    with legacy.begin() as db:
        db.execute(text(f"SET LOCAL ROLE {self_owned}"))
        assert db.execute(text("SELECT current_user")).scalar_one() == self_owned

    # In contrast, the independently-created registry OWNER remains out of
    # reach of the legacy user; it can't gain admin or SET membership there.
    with admin.connect() as db:
        row = db.execute(text("""
            SELECT COUNT(*) FROM pg_catalog.pg_auth_members am
            JOIN pg_catalog.pg_roles owner ON owner.oid=am.roleid
            JOIN pg_catalog.pg_roles member ON member.oid=am.member
            WHERE owner.rolname=:owner AND member.rolname=:member
        """), {"owner": OWNER, "member": LEGACY}).scalar_one()
        assert row == 0
    must_deny(legacy, f"GRANT {OWNER} TO {LEGACY} WITH SET TRUE")
)
                )
            """))
            db.execute(text("""
                CREATE TABLE public.users (
                    id INTEGER PRIMARY KEY,
                    disabled BOOLEAN NOT NULL
                )
            """))
            db.execute(text("""
                CREATE TABLE public.sendro_tenant_users (
                    tenant_id BIGINT NOT NULL REFERENCES public.sendro_tenants(id)
                        ON DELETE RESTRICT,
                    user_id INTEGER NOT NULL REFERENCES public.users(id)
                        ON DELETE RESTRICT,
                    member_role VARCHAR(20) NOT NULL DEFAULT 'operator',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT ck_sendro_tenant_users_role
                        CHECK (member_role IN ('owner','admin','operator','viewer')),
                    CONSTRAINT pk_sendro_tenant_users PRIMARY KEY (tenant_id, user_id)
                )
            """))
            db.execute(text("""
                INSERT INTO public.sendro_tenants(id,slug,display_name)
                VALUES(71,'synthetic-a','Synthetic A'),(72,'synthetic-b','Synthetic B')
            """))
            db.execute(text("""
                INSERT INTO public.users(id,disabled)
                VALUES(171,FALSE),(172,FALSE)
            """))
            db.execute(text("""
                INSERT INTO public.sendro_tenant_users
                (tenant_id,user_id,member_role,is_active)
                VALUES(71,171,'owner',TRUE),(72,172,'admin',TRUE)
            """))
            db.exec_driver_sql(
                f"CREATE ROLE {OWNER} NOLOGIN NOSUPERUSER "
                "NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            )
            db.exec_driver_sql(
                f"CREATE ROLE {READER} LOGIN NOSUPERUSER "
                f"NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '{PASSWORD}'"
            )
            db.exec_driver_sql(
                f"CREATE ROLE {LEGACY} LOGIN NOSUPERUSER "
                f"CREATEDB CREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '{PASSWORD}'"
            )
            db.exec_driver_sql(f"GRANT CREATE ON SCHEMA public TO {LEGACY}")

        with admin.connect() as db:
            with db.begin():
                db.execute(text("SET TRANSACTION READ ONLY"))
                report = db.execute(text(preflight)).mappings().one()
                assert report["transaction_read_only"] == "on"
                assert report["valid_columns"] == 7
                assert report["membership_key_exists"] is True
                assert report["schema_shape_ready"] is True
                assert report["owner_role_exists"] is True
                assert report["reader_role_exists"] is True
                assert report["new_schema_exists"] is False

        # A missing REFERENCES grant must abort the WHOLE BEGIN/COMMIT script.
        with pytest.raises(PsycopgError):
            run_manual_script(admin, ddl)
        with admin.connect() as db:
            assert db.execute(text(
                "SELECT pg_catalog.to_regnamespace('sendro_whatsapp')"
            )).scalar_one() is None

        with admin.begin() as db:
            db.exec_driver_sql(
                f"GRANT REFERENCES ON public.sendro_tenants, "
                f"public.sendro_tenant_users TO {OWNER}"
            )
        run_manual_script(admin, ddl)
        with admin.connect() as db:
            with db.begin():
                db.execute(text("SET TRANSACTION READ ONLY"))
                after = db.execute(text(preflight)).mappings().one()
                assert after["new_schema_exists"] is True
                assert after["new_table_exists"] is True
                assert after["schema_shape_ready"] is False

        for role in (READER, LEGACY):
            roles[role] = create_engine(
                url.set(username=role, password=PASSWORD),
                connect_args={"options": "-c lock_timeout=2000 -c statement_timeout=10000"},
            )
        yield admin, roles, ddl
    finally:
        for engine in roles.values():
            engine.dispose()
        admin.dispose()


def test_empty_registry_and_nologin_independent_owner(dedicated_pg):
    admin, roles, _ = dedicated_pg
    with admin.connect() as db:
        obj = db.execute(text("""
            SELECT pg_catalog.pg_get_userbyid(c.relowner) AS table_owner,
                   pg_catalog.pg_get_userbyid(n.nspowner) AS schema_owner,
                   (SELECT COUNT(*) FROM sendro_whatsapp.verified_destinations) AS rows
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON c.relnamespace=n.oid
            WHERE n.nspname='sendro_whatsapp' AND c.relname='verified_destinations'
        """)).mappings().one()
        assert obj["table_owner"] == obj["schema_owner"] == OWNER
        assert obj["rows"] == 0
        o = db.execute(text("""
            SELECT rolcanlogin,rolcreatedb,rolcreaterole
            FROM pg_catalog.pg_roles WHERE rolname=:role
        """), {"role": OWNER}).one()
        assert tuple(o) == (False,False,False)
    with roles[READER].connect() as db:
        with pytest.raises(WhatsAppRoutingPreflightError, match="Missing"):
            load_dedicated_whatsapp_registry(db)


def test_reader_and_legacy_cannot_mutate_or_take_ownership(dedicated_pg):
    admin, roles, _ = dedicated_pg
    with roles[READER].connect() as db:
        grants = db.execute(text("""
            SELECT
              has_column_privilege(current_user,
                  'sendro_whatsapp.verified_destinations','waba_id','SELECT') AS routing_read,
              has_table_privilege(current_user,
                  'sendro_whatsapp.verified_destinations','INSERT,UPDATE,DELETE,TRUNCATE') AS writes,
              has_function_privilege(current_user,
                  'sendro_whatsapp.validate_reviewer()','EXECUTE') AS validator_execute,
              has_schema_privilege(current_user,'sendro_whatsapp','CREATE') AS schema_write
        """)).mappings().one()
        assert grants["routing_read"] is True
        assert grants["writes"] is False
        assert grants["validator_execute"] is False
        assert grants["schema_write"] is False
    for engine in (roles[READER],roles[LEGACY]):
        must_deny(engine,"SELECT evidence_ref FROM sendro_whatsapp.verified_destinations")
        must_deny(engine,"INSERT INTO sendro_whatsapp.verified_destinations "
                   "(waba_id,phone_number_id) VALUES ('777777777','888888888')")
        must_deny(engine,"DELETE FROM sendro_whatsapp.verified_destinations")
        must_deny(engine,"TRUNCATE sendro_whatsapp.verified_destinations")
        must_deny(engine,"ALTER TABLE sendro_whatsapp.verified_destinations DISABLE TRIGGER ALL")
        must_deny(engine,f"SET ROLE {OWNER}")
    # A CREATE ROLE principal is not thereby the controlled NOLOGIN owner.
    must_deny(roles[LEGACY],f"GRANT {OWNER} TO {LEGACY}")
    with admin.connect() as db:
        assert db.execute(text(
            "SELECT COUNT(*) FROM sendro_whatsapp.verified_destinations"
        )).scalar_one() == 0


def test_second_install_fails_without_touching_committed_registry(dedicated_pg):
    admin, _, ddl = dedicated_pg
    with pytest.raises(PsycopgError):
        run_manual_script(admin, ddl)
    with admin.connect() as db:
        assert db.execute(text(
            "SELECT COUNT(*) FROM sendro_whatsapp.verified_destinations"
        )).scalar_one() == 0


def test_createrole_self_created_owner_is_not_independent(dedicated_pg):
    """Regression: PostgreSQL CREATEROLE creator gains ADMIN of own new role.

    A non-superuser that *creates* the owner role can immediately grant itself
    SET permission later. This demonstrates why the existing privileged Sendro
    login must NEVER provision the new owner in the real shared database.
    """
    admin, roles, _ = dedicated_pg
    legacy = roles[LEGACY]
    self_owned = "unsafe_selfcreated_registry_owner_ci"

    with legacy.begin() as db:
        db.execute(text(
            f"CREATE ROLE {self_owned} NOLOGIN NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
        ))
        membership = db.execute(text("""
            SELECT am.admin_option,am.set_option,am.inherit_option
            FROM pg_catalog.pg_auth_members am
            JOIN pg_catalog.pg_roles owner ON owner.oid=am.roleid
            JOIN pg_catalog.pg_roles member ON member.oid=am.member
            WHERE owner.rolname=:owner AND member.rolname=:member
        """), {"owner": self_owned, "member": LEGACY}).one()
        assert membership.admin_option is True
        assert membership.set_option is False
        assert membership.inherit_option is False

        # Privilege escalation possible for a creator-owned role: this is
        # intentional PostgreSQL behavior, and the reason for the STOP gate.
        db.execute(text(
            f"GRANT {self_owned} TO {LEGACY} WITH SET TRUE, INHERIT FALSE"
        ))
    with legacy.begin() as db:
        db.execute(text(f"SET LOCAL ROLE {self_owned}"))
        assert db.execute(text("SELECT current_user")).scalar_one() == self_owned

    # In contrast, the independently-created registry OWNER remains out of
    # reach of the legacy user; it can't gain admin or SET membership there.
    with admin.connect() as db:
        row = db.execute(text("""
            SELECT COUNT(*) FROM pg_catalog.pg_auth_members am
            JOIN pg_catalog.pg_roles owner ON owner.oid=am.roleid
            JOIN pg_catalog.pg_roles member ON member.oid=am.member
            WHERE owner.rolname=:owner AND member.rolname=:member
        """), {"owner": OWNER, "member": LEGACY}).scalar_one()
        assert row == 0
    must_deny(legacy, f"GRANT {OWNER} TO {LEGACY} WITH SET TRUE")
