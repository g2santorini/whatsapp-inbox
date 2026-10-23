"""CI-only synthetic PostgreSQL proof of batch ownership and parent cleanup.

Never execute this against Sendro, Render or staging; the unique database
allowlist is validated before an engine exists. Provenance tables below are
fabricated for adversarial tests. There is no live verified batch ownership
registry and these SQL statements are NOT production cleanup instructions.
"""
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text

from backend.tests.test_privacy_batch_delivery_postgres_ci import (
    CI_URL, require_disposable_batch_pg,
)
from backend.app.privacy_retention import twelve_month_cutoff

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
CUTOFF = twelve_month_cutoff(NOW).replace(tzinfo=None)
SCHEMA = "ci_batch_provenance_rehearsal"
A, B = 401, 402

# Explicit single-row DELETE.  A batch with *any* unverified or conflicting
# linked child fails closed, including for an otherwise-unlinked sibling.
DELETE_ONE_CHILD = text("""
DELETE FROM ci_batch_provenance_rehearsal.batch_items AS item
WHERE item.id = :item_id
  AND item.batch_id = :batch_id
  AND item.created_at <= :cutoff
  AND EXISTS (
    SELECT 1 FROM ci_batch_provenance_rehearsal.verified_batch_scope AS s
    WHERE s.batch_id = item.batch_id
      AND s.tenant_id = :tenant_id
      AND s.ownership_verified IS TRUE
      AND s.controller_instructions_verified IS TRUE
      AND s.related_records_reviewed IS TRUE
      AND s.backup_restore_plan_reviewed IS TRUE
      AND s.legal_hold IS FALSE
  )
  AND NOT EXISTS (
    SELECT 1 FROM ci_batch_provenance_rehearsal.batch_items AS sibling
    WHERE sibling.batch_id = item.batch_id AND (
      (sibling.conversation_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM ci_batch_provenance_rehearsal.verified_conversation_scope AS c
        WHERE c.conversation_id = sibling.conversation_id
          AND c.tenant_id = :tenant_id AND c.ownership_verified IS TRUE
      ))
      OR
      (sibling.message_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM ci_batch_provenance_rehearsal.messages AS m
        JOIN ci_batch_provenance_rehearsal.verified_conversation_scope AS c
          ON c.conversation_id = m.conversation_id
        WHERE m.id = sibling.message_id
          AND c.tenant_id = :tenant_id AND c.ownership_verified IS TRUE
          AND (
            sibling.conversation_id IS NULL
            OR sibling.conversation_id = m.conversation_id
          )
      ))
    )
  )
RETURNING item.id
""")

DELETE_EMPTY_PARENT = text("""
DELETE FROM ci_batch_provenance_rehearsal.batches AS parent
WHERE parent.id = :batch_id
  AND parent.created_at <= :cutoff
  AND EXISTS (
    SELECT 1 FROM ci_batch_provenance_rehearsal.verified_batch_scope AS s
    WHERE s.batch_id = parent.id
      AND s.tenant_id = :tenant_id
      AND s.ownership_verified IS TRUE
      AND s.controller_instructions_verified IS TRUE
      AND s.related_records_reviewed IS TRUE
      AND s.backup_restore_plan_reviewed IS TRUE
      AND s.legal_hold IS FALSE
  )
  AND NOT EXISTS (
    SELECT 1 FROM ci_batch_provenance_rehearsal.batch_items AS item
    WHERE item.batch_id = parent.id
  )
RETURNING parent.id
""")


