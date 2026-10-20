"""Isolated PostgreSQL rehearsal of the *real* manual WhatsApp ownership DDL.

All INSERT/UPDATE/DELETE in this file affect ONLY the disposable PostgreSQL 16
container in its own GitHub Actions job.  It must never connect to Render or
use DATABASE_URL.  No real contacts, tokens, case records, or Meta calls.
There is NO runtime/backfill implementation or authorization in this test.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from backend.app.privacy_whatsapp_tenant_links import (
    inspect_mapped_whatsapp,
    whatsapp_links_enabled,
    WHATSAPP_FLAG,
    WHATSAPP_VALUE,
)


CI_URL_ENV = "SENDRO_WHATSAPP_PG_CI_URL"
CI_GATE_ENV = "SENDRO_WHATSAPP_PG_CI_APPROVAL"
EXPECTED_GATE = "ephemeral-whatsapp-postgres-only"
EXPECTED_DB = "sendro_wa_ci"
EXPECTED_USER = "sendro_wa_ci"
EXPECTED_PORT = 55440
TENANT_A = 71
TENANT_B = 72
REVIEWER_A = 171
REVIEWER_B = 172
STAMP = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
FAKE_EVIDENCE_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
FAKE_EVIDENCE_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def require_disposable_whatsapp_pg(url, env):
    """Allowlist a uniquely named *local ephemeral* CI DB before any connect."""
    candidate = make_url(url)
    if not (
        env.get("GITHUB_ACTIONS") == "true"
        and env.get(CI_GATE_ENV) == EXPECTED_GATE
        and candidate.drivername == "postgresql+psycopg"
        and candidate.host == "127.0.0.1"
        and candidate.port == EXPECTED_PORT
        and candidate.database == EXPECTED_DB
        and candidate.username == EXPECTED_USER
    ):
        raise RuntimeError("Refusing non-disposable WhatsApp PostgreSQL")
    return candidate


# This is deliberately test-only SQL and requires reviewer + evidence fields.
# There is no bulk INSERT or way to target Render.
LINK_ONE_SQL = text("""
    INSERT INTO public.sendro_privacy_legacy_whatsapp_links (
        conversation_id, tenant_id, verified_by_user_id,
        verification_method, evidence_ref, verified_at
    ) VALUES (
        :conversation_id, :tenant_id, :reviewer,
        'manual-owner-review', CAST(:evidence_ref AS uuid), :verified_at
    )
