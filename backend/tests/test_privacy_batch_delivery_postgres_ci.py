"""Disposable PostgreSQL ONLY: controlled erasure rehearsal for Sendro batch history.

This is intentionally a pytest-only fixture, NOT an app module, operator script,
scheduled task, or production erasure implementation. The synthetic
ci_verified_batch_scope table DOES NOT exist in Sendro and cannot prove real
legacy WhatsApp tenant ownership. Deletion applies only to hand-picked
fabricated batch items in a dedicated short-lived GitHub Actions database.
"""
import os
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.app.privacy_batch_delivery_retention import (
    DeliveryHistoryRetentionSnapshot,
    review_delivery_history,
)
from backend.app.privacy_retention import twelve_month_cutoff


CI_URL = "SENDRO_BATCH_RETENTION_PG_CI_URL"
CI_GATE = "SENDRO_BATCH_RETENTION_PG_CI_APPROVAL"
CI_APPROVAL = "ephemeral-batch-retention-only"
CI_HOST = "127.0.0.1"
CI_PORT = 55443
CI_DATABASE = "sendro_batch_retention_ci"
CI_USER = "sendro_batch_ci"
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
CUTOFF = twelve_month_cutoff(NOW)

# These IDs are invented and must not be copied into any real database.
TENANT_A = 401
TENANT_B = 402
BATCH_A = 601
BATCH_B = 602
BATCH_UNVERIFIED = 603
BATCH_HOLD = 604

# All SQL below is limited to this pytest fixture. It is NOT designed for
# deploying against the production schema. There is no runtime integration.
DELETE_APPROVED_ONE_ITEM = text("""
DELETE FROM public.template_batch_items AS item
WHERE item.id = :item_id
  AND item.batch_db_id = :batch_id
  AND item.created_at <= :cutoff
  AND EXISTS (
    SELECT 1
    FROM public.ci_verified_batch_scope AS scope
    WHERE scope.batch_db_id = item.batch_db_id
      AND scope.tenant_id = :tenant_id
      AND scope.ownership_verified IS TRUE
      AND scope.controller_instructions_verified IS TRUE
      AND scope.related_records_reviewed IS TRUE
      AND scope.backup_restore_plan_reviewed IS TRUE
      AND scope.legal_hold IS FALSE
  )
RETURNING item.id
""")


def require_disposable_batch_pg(url, env):
    """Refuse everything except the unique ephemeral Actions local instance."""
    try:
        candidate = make_url(url)
    except Exception as exc:
        raise RuntimeError("Refusing non-disposable batch PostgreSQL") from exc
    if not (
        env.get("GITHUB_ACTIONS") == "true"
        and env.get(CI_GATE) == CI_APPROVAL
        and candidate.drivername == "postgresql+psycopg"
        and candidate.host == CI_HOST
        and candidate.port == CI_PORT
        and candidate.database == CI_DATABASE
        and candidate.username == CI_USER
        and candidate.password == "synthetic-batch-password"
        and not candidate.query
    ):
        raise RuntimeError("Refusing non-disposable batch PostgreSQL")
    return candidate