@pytest.fixture(scope="module")
def sandbox_pg():
    url = os.environ.get(CI_URL)
    if not url:
        pytest.skip("Disposable GitHub PostgreSQL service required")
    # This existing guard checks GitHub Actions, separate approved CI flag,
    # exact loopback host/port, database, username and password.
    approved = require_disposable_batch_pg(url, os.environ)
    engine = create_engine(
        approved, connect_args={
            "options": "-c statement_timeout=6000 -c lock_timeout=1500"
        },
    )
    try:
        with engine.begin() as db:
            db.exec_driver_sql(
                "CREATE SCHEMA ci_batch_provenance_rehearsal"
            )
            db.exec_driver_sql("""
                CREATE TABLE ci_batch_provenance_rehearsal.conversations(
                    id INTEGER PRIMARY KEY, contact_phone TEXT)
            """)
            db.exec_driver_sql("""
                CREATE TABLE ci_batch_provenance_rehearsal.messages(
                    id INTEGER PRIMARY KEY,
                    conversation_id INTEGER NOT NULL
                      REFERENCES ci_batch_provenance_rehearsal.conversations(id),
                    content TEXT)
            """)
            db.exec_driver_sql("""
                CREATE TABLE ci_batch_provenance_rehearsal.batches(
                    id INTEGER PRIMARY KEY, label TEXT,
                    created_at TIMESTAMP NOT NULL)
            """)
            db.exec_driver_sql("""
                CREATE TABLE ci_batch_provenance_rehearsal.batch_items(
                    id INTEGER PRIMARY KEY,
                    batch_id INTEGER NOT NULL
                      REFERENCES ci_batch_provenance_rehearsal.batches(id),
                    created_at TIMESTAMP NOT NULL,
                    status_updated_at TIMESTAMP,
                    guest_name TEXT,
                    conversation_id INTEGER
                      REFERENCES ci_batch_provenance_rehearsal.conversations(id),
                    message_id INTEGER
                      REFERENCES ci_batch_provenance_rehearsal.messages(id))
            """)
            db.exec_driver_sql("""
                CREATE TABLE ci_batch_provenance_rehearsal.verified_batch_scope(
                    batch_id INTEGER PRIMARY KEY
                      REFERENCES ci_batch_provenance_rehearsal.batches(id),
                    tenant_id INTEGER NOT NULL,
                    ownership_verified BOOLEAN NOT NULL,
                    controller_instructions_verified BOOLEAN NOT NULL,
                    related_records_reviewed BOOLEAN NOT NULL,
                    backup_restore_plan_reviewed BOOLEAN NOT NULL,
                    legal_hold BOOLEAN)
            """)
            db.exec_driver_sql("""
                CREATE TABLE ci_batch_provenance_rehearsal.verified_conversation_scope(
                    conversation_id INTEGER PRIMARY KEY
                      REFERENCES ci_batch_provenance_rehearsal.conversations(id),
                    tenant_id INTEGER NOT NULL,
                    ownership_verified BOOLEAN NOT NULL)
            """)
            db.execute(text("""
                INSERT INTO ci_batch_provenance_rehearsal.conversations(id,contact_phone)
                VALUES (201,'fake-a'), (202,'fake-b'), (203,'fake-unverified')
            """))
            db.execute(text("""
                INSERT INTO ci_batch_provenance_rehearsal.messages(id,conversation_id,content)
                VALUES (301,201,'synthetic-A'), (302,202,'synthetic-B')
            """))
            db.execute(text("""
                INSERT INTO ci_batch_provenance_rehearsal.verified_conversation_scope(
                    conversation_id,tenant_id,ownership_verified)
                VALUES (201,401,TRUE), (202,402,TRUE), (203,401,FALSE)
            """))
            db.execute(text("""
                INSERT INTO ci_batch_provenance_rehearsal.batches(id,label,created_at)
                VALUES (1001,'old A with young sibling','2025-01-01'),
                       (1002,'old B','2025-01-01'),
                       (1003,'unknown owner','2025-01-01'),
                       (1004,'legal hold','2025-01-01'),
                       (1005,'complete old A','2025-01-01'),
                       (1006,'mixed parent','2025-01-01'),
                       (1007,'empty unverified','2025-01-01'),
                       (1008,'newly created empty A','2026-10-01')
            """))
            db.execute(text("""
                INSERT INTO ci_batch_provenance_rehearsal.verified_batch_scope(
                    batch_id,tenant_id,ownership_verified,
                    controller_instructions_verified,related_records_reviewed,
                    backup_restore_plan_reviewed,legal_hold)
                VALUES (1001,401,TRUE,TRUE,TRUE,TRUE,FALSE),
                       (1002,402,TRUE,TRUE,TRUE,TRUE,FALSE),
                       (1003,401,FALSE,TRUE,TRUE,TRUE,FALSE),
                       (1004,401,TRUE,TRUE,TRUE,TRUE,TRUE),
                       (1005,401,TRUE,TRUE,TRUE,TRUE,FALSE),
                       (1006,401,TRUE,TRUE,TRUE,TRUE,FALSE),
                       (1007,401,FALSE,TRUE,TRUE,TRUE,FALSE),
                       (1008,401,TRUE,TRUE,TRUE,TRUE,FALSE)
            """))
            db.execute(text("""
                INSERT INTO ci_batch_provenance_rehearsal.batch_items(
                    id,batch_id,created_at,status_updated_at,
                    guest_name,conversation_id,message_id)
                VALUES
                  (501,1001,'2025-06-11','2026-10-22','fake old A',201,301),
                  (502,1001,'2026-10-20',NULL,'fake young A',201,301),
                  (503,1002,'2025-06-11',NULL,'fake old B',202,302),
                  (504,1003,'2025-06-11',NULL,'fake unknown',NULL,NULL),
                  (505,1004,'2025-06-11',NULL,'fake held',NULL,NULL),
                  (506,1005,'2025-06-11',NULL,'fake last old child',201,301),
                  (507,1006,'2025-06-11',NULL,'fake orphan in mixed',NULL,NULL),
                  (508,1006,'2025-06-11',NULL,'fake cross tenant',202,302),
                  (509,1006,'2025-06-11',NULL,'fake mismatch',201,302),
                  (510,1006,'2025-06-11',NULL,'fake unverified',203,NULL),
                  (511,1006,'2025-06-11',NULL,'fake message only B',NULL,302)
            """))
        yield engine
    finally:
        # Only a temporary CI schema inside an allowlisted ephemeral database.
        with engine.begin() as db:
            db.exec_driver_sql(
                "DROP SCHEMA ci_batch_provenance_rehearsal CASCADE"
            )
        engine.dispose()