""")


def link_values(conversation_id=10001, *, tenant_id=TENANT_A,
                reviewer=REVIEWER_A, evidence_ref=FAKE_EVIDENCE_A):
    return {
        "conversation_id": conversation_id, "tenant_id": tenant_id,
        "reviewer": reviewer, "evidence_ref": evidence_ref,
        "verified_at": STAMP,
    }


def count_rows(engine, table):
    # The sole callers use hard-coded test table names.
    with engine.connect() as db:
        return db.execute(text("SELECT count(*) FROM public." + table)).scalar_one()


@pytest.fixture(scope="module")
def pg_engine():
    url = os.environ.get(CI_URL_ENV)
    if not url:
        pytest.skip("Only runnable inside disposable GitHub Actions PostgreSQL")
    safe_url = require_disposable_whatsapp_pg(url, os.environ)
    engine = create_engine(
        safe_url, connect_args={"options": "-c lock_timeout=2000 -c statement_timeout=10000"}
    )
    try:
        with engine.begin() as db:
            db.exec_driver_sql("""
                CREATE TABLE public.conversations (
                    id INTEGER PRIMARY KEY, contact_phone TEXT
                )
            """)
            db.exec_driver_sql("""
                CREATE TABLE public.messages (
                    id INTEGER PRIMARY KEY,
                    conversation_id INTEGER REFERENCES public.conversations(id),
                    media_id TEXT, content TEXT
                )
            """)
            db.exec_driver_sql("""
                CREATE TABLE public.sendro_tenants (
                    id BIGINT PRIMARY KEY, display_name TEXT NOT NULL
                )
            """)
            db.exec_driver_sql("""
                CREATE TABLE public.sendro_tenant_users (
                    tenant_id BIGINT NOT NULL REFERENCES public.sendro_tenants(id),
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (tenant_id, user_id)
                )
            """)
            db.execute(text("""
                INSERT INTO public.sendro_tenants(id, display_name)
                VALUES (71, 'Synthetic Business A'), (72, 'Synthetic Business B')
            """))
            db.execute(text("""
                INSERT INTO public.sendro_tenant_users (tenant_id, user_id)
                VALUES (71, 171), (72, 172)
            """))
            db.execute(text("""
                INSERT INTO public.conversations (id, contact_phone)
                VALUES (10001, '+30000000001'), (10002, '+30000000002'),
                       (10003, '+30000000003'), (10004, '+30000000004'),
                       (10005, '+30000000005'), (10006, '+30000000006')
            """))
            db.execute(text("""
                INSERT INTO public.messages(id, conversation_id, media_id, content)
                VALUES (20001, 10001, NULL, 'fabricated hello'),
                       (20002, 10001, 'synthetic-media-identifier', NULL),
                       (20003, 10002, NULL, 'fabricated second')
            """))

        # Execute the exact existing operator-authored SQL from the repository,
        # NEVER a simplified approximation of its constraints.
        migration = (Path(__file__).parents[2] / "ops" / "db" /
                     "20261019_privacy_legacy_whatsapp_ownership_MANUAL_ONLY.sql")
        ddl = migration.read_text(encoding="utf-8")
        assert "CREATE TABLE public.sendro_privacy_legacy_whatsapp_links" in ddl
        assert "BEGIN;" in ddl and "COMMIT;" in ddl
        from psycopg import ClientCursor
        raw = engine.raw_connection()
        try:
            raw.rollback()
            with ClientCursor(raw.driver_connection) as cursor:
                cursor.execute(ddl)
            raw.commit()
        finally:
            raw.close()
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def reset_synthetic_links(request):
    if "pg_engine" not in request.fixturenames:
        yield
        return
    engine = request.getfixturevalue("pg_engine")
    # Clear only this throwaway container's synthetic mapping table.
    with engine.begin() as db:
        db.execute(text("DELETE FROM public.sendro_privacy_legacy_whatsapp_links"))
    yield


@pytest.mark.parametrize("candidate", [
    "postgresql+psycopg://sendro_wa_ci:fake@outside.render.com:55440/sendro_wa_ci",
    "postgresql+psycopg://sendro_wa_ci:fake@127.0.0.1:5432/sendro_wa_ci",
    "postgresql+psycopg://sendro_wa_ci:fake@127.0.0.1:55440/sendro",
    "postgresql+psycopg://wrong_user:fake@127.0.0.1:55440/sendro_wa_ci",
    "sqlite:///some_local_file.db",
])
def test_guard_rejects_external_and_mismatched_databases(candidate):
    with pytest.raises(RuntimeError, match="non-disposable"):
        require_disposable_whatsapp_pg(candidate, {
            "GITHUB_ACTIONS": "true", CI_GATE_ENV: EXPECTED_GATE,
        })


def test_guard_needs_both_ci_approvals_and_never_reads_database_url():
    sample = ("postgresql+psycopg://sendro_wa_ci:fake@127.0.0.1:"
              "55440/sendro_wa_ci")
    for environment in ({}, {"GITHUB_ACTIONS": "true"},
                        {CI_GATE_ENV: EXPECTED_GATE}):
        with pytest.raises(RuntimeError):
            require_disposable_whatsapp_pg(sample, environment)
    source = Path(__file__).read_text(encoding="utf-8")
    assert 'os.environ.get("DATABASE_URL")' not in source
    assert 'create_engine(os.environ' not in source


def test_exact_manual_migration_schema_and_no_automatic_owner(pg_engine):
    with pg_engine.connect() as db:
        constraints = db.execute(text("""
            SELECT conname, contype FROM pg_constraint
            WHERE conrelid = 'public.sendro_privacy_legacy_whatsapp_links'::regclass
        """)).all()
        indexes = db.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname='public'
              AND tablename='sendro_privacy_legacy_whatsapp_links'
        """)).scalars().all()
    names = {row.conname for row in constraints}
    assert "fk_privacy_legacy_whatsapp_reviewer" in names
    assert "ck_privacy_legacy_whatsapp_revocation_time" in names
    assert sum(row.contype == "f" for row in constraints) == 3
    assert sum(row.contype == "p" for row in constraints) == 1
    assert "idx_privacy_legacy_whatsapp_tenant" in indexes
    assert count_rows(pg_engine, "sendro_privacy_legacy_whatsapp_links") == 0
    assert whatsapp_links_enabled({}) is False
    assert whatsapp_links_enabled({WHATSAPP_FLAG: "enabled"}) is False
    assert whatsapp_links_enabled({WHATSAPP_FLAG: WHATSAPP_VALUE}) is True


def test_verified_exact_link_has_only_metadata_and_is_tenant_isolated(pg_engine):
    with pg_engine.begin() as db:
        db.execute(LINK_ONE_SQL, link_values())
    with Session(pg_engine) as session:
        result = inspect_mapped_whatsapp(session, tenant_id=TENANT_A,
                                         conversation_id=10001)
        assert result == {
            "platform": "whatsapp", "conversation_id": 10001,
            "messages": 2, "messages_with_media_metadata": 1,
            "partial_inventory": True, "linked_to_case": False,
            "erasure_enabled": False, "safe_to_delete_count": 0,
        }
        for tenant_id, conversation_id in (
            (TENANT_B, 10001), (TENANT_A, 10002),
            (TENANT_B, 10002), (TENANT_A, 99999)
        ):
            with pytest.raises(LookupError, match="not found for this company"):
                inspect_mapped_whatsapp(session, tenant_id=tenant_id,
                                        conversation_id=conversation_id)
    assert count_rows(pg_engine, "conversations") == 6
    assert count_rows(pg_engine, "messages") == 3


