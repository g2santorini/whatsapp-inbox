"""Guardrails for the manual Sendro index rollout (no real DB connection)."""
from pathlib import Path
import re


BASE = Path(__file__).resolve().parents[2] / "ops" / "db"
MIGRATION = BASE / "20261013_manual_performance_indexes.sql"
VERIFY = BASE / "20261013_verify_performance_indexes.sql"


def _statements(path):
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("--")
    )


def test_index_rollout_is_explicit_nonunique_concurrent_ddl_only():
    sql = _statements(MIGRATION)
    creates = re.findall(
        r"CREATE INDEX CONCURRENTLY IF NOT EXISTS\s+(\w+)\s+ON public\.(\w+)\s*"
        r"\(([^;]+?)\)(?:\s+WHERE[^;]+)?;",
        sql, flags=re.IGNORECASE | re.DOTALL,
    )
    assert len(creates) == 4, "All four indexes must be built concurrently"
    assert len({entry[0] for entry in creates}) == 4, "Names must be unique"

    expected = {
        "idx_sendro_messages_conv_id_desc": ("messages", "conversation_id, id DESC"),
        "idx_sendro_messages_wa_id": ("messages", "whatsapp_message_id"),
        "idx_sendro_conversations_inbox_updated": (
            "conversations", "updated_at DESC, id DESC"
        ),
        "idx_sendro_conversations_active_recent": (
            "conversations", "last_message_at DESC, id DESC"
        ),
    }
    actual = {name: (table, " ".join(columns.split())) for name, table, columns in creates}
    assert actual == expected

    assert sql.upper().count("CREATE INDEX CONCURRENTLY IF NOT EXISTS") == 4
    for disallowed in ("CREATE UNIQUE", "ALTER TABLE", "DROP INDEX", "DELETE FROM", "INSERT INTO",
                       "UPDATE ", "BEGIN;", "COMMIT;", "CREATE EXTENSION"):
        assert disallowed not in sql.upper()
    assert "WHERE whatsapp_message_id IS NOT NULL" in sql
    assert sql.count("WHERE status <> 'archived'") == 2


def test_verification_is_explain_and_select_only():
    sql = _statements(VERIFY).strip()
    assert sql.upper().count("EXPLAIN") == 5
    assert sql.count("pg_index") == 1
    # No schema changes or data modifications even in the verification script.
    for disallowed in ("CREATE ", "DROP ", "ALTER ", "INSERT ", "UPDATE ", "DELETE ",
                       "TRUNCATE ", "ANALYZE ", "EXPLAIN ANALYZE"):
        assert disallowed not in sql.upper()