def counts(db):
    return tuple(db.execute(text(
        "SELECT COUNT(*) FROM ci_batch_provenance_rehearsal." + table
    )).scalar_one() for table in (
        "batch_items", "batches", "conversations", "messages",
    ))


def remove_child(db, row, batch, tenant=A):
    return db.execute(DELETE_ONE_CHILD, {
        "item_id": row, "batch_id": batch, "tenant_id": tenant,
        "cutoff": CUTOFF,
    }).scalars().all()


def remove_parent(db, batch, tenant=A):
    return db.execute(DELETE_EMPTY_PARENT, {
        "batch_id": batch, "tenant_id": tenant, "cutoff": CUTOFF,
    }).scalars().all()


def test_ambiguous_mixed_batch_blocks_even_orphan_older_rows(sandbox_pg):
    with sandbox_pg.connect() as db:
        tx = db.begin()
        try:
            original = counts(db)
            for row in (507, 508, 509, 510, 511):
                assert remove_child(db, row, batch=1006, tenant=A) == []
            assert counts(db) == original
        finally:
            tx.rollback()


def test_independently_verified_parent_not_enough_for_linked_other_company(
    sandbox_pg,
):
    with sandbox_pg.connect() as db:
        tx = db.begin()
        try:
            assert remove_child(db, 503, batch=1002, tenant=A) == []
            assert remove_child(db, 503, batch=1001, tenant=A) == []
            assert remove_child(db, 503, batch=1002, tenant=B) == [503]
            assert counts(db)[2:] == (3, 2)
        finally:
            tx.rollback()


def test_old_item_only_leaves_younger_sibling_and_live_messages(sandbox_pg):
    with sandbox_pg.connect() as db:
        tx = db.begin()
        try:
            before = counts(db)
            assert remove_child(db, 501, batch=1001) == [501]
            assert remove_parent(db, batch=1001) == []
            assert db.execute(text("""
                SELECT COUNT(*) FROM ci_batch_provenance_rehearsal.batch_items
                WHERE id=502
            """)).scalar_one() == 1
            assert counts(db) == (before[0] - 1, before[1],
                                  before[2], before[3])
        finally:
            tx.rollback()


def test_last_old_item_and_parent_are_both_removed_atomically(sandbox_pg):
    with sandbox_pg.connect() as db:
        tx = db.begin()
        try:
            before = counts(db)
            assert remove_parent(db, batch=1005) == []
            assert remove_child(db, 506, batch=1005) == [506]
            assert remove_parent(db, batch=1005) == [1005]
            assert counts(db) == (before[0] - 1, before[1] - 1,
                                  before[2], before[3])
        finally:
            tx.rollback()


def test_unverified_held_or_young_parent_never_cleaned(sandbox_pg):
    with sandbox_pg.connect() as db:
        tx = db.begin()
        try:
            assert remove_child(db, 504, batch=1003) == []
            assert remove_child(db, 505, batch=1004) == []
            assert remove_parent(db, batch=1007) == []
            assert remove_parent(db, batch=1008) == []
            assert remove_parent(db, batch=1004) == []
        finally:
            tx.rollback()


def test_failure_rolls_back_child_and_parent_in_one_transaction(sandbox_pg):
    with sandbox_pg.connect() as db:
        before = counts(db)
    with pytest.raises(RuntimeError, match="simulated crash"):
        with sandbox_pg.begin() as db:
            assert remove_child(db, 506, batch=1005) == [506]
            assert remove_parent(db, batch=1005) == [1005]
            raise RuntimeError("simulated crash")
    with sandbox_pg.connect() as db:
        assert counts(db) == before


def test_only_ci_tables_and_no_runtime_wiring():
    from inspect import getsource
    src = getsource(sandbox_pg.__wrapped__)
    assert "require_disposable_batch_pg(url, os.environ)" in src
    assert "CREATE TABLE ci_batch_provenance_rehearsal" in src
    assert "DATABASE_URL" not in src
    assert "app.include_router" not in src
    assert "get_db(" not in src