@pytest.mark.parametrize("bad", [
    {"conversation_id": 99999},  # no source conversation
    {"tenant_id": 9999},  # no registered company
    {"reviewer": REVIEWER_B},  # wrong-tenant verifier, composite FK
    {"evidence_ref": "not-a-uuid"},  # invalid evidence format
])
def test_invalid_evidence_tenant_or_conversation_rolls_back(pg_engine, bad):
    with pytest.raises(DBAPIError):
        with pg_engine.begin() as db:
            db.execute(LINK_ONE_SQL, {**link_values(), **bad})
    assert count_rows(pg_engine, "sendro_privacy_legacy_whatsapp_links") == 0


def test_duplicate_assignment_cannot_take_over_another_company(pg_engine):
    with pg_engine.begin() as db:
        db.execute(LINK_ONE_SQL, link_values())
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as db:
            db.execute(LINK_ONE_SQL, link_values(
                tenant_id=TENANT_B, reviewer=REVIEWER_B,
                evidence_ref=FAKE_EVIDENCE_B
            ))
    with pg_engine.connect() as db:
        row = db.execute(text("""
            SELECT tenant_id, verified_by_user_id, evidence_ref
            FROM public.sendro_privacy_legacy_whatsapp_links
            WHERE conversation_id = 10001
        """)).one()
        assert (row.tenant_id, row.verified_by_user_id) == (TENANT_A, REVIEWER_A)
        assert str(row.evidence_ref) == FAKE_EVIDENCE_A


def test_replay_noop_not_an_upsert_that_rewrites_verified_links(pg_engine):
    with pg_engine.begin() as db:
        db.execute(LINK_ONE_SQL, link_values())
        # The only safe replay mode: a conflicting claim does nothing.
        replay = db.execute(text("""
            INSERT INTO public.sendro_privacy_legacy_whatsapp_links (
                conversation_id, tenant_id, verified_by_user_id,
                verification_method, evidence_ref, verified_at
            ) VALUES (10001, 72, 172, 'manual-owner-review',
                      CAST(:evidence AS uuid), :stamp)
            ON CONFLICT (conversation_id) DO NOTHING
        """), {"evidence": FAKE_EVIDENCE_B, "stamp": STAMP})
        assert replay.rowcount == 0
    with pg_engine.connect() as db:
        assert db.execute(text("""
            SELECT tenant_id FROM public.sendro_privacy_legacy_whatsapp_links
            WHERE conversation_id = 10001
        """)).scalar_one() == TENANT_A


def test_revocation_hides_link_and_invalid_revocation_is_rejected(pg_engine):
    with pg_engine.begin() as db:
        db.execute(LINK_ONE_SQL, link_values())
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as db:
            db.execute(text("""
                UPDATE public.sendro_privacy_legacy_whatsapp_links
                SET revoked_at = :past WHERE conversation_id = 10001
            """), {"past": STAMP - timedelta(days=1)})
    with pg_engine.begin() as db:
        db.execute(text("""
            UPDATE public.sendro_privacy_legacy_whatsapp_links
            SET revoked_at = :later WHERE conversation_id = 10001
        """), {"later": STAMP + timedelta(hours=1)})
    with Session(pg_engine) as session:
        with pytest.raises(LookupError):
            inspect_mapped_whatsapp(session, tenant_id=TENANT_A,
                                    conversation_id=10001)


def test_partial_failure_rolls_back_the_whole_disposable_transaction(pg_engine):
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as db:
            db.execute(LINK_ONE_SQL, link_values(conversation_id=10001))
            db.execute(LINK_ONE_SQL, link_values(conversation_id=10002,
                                                 reviewer=REVIEWER_B))
    assert count_rows(pg_engine, "sendro_privacy_legacy_whatsapp_links") == 0
    assert count_rows(pg_engine, "messages") == 3


def test_readonly_transaction_rejects_any_mapping_insert(pg_engine):
    with pg_engine.connect() as db:
        with pytest.raises(DBAPIError):
            with db.begin():
                db.execute(text("SET TRANSACTION READ ONLY"))
                db.execute(LINK_ONE_SQL, link_values())
    assert count_rows(pg_engine, "sendro_privacy_legacy_whatsapp_links") == 0


def test_new_conversations_remain_unlinked_even_after_synthetic_review(pg_engine):
    with pg_engine.begin() as db:
        db.execute(LINK_ONE_SQL, link_values(conversation_id=10001))
    with Session(pg_engine) as session:
        with pytest.raises(LookupError):
            inspect_mapped_whatsapp(session, tenant_id=TENANT_A,
                                    conversation_id=10006)
    assert count_rows(pg_engine, "sendro_privacy_legacy_whatsapp_links") == 1
