"""PostgreSQL privacy preview tests: synthetic records in ephemeral GitHub CI."""
from datetime import datetime, timezone
import os

import pytest
from sqlalchemy import create_engine, text

from backend.app.privacy_retention_pg_preview import (
    BATCH_COUNTS_SQL, CONVERSATION_COUNTS_SQL, preview_disposable_postgres,
)
from backend.tests.test_instagram_postgres_isolation import require_ephemeral_ci_postgres


CI_FLAGS = {
    "GITHUB_ACTIONS": "true",
    "SENDRO_INSTAGRAM_PG_CI_APPROVAL": "ephemeral-local-service-only",
}
NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
OLD = datetime(2025, 8, 1, 12)
RECENT = datetime(2026, 9, 1, 12)


@pytest.fixture(scope="module")
def synthetic_pg():
    url = os.environ.get("SENDRO_INSTAGRAM_PG_CI_URL")
    if not url:
        pytest.skip("Disposable CI PostgreSQL required")
    approved_url = require_ephemeral_ci_postgres(url, os.environ)
    engine = create_engine(approved_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE public.conversations (
                  id BIGINT PRIMARY KEY, status TEXT, unread_count INTEGER,
                  assigned_to_user_id BIGINT, follow_up BOOLEAN,
                  created_at TIMESTAMP, updated_at TIMESTAMP,
                  last_message_at TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE public.messages (
                  id BIGINT PRIMARY KEY, conversation_id BIGINT,
                  created_at TIMESTAMP, content TEXT
                )
            """))
            conn.execute(text("""
                CREATE TABLE public.template_batch_items (
                  id BIGINT PRIMARY KEY, conversation_id BIGINT,
                  message_id BIGINT, guest_name TEXT, phone TEXT
                )
            """))
            rows = [
                (1, "archived", None, OLD),
                (2, "closed", None, OLD),
                (3, "closed", None, OLD),
                (4, "open", None, OLD),
                (5, "archived", 99, OLD),
                (6, "closed", None, RECENT),
                (7, "archived", None, OLD),
            ]
            for cid, status, assigned, stamp in rows:
                conn.execute(text("""
                    INSERT INTO public.conversations (
                      id, status, unread_count, assigned_to_user_id,
                      follow_up, created_at, updated_at, last_message_at
                    ) VALUES (:id, :status, 0, :assigned, false,
                              :stamp, :stamp, :stamp)
                """), {
                    "id": cid, "status": status,
                    "assigned": assigned, "stamp": stamp,
                })
            conn.execute(text("""
                INSERT INTO public.messages
                    (id, conversation_id, created_at, content)
                VALUES
                    (101, 1, :old, 'synthetic-old'),
                    (102, 2, :old, 'synthetic-linked'),
                    (103, 3, :recent, 'synthetic-newer')
            """), {"old": OLD, "recent": RECENT})
            conn.execute(text("""
                INSERT INTO public.template_batch_items (
                    id, conversation_id, message_id, guest_name, phone
                ) VALUES
                    (201, NULL, 102, 'Fabricated One', '00000001'),
                    (202, NULL, NULL, 'Fabricated Two', '00000002')
            """))
        yield engine
    finally:
        engine.dispose()


def run_readonly(engine, flags=CI_FLAGS):
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            return preview_disposable_postgres(conn, now=NOW, ci_flags=flags)


def test_counts_are_aggregate_only_and_detect_orphan_records(synthetic_pg):
    result = run_readonly(synthetic_pg)
    assert result["counts"] == {
        "total": 7,
        "active_or_unknown": 1,
        "pending_or_unknown": 1,
        "recent_or_unknown": 2,
        "older_inactive_clear_work": 3,
        "older_with_direct_batch_reference": 1,
        "older_without_direct_batch_reference": 2,
        "template_batch_items": 2,
        "unlinked_template_batch_items": 1,
    }
    assert result["eligible_for_deletion"] == 0
    assert result["deletion_enabled"] is False
    for private in ("Fabricated One", "00000002", "synthetic-old"):
        assert private not in str(result)


def test_refuses_bad_ci_gate(synthetic_pg):
    with synthetic_pg.connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            with pytest.raises(PermissionError):
                preview_disposable_postgres(conn, now=NOW, ci_flags={})


def test_refuses_writable_transaction(synthetic_pg):
    with synthetic_pg.connect() as conn:
        with conn.begin():
            with pytest.raises(PermissionError, match="read-only"):
                preview_disposable_postgres(conn, now=NOW, ci_flags=CI_FLAGS)


def test_source_queries_are_aggregate_selects_only():
    sql = (CONVERSATION_COUNTS_SQL + BATCH_COUNTS_SQL).lower()
    assert "count(*)" in sql
    assert "from public.conversations" in sql
    assert "from public.template_batch_items" in sql
    assert "from public.messages" in sql
    for forbidden in (
        "delete from", "truncate ", "update public.", "insert into",
        "drop table", "select *", "contact_phone", "guest_name",
        "m.content", "phone", "reservation_number",
    ):
        assert forbidden not in sql
