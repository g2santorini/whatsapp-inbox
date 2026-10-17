"""GDPR persistence rehearsal on GitHub's isolated PostgreSQL only.

The strict allowlist is checked BEFORE engine creation; never query Render.
All records and actor identities in this fixture are synthetic.
"""
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.app.privacy_case_store import create_request, get_request, update_request
from backend.tests.test_instagram_postgres_isolation import require_ephemeral_ci_postgres


@pytest.fixture(scope="module")
def ephemeral_privacy_engine():
    url = os.environ.get("SENDRO_INSTAGRAM_PG_CI_URL")
    if not url:
        pytest.skip("Requires isolated GitHub Actions PostgreSQL")
    approved_url = require_ephemeral_ci_postgres(url, os.environ)
    engine = create_engine(approved_url)
    try:
        with engine.begin() as db:
            db.exec_driver_sql("CREATE TABLE IF NOT EXISTS public.users (id INTEGER PRIMARY KEY)")
            db.exec_driver_sql("ALTER TABLE public.users ADD COLUMN IF NOT EXISTS disabled BOOLEAN NOT NULL DEFAULT FALSE")
            # Existing Instagram schema is reused in this *disposable* CI DB.
            db.execute(text("""
                INSERT INTO public.sendro_tenants(id, slug, display_name)
                VALUES (989901, 'privacy-ci-tenant-a', 'Synthetic A'),
                       (989902, 'privacy-ci-tenant-b', 'Synthetic B')
                ON CONFLICT DO NOTHING
            """))
            db.execute(text("""
                INSERT INTO public.users(id,disabled)
                VALUES (989901, FALSE), (989902, FALSE)
                ON CONFLICT DO NOTHING
            """))
            db.execute(text("""
                INSERT INTO public.sendro_tenant_users
                    (tenant_id, user_id, member_role, is_active)
                VALUES (989901,989901,'owner',TRUE),
                       (989902,989902,'admin',TRUE)
                ON CONFLICT DO NOTHING
            """))
        migration = (
            Path(__file__).parents[2] / "ops" / "db" /
            "20261017_privacy_cases_MANUAL_ONLY.sql"
        ).read_text(encoding="utf-8")
        # psycopg ClientCursor supports a whole operator-authored SQL script.
        raw = engine.raw_connection()
        try:
            from psycopg import ClientCursor
            raw.rollback()
            with ClientCursor(raw.driver_connection) as cursor:
                cursor.execute(migration)
            raw.commit()
        finally:
            raw.close()
        yield engine
    finally:
        engine.dispose()


def test_case_persistence_and_tenant_isolation_in_real_postgres(ephemeral_privacy_engine):
    engine = ephemeral_privacy_engine
    with Session(engine) as db:
        initial = create_request(db, tenant_id=989901, user_id=989901,
                                 channel="whatsapp")
        ref = initial["case_ref"]
        assert initial["status"] == "received"
        assert initial["erasure_enabled"] is False
    with Session(engine) as db:
        assert update_request(db, tenant_id=989901, user_id=989901,
                              ref=ref, action="identity",
                              attested=True)["status"] == "identity_checked"
    with Session(engine) as db:
        assert get_request(db, tenant_id=989901, user_id=989901,
                           ref=ref)["audit_events"] == 2
        with pytest.raises(LookupError):
            get_request(db, tenant_id=989902, user_id=989902, ref=ref)
        with pytest.raises(PermissionError):
            get_request(db, tenant_id=989901, user_id=989902, ref=ref)


def test_audit_events_are_immutable_even_if_sql_attempts_modification(ephemeral_privacy_engine):
    engine = ephemeral_privacy_engine
    with engine.connect() as db:
        with pytest.raises(DBAPIError):
            with db.begin():
                db.execute(text("""
                    UPDATE public.sendro_privacy_case_events
                    SET action='scope_reviewed' WHERE tenant_id=989901
                """))
    with engine.connect() as db:
        with pytest.raises(DBAPIError):
            with db.begin():
                db.execute(text("""
                    DELETE FROM public.sendro_privacy_case_events
                    WHERE tenant_id=989901
                """))
    with engine.connect() as db:
        assert db.execute(text("""
            SELECT count(*) FROM public.sendro_privacy_case_events
            WHERE tenant_id=989901
        """)).scalar_one() == 2