@pytest.fixture(scope="module")
def synthetic_pg():
    url = os.environ.get(CI_URL)
    if url is None:
        pytest.skip("Runs only in a dedicated GitHub Actions PostgreSQL service")
    safe_url = require_disposable_batch_pg(url, os.environ)
    engine = create_engine(
        safe_url,
        connect_args={"options": "-c statement_timeout=6000 -c lock_timeout=1500"},
    )
    try:
        with engine.begin() as conn:
            # Minimal contract of REAL FK direction, with all fake data.
            # Intentionally does NOT create realistic customer data or users.
            conn.exec_driver_sql("""
                CREATE TABLE public.conversations(
                    id BIGINT PRIMARY KEY,
                    contact_phone TEXT NOT NULL)
            """)
            conn.exec_driver_sql("""
                CREATE TABLE public.messages(
                    id BIGINT PRIMARY KEY,
                    conversation_id BIGINT NOT NULL REFERENCES public.conversations(id),
                    content TEXT NOT NULL)
            """)
            conn.exec_driver_sql("""
                CREATE TABLE public.template_batches(
                    id BIGINT PRIMARY KEY,
                    batch_id TEXT NOT NULL UNIQUE,
                    batch_label TEXT,
                    created_at TIMESTAMP NOT NULL)
            """)
            conn.exec_driver_sql("""
                CREATE TABLE public.template_batch_items(
                    id BIGINT PRIMARY KEY,
                    batch_db_id BIGINT NOT NULL REFERENCES public.template_batches(id),
                    created_at TIMESTAMP NOT NULL,
                    whatsapp_status_updated_at TIMESTAMP NULL,
                    guest_name TEXT NULL,
                    phone TEXT NULL,
                    reservation_number TEXT NULL,
                    conversation_id BIGINT NULL REFERENCES public.conversations(id),
                    message_id BIGINT NULL REFERENCES public.messages(id))
            """)
            # SYNTHETIC ONLY approval/ownership evidence. Not present in live DB.
            conn.exec_driver_sql("""
                CREATE TABLE public.ci_verified_batch_scope(
                    batch_db_id BIGINT PRIMARY KEY REFERENCES public.template_batches(id),
                    tenant_id BIGINT NOT NULL,
                    ownership_verified BOOLEAN NOT NULL,
                    controller_instructions_verified BOOLEAN NOT NULL,
                    related_records_reviewed BOOLEAN NOT NULL,
                    backup_restore_plan_reviewed BOOLEAN NOT NULL,
                    legal_hold BOOLEAN NULL)
            """)
            conn.execute(text("""
                INSERT INTO public.conversations(id,contact_phone)
                VALUES (701, 'fictional-A'), (702, 'fictional-B')
            """))
            conn.execute(text("""
                INSERT INTO public.messages(id,conversation_id,content)
                VALUES (801,701,'fabricated test message'),
                       (802,702,'fabricated second message')
            """))
            conn.execute(text("""
                INSERT INTO public.template_batches(id,batch_id,batch_label,created_at)
                VALUES (601,'batch-fixture-A','Synthetic A','2025-01-01'),
                       (602,'batch-fixture-B','Synthetic B','2025-01-01'),
                       (603,'batch-fixture-unknown','Unknown','2025-01-01'),
                       (604,'batch-fixture-hold','Hold','2025-01-01')
            """))
            conn.execute(text("""
                INSERT INTO public.ci_verified_batch_scope(
                    batch_db_id,tenant_id,ownership_verified,
                    controller_instructions_verified,related_records_reviewed,
                    backup_restore_plan_reviewed,legal_hold)
                VALUES
                (601,401,TRUE,TRUE,TRUE,TRUE,FALSE),
                (602,402,TRUE,TRUE,TRUE,TRUE,FALSE),
                (603,401,FALSE,TRUE,TRUE,TRUE,FALSE),
                (604,401,TRUE,TRUE,TRUE,TRUE,TRUE)
            """))
            conn.execute(text("""
                INSERT INTO public.template_batch_items(
                    id,batch_db_id,created_at,whatsapp_status_updated_at,
                    guest_name,phone,reservation_number,conversation_id,message_id
                ) VALUES
                (901,601,'2025-06-11','2026-10-22','fabricated guest 1','synthetic 1','synthetic-order',701,801),
                (902,601,'2026-10-20',NULL,'fabricated guest 2','synthetic 2','synthetic-order',701,801),
                (903,602,'2025-06-11',NULL,'fabricated guest 3','synthetic 3','synthetic-order',702,802),
                (904,603,'2025-06-11',NULL,'fabricated guest 4','synthetic 4',NULL,NULL,NULL),
                (905,604,'2025-06-11',NULL,'fabricated guest 5','synthetic 5',NULL,NULL,NULL),
                (906,601,'2025-06-11',NULL,'fabricated guest 6','synthetic 6',NULL,NULL,NULL),
                (907,601,'2025-10-24',NULL,'fabricated guest 7','synthetic 7',NULL,NULL,NULL),
                (908,601,'2025-10-23 12:00:00',NULL,'fabricated guest 8','synthetic 8',NULL,NULL,NULL)
            """))
        yield engine
    finally:
        engine.dispose()


def counts(engine):
    with engine.connect() as db:
        return (
            db.execute(text("SELECT COUNT(*) FROM public.template_batch_items")).scalar_one(),
            db.execute(text("SELECT COUNT(*) FROM public.template_batches")).scalar_one(),
            db.execute(text("SELECT COUNT(*) FROM public.conversations")).scalar_one(),
            db.execute(text("SELECT COUNT(*) FROM public.messages")).scalar_one(),
        )


def delete_one(conn, *, item_id, batch_id=BATCH_A, tenant_id=TENANT_A):
    """CI-only explicit single synthetic item; transaction supplied by caller."""
    return conn.execute(DELETE_APPROVED_ONE_ITEM, {
        "item_id": item_id,
        "batch_id": batch_id,
        "tenant_id": tenant_id,
        "cutoff": CUTOFF.replace(tzinfo=None),  # Legacy PostgreSQL timestamp is UTC-naive
    }).scalars().all()


@pytest.mark.parametrize("bad_url", [
    "postgresql+psycopg://sendro_batch_ci:synthetic-batch-password@render.com:55443/sendro_batch_retention_ci",
    "postgresql+psycopg://sendro_batch_ci:synthetic-batch-password@127.0.0.1:5432/sendro_batch_retention_ci",
    "postgresql+psycopg://sendro_batch_ci:synthetic-batch-password@127.0.0.1:55443/sendro",
    "postgresql+psycopg://other:synthetic-batch-password@127.0.0.1:55443/sendro_batch_retention_ci",
    "postgresql+psycopg://sendro_batch_ci:wrong@127.0.0.1:55443/sendro_batch_retention_ci",
    "sqlite:///oops.sqlite",
])
def test_disposable_allowlist_rejects_wrong_targets(bad_url):
    with pytest.raises(RuntimeError, match="non-disposable"):
        require_disposable_batch_pg(
            bad_url, {"GITHUB_ACTIONS": "true", CI_GATE: CI_APPROVAL}
        )


