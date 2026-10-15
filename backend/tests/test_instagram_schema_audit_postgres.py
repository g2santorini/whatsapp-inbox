"""Phase 2N metadata-only schema audit tests in disposable PostgreSQL CI.

These tests depend on the exact migration replay fixture's strict CI-only DB
guard. The Render/shared staging+production DB is never queried.
"""
from copy import deepcopy

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.instagram_schema_audit import (
    INSTAGRAM_CATALOG_SQL,
    TABLES,
    compare_instagram_catalog_rows,
    read_catalog_only,
)
from backend.tests.test_instagram_manual_migrations_postgres import replay_engine


@pytest.fixture(scope="module")
def catalog_rows(replay_engine):
    # The caller, not the audit function, enforces READ ONLY on the server.
    with replay_engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            assert conn.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
            return read_catalog_only(conn)


def test_audit_only_queries_pg_catalog_metadata():
    sql = " ".join(INSTAGRAM_CATALOG_SQL.lower().split())
    assert "pg_catalog.pg_class" in sql
    assert "pg_catalog.pg_constraint" in sql
    assert "pg_catalog.pg_index" in sql
    assert "pg_catalog.pg_attribute" in sql
    assert "information_schema" not in sql
    assert "pg_get_indexdef" in sql
    for forbidden in (
        " from public.sendro_channel_messages",
        " from public.users",
        " from public.sendro_channel_webhook_deliveries",
        "payload_ciphertext", "customer_id =",
        "pg_catalog.pg_stat_activity",
        " insert ", " update ", " delete ", " alter ", " drop ",
    ):
        assert forbidden not in " " + sql + " "


def test_replayed_six_migrations_match_expected_schema_manifest(catalog_rows):
    outcome = compare_instagram_catalog_rows(catalog_rows)
    assert outcome == {
        "status": "compatible",
        "expected_table_count": 6,
        "tables_found": 6,
        "issues": [],
    }
    tables = {r["table_name"] for r in catalog_rows if r["object_kind"] == "table"}
    assert tables == set(TABLES)


def test_read_only_transaction_cannot_write_even_in_ephemeral_db(replay_engine):
    with replay_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                assert conn.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
                conn.execute(text("""
                    INSERT INTO public.sendro_tenants (slug, display_name)
                    VALUES ('forbidden-ci-test', 'Must Never Exist')
                """))
    with replay_engine.connect() as conn:
        exists = conn.execute(text("""
            SELECT EXISTS(SELECT 1 FROM public.sendro_tenants
                          WHERE slug = 'forbidden-ci-test')
        """)).scalar_one()
    assert exists is False


def alter_one(rows, *, kind, table, name, replacement=None, remove=False):
    snapshot = deepcopy(rows)
    candidate = next(
        entry for entry in snapshot
        if entry["object_kind"] == kind
        and entry["table_name"] == table and entry["object_name"] == name
    )
    if remove:
        snapshot.remove(candidate)
    else:
        candidate["definition"] = replacement
    return snapshot


def test_missing_table_is_reported_without_any_customer_records(catalog_rows):
    tampered = [
        r for r in deepcopy(catalog_rows)
        if r["table_name"] != "sendro_channel_messages"
    ]
    report = compare_instagram_catalog_rows(tampered)
    assert report["status"] == "drift"
    assert {"code": "missing_table", "table": "sendro_channel_messages",
            "object": "sendro_channel_messages"} in report["issues"]
    assert report["tables_found"] == 5
    assert "Synthetic message" not in str(report)


def test_missing_or_wrong_tenant_scope_fk_is_detected(catalog_rows):
    table = "sendro_channel_messages"
    name = "fk_sendro_channel_messages_conversation_scope"
    for changed in (
        alter_one(catalog_rows, kind="constraint", table=table,
                  name=name, remove=True),
        alter_one(catalog_rows, kind="constraint", table=table, name=name,
                  replacement="f|FOREIGN KEY (conversation_id) REFERENCES sendro_channel_conversations(id)"),
    ):
        codes = {issue["code"] for issue in compare_instagram_catalog_rows(changed)["issues"]}
        assert codes & {"missing_constraint", "critical_constraint_definition_drift"}


def test_instagram_only_provider_constraint_change_is_detected(catalog_rows):
    changed = alter_one(
        catalog_rows, kind="constraint",
        table="sendro_channel_webhook_deliveries",
        name="ck_sendro_channel_webhook_deliveries_provider",
        replacement="c|CHECK (provider = 'whatsapp')",
    )
    issues = compare_instagram_catalog_rows(changed)["issues"]
    assert {"code": "critical_constraint_definition_drift",
            "table": "sendro_channel_webhook_deliveries",
            "object": "ck_sendro_channel_webhook_deliveries_provider"} in issues


def test_missing_index_and_column_type_drift_are_reported(catalog_rows):
    changed = alter_one(
        catalog_rows, kind="index",
        table="sendro_channel_webhook_deliveries",
        name="idx_sendro_channel_webhook_deliveries_work", remove=True,
    )
    changed = alter_one(
        changed, kind="column", table="sendro_channel_messages",
        name="media_json", replacement="text|nullable",
    )
    issues = compare_instagram_catalog_rows(changed)["issues"]
    assert any(i["code"] == "missing_index" for i in issues)
    assert any(i["code"] == "column_type_or_nullability_drift" and
               i["object"] == "media_json" for i in issues)


def test_unexpected_column_is_flagged_and_report_never_contains_definitions(catalog_rows):
    changed = deepcopy(catalog_rows)
    changed.append({
        "object_kind": "column",
        "table_name": "sendro_channel_conversations",
        "object_name": "unreviewed_new_column",
        "definition": "bytea|nullable",
    })
    report = compare_instagram_catalog_rows(changed)
    assert any(issue["code"] == "unexpected_column" for issue in report["issues"])
    assert "bytea|nullable" not in str(report)


def test_audit_rejects_out_of_scope_table_metadata(catalog_rows):
    changed = deepcopy(catalog_rows)
    changed.append({
        "object_kind": "table",
        "table_name": "users",
        "object_name": "users",
        "definition": "r",
    })
    with pytest.raises(ValueError, match="scope"):
        compare_instagram_catalog_rows(changed)


def test_metadata_audit_can_be_reused_without_touching_db(catalog_rows):
    snapshot = deepcopy(catalog_rows)
    assert compare_instagram_catalog_rows(snapshot)["status"] == "compatible"
    assert snapshot == catalog_rows