def test_missing_approval_blocks_before_engine():
    url = ("postgresql+psycopg://sendro_batch_ci:synthetic-batch-password"
           "@127.0.0.1:55443/sendro_batch_retention_ci")
    for env in ({}, {"GITHUB_ACTIONS": "true"}, {CI_GATE: CI_APPROVAL}):
        with pytest.raises(RuntimeError):
            require_disposable_batch_pg(url, env)


def test_classification_uses_creation_even_after_late_delivery_update():
    row = DeliveryHistoryRetentionSnapshot(
        created_at=datetime(2025, 6, 11, 9),
        delivery_status_updated_at=datetime(2026, 10, 22),
        tenant_ownership_verified=True,
        controller_instructions_verified=True,
        related_records_reviewed=True,
        backup_restore_plan_reviewed=True,
        legal_hold=False,
    )
    assert review_delivery_history(row, as_of=NOW) == (
        "candidate_for_manual_erasure_review"
    )


def test_isolated_postgres_real_fk_and_age_scope_with_rollback(synthetic_pg):
    initial = counts(synthetic_pg)
    assert initial == (8, 4, 2, 2)
    # Real SQL actually erases two invented eligible batch rows, then rolls
    # back the ENTIRE transaction before returning from this test.
    with synthetic_pg.connect() as db:
        txn = db.begin()
        try:
            assert delete_one(db, item_id=901) == [901]
            assert delete_one(db, item_id=906) == [906]
            assert db.execute(text(
                "SELECT COUNT(*) FROM public.template_batch_items"
            )).scalar_one() == 6
            # Deleting ONLY a child batch item keeps the parent, message and
            # conversation, also keeping the one younger sibling.
            assert db.execute(text("""
                SELECT COUNT(*) FROM public.template_batch_items
                WHERE id=902
            """)).scalar_one() == 1
            assert db.execute(text(
                "SELECT COUNT(*) FROM public.messages"
            )).scalar_one() == 2
            assert db.execute(text(
                "SELECT COUNT(*) FROM public.conversations"
            )).scalar_one() == 2
            assert db.execute(text(
                "SELECT COUNT(*) FROM public.template_batches"
            )).scalar_one() == 4
        finally:
            txn.rollback()
    assert counts(synthetic_pg) == initial


@pytest.mark.parametrize("item_id,batch_id,tenant_id", [
    (902, BATCH_A, TENANT_A),     # recent
    (903, BATCH_A, TENANT_A),     # belongs to other company
    (903, BATCH_B, TENANT_A),     # wrong tenant
    (904, BATCH_UNVERIFIED, TENANT_A),  # unknown ownership
    (905, BATCH_HOLD, TENANT_A),        # hold
    (907, BATCH_A, TENANT_A),     # just after deadline
    (9999, BATCH_A, TENANT_A),    # missing record
])
def test_recent_other_tenant_unknown_and_hold_fail_closed(
    synthetic_pg, item_id, batch_id, tenant_id
):
    before = counts(synthetic_pg)
    with synthetic_pg.connect() as db:
        txn = db.begin()
        try:
            assert delete_one(db, item_id=item_id,
                              batch_id=batch_id, tenant_id=tenant_id) == []
        finally:
            txn.rollback()
    assert counts(synthetic_pg) == before


def test_exact_calendar_boundary_and_prior_provider_status(synthetic_pg):
    with synthetic_pg.connect() as db:
        txn = db.begin()
        try:
            # Exact 12-month inclusive cutoff, and no dependent message.
            assert delete_one(db, item_id=908) == [908]
        finally:
            txn.rollback()


def test_transaction_rolls_back_if_second_step_fails(synthetic_pg):
    before = counts(synthetic_pg)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with synthetic_pg.begin() as db:
            assert delete_one(db, item_id=901) == [901]
            raise RuntimeError("synthetic failure: cancel atomic operation")
    assert counts(synthetic_pg) == before


def test_no_application_write_path_or_real_ownership_claim():
    from inspect import getsource
    fixture = getsource(synthetic_pg.__wrapped__)
    assert "ci_verified_batch_scope" in fixture  # DOES NOT exist live
    assert "get_db(" not in fixture and "FastAPI(" not in fixture
    assert "DATABASE_URL" not in fixture
    assert "os.environ.get(CI_URL)" in fixture
    assert "app.include_router(" not in fixture


def test_only_explicitly_scoped_id_not_bulk_delete(synthetic_pg):
    with synthetic_pg.connect() as db:
        txn = db.begin()
        try:
            # A single hand-picked orphan with verified synthetic scope.
            assert delete_one(db, item_id=906) == [906]
            # A second orphan is unknown or legally held, still preserved.
            assert db.execute(text("""
                SELECT COUNT(*) FROM public.template_batch_items
                WHERE id IN (904, 905)
            """)).scalar_one() == 2
        finally:
            txn.rollback()
