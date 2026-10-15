"""Phase 2N: offline, schema-only Instagram database drift audit.

There is NO CLI, DATABASE_URL access, engine creation, Render connection,
scheduler or FastAPI hook. The SQL reads pg_catalog metadata only and never
reads customer rows, users, messages, secrets or encrypted webhook payloads.

To inspect a real DB in the future, use a separately authorized read-only
operator/tool with least-privilege credentials and explicit owner approval.
"""
from collections import defaultdict

from sqlalchemy import text


# Match ONLY six Instagram/SaaS tables. Never list whole public schema.
TABLES = (
    "sendro_tenants",
    "sendro_tenant_users",
    "sendro_channel_accounts",
    "sendro_channel_conversations",
    "sendro_channel_messages",
    "sendro_channel_webhook_deliveries",
)

# Fixed read-only pg_catalog SQL; zero customer-table reads, no DDL/DML.
# The rows include *schema identifiers and definitions only*, not record data.
INSTAGRAM_CATALOG_SQL = """
WITH target(name) AS (
    VALUES ('sendro_tenants'),
           ('sendro_tenant_users'),
           ('sendro_channel_accounts'),
           ('sendro_channel_conversations'),
           ('sendro_channel_messages'),
           ('sendro_channel_webhook_deliveries')
), relations AS (
    SELECT c.oid, c.relname, c.relkind
    FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    JOIN target AS t ON t.name = c.relname
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
)
SELECT 'table' AS object_kind,
       r.relname AS table_name,
       r.relname AS object_name,
       r.relkind::text AS definition
FROM relations AS r
UNION ALL
SELECT 'column', r.relname, a.attname,
       ty.typname || '|' ||
           CASE WHEN a.attnotnull THEN 'required' ELSE 'nullable' END
FROM relations AS r
JOIN pg_catalog.pg_attribute AS a ON a.attrelid = r.oid
JOIN pg_catalog.pg_type AS ty ON ty.oid = a.atttypid
WHERE a.attnum > 0 AND NOT a.attisdropped
UNION ALL
SELECT 'constraint', r.relname, con.conname,
       con.contype::text || '|' || pg_catalog.pg_get_constraintdef(con.oid, true)
FROM relations AS r
JOIN pg_catalog.pg_constraint AS con ON con.conrelid = r.oid
UNION ALL
SELECT 'index', r.relname, ic.relname,
       pg_catalog.pg_get_indexdef(idx.indexrelid, 0, true)
FROM relations AS r
JOIN pg_catalog.pg_index AS idx ON idx.indrelid = r.oid
JOIN pg_catalog.pg_class AS ic ON ic.oid = idx.indexrelid
ORDER BY table_name, object_kind, object_name
"""

# Compact manifest reviewed against the original, manually authored,
# UNMERGED Instagram SQL migration snapshots 1–6 (PRs #12–17).
# A suffix ! means NOT NULL, ? means nullable.
COLUMN_MANIFEST = {
    "sendro_tenants": """
        id:int8! slug:varchar! display_name:varchar! created_at:timestamptz!
    """,
    "sendro_tenant_users": """
        tenant_id:int8! user_id:int4! member_role:varchar!
        is_active:bool! joined_at:timestamptz!
    """,
    "sendro_channel_accounts": """
        id:int8! tenant_id:int8! platform:varchar! external_account_id:varchar!
        display_name:varchar? status:varchar! created_at:timestamptz!
        updated_at:timestamptz!
    """,
    "sendro_channel_conversations": """
        id:int8! tenant_id:int8! channel_account_id:int8!
        external_customer_id:varchar! contact_name:varchar? status:varchar!
        assigned_to_user_id:int4? unread_count:int4! last_message_at:timestamptz?
        created_at:timestamptz! updated_at:timestamptz!
    """,
    "sendro_channel_messages": """
        id:int8! tenant_id:int8! channel_account_id:int8!
        conversation_id:int8! provider_message_id:varchar? direction:varchar!
        message_type:varchar! content:text? media_json:jsonb?
        provider_timestamp:timestamptz? delivery_status:varchar?
        is_read:bool! sent_by_user_id:int4? created_at:timestamptz!
        updated_at:timestamptz!
    """,
    "sendro_channel_webhook_deliveries": """
        id:int8! provider:varchar! raw_body_sha256:bpchar!
        payload_ciphertext:bytea! processing_state:varchar!
        attempts:int4! last_error_code:varchar? received_at:timestamptz!
        next_attempt_at:timestamptz? processed_at:timestamptz?
    """,
}

CONSTRAINT_MANIFEST = {
    "sendro_tenants": (
        "sendro_tenants_pkey", "sendro_tenants_slug_key",
        "ck_sendro_tenants_slug",
    ),
    "sendro_tenant_users": (
        "pk_sendro_tenant_users", "ck_sendro_tenant_users_role",
        "sendro_tenant_users_tenant_id_fkey",
        "sendro_tenant_users_user_id_fkey",
    ),
    "sendro_channel_accounts": (
        "sendro_channel_accounts_pkey",
        "sendro_channel_accounts_tenant_id_fkey",
        "ck_sendro_channel_accounts_platform",
        "ck_sendro_channel_accounts_status",
        "uq_sendro_channel_accounts_platform_external",
        "uq_sendro_channel_accounts_id_tenant",
    ),
    "sendro_channel_conversations": (
        "sendro_channel_conversations_pkey",
        "fk_sendro_channel_conversations_account_tenant",
        "fk_sendro_channel_conversations_assigned_member",
        "uq_sendro_channel_conversations_account_customer",
        "uq_sendro_channel_conversations_id_tenant_account",
        "ck_sendro_channel_conversations_customer",
        "ck_sendro_channel_conversations_status",
        "ck_sendro_channel_conversations_unread",
    ),
    "sendro_channel_messages": (
        "sendro_channel_messages_pkey",
        "fk_sendro_channel_messages_conversation_scope",
        "fk_sendro_channel_messages_sender_member",
        "uq_sendro_channel_messages_provider",
        "ck_sendro_channel_messages_direction",
        "ck_sendro_channel_messages_inbound_mid",
        "ck_sendro_channel_messages_body",
        "ck_sendro_channel_messages_delivery_status",
    ),
    "sendro_channel_webhook_deliveries": (
        "sendro_channel_webhook_deliveries_pkey",
        "uq_sendro_channel_webhook_deliveries_dedupe",
        "ck_sendro_channel_webhook_deliveries_provider",
        "ck_sendro_channel_webhook_deliveries_digest",
        "ck_sendro_channel_webhook_deliveries_state",
        "ck_sendro_channel_webhook_deliveries_attempts",
        "ck_sendro_channel_webhook_deliveries_ciphertext",
    ),
}

EXPLICIT_INDEXES = {
    "sendro_tenant_users": ("idx_sendro_tenant_users_user",),
    "sendro_channel_accounts": ("idx_sendro_channel_accounts_tenant_platform",),
    "sendro_channel_conversations": (
        "idx_sendro_channel_conversations_tenant_status_updated",),
    "sendro_channel_messages": (
        "idx_sendro_channel_messages_conversation_id_desc",
        "idx_sendro_channel_messages_tenant_created_desc",
    ),
    "sendro_channel_webhook_deliveries": (
        "idx_sendro_channel_webhook_deliveries_work",),
}

# Critical constraints: presence alone is not enough; confirm definitions.
# Match stable fragments, not PostgreSQL version-specific casts/spacing.
CRITICAL_CONSTRAINTS = {
    ("sendro_channel_accounts", "uq_sendro_channel_accounts_platform_external"):
        ("u|unique (platform, external_account_id)",),
    ("sendro_channel_conversations", "fk_sendro_channel_conversations_account_tenant"):
        ("f|foreign key (channel_account_id, tenant_id)",
         "references sendro_channel_accounts(id, tenant_id)"),
    ("sendro_channel_messages", "fk_sendro_channel_messages_conversation_scope"):
        ("f|foreign key (conversation_id, tenant_id, channel_account_id)",
         "references sendro_channel_conversations(id, tenant_id, channel_account_id)"),
    ("sendro_channel_messages", "uq_sendro_channel_messages_provider"):
        ("u|unique (channel_account_id, provider_message_id)",),
    ("sendro_channel_webhook_deliveries", "uq_sendro_channel_webhook_deliveries_dedupe"):
        ("u|unique (provider, raw_body_sha256)",),
    ("sendro_channel_webhook_deliveries", "ck_sendro_channel_webhook_deliveries_provider"):
        ("c|check", "provider", "'instagram'"),
}


def _expected_columns(spec):
    columns = {}
    for item in spec.split():
        name, typemark = item.split(":")
        if typemark[-1] not in "!?":
            raise ValueError("Invalid schema manifest column")
        columns[name] = typemark[:-1] + "|" + (
            "required" if typemark[-1] == "!" else "nullable"
        )
    return columns


def read_catalog_only(connection):
    """Use an ALREADY-OPEN authorized PostgreSQL connection. No engine creation.

    Caller must ensure an isolated CI database or obtain separate approval
    for any future production read-only schema audit. Selects pg_catalog only.
    """
    return [dict(row) for row in
            connection.execute(text(INSTAGRAM_CATALOG_SQL)).mappings().all()]


def compare_instagram_catalog_rows(rows):
    """Deterministic metadata-only comparison, no PII, no database I/O.

    Input is a list of rows shaped like the result of INSTAGRAM_CATALOG_SQL.
    Accepts no customer data and produces only schema object names + drift codes.
    """
    found = defaultdict(dict)
    issues = []
    valid_kinds = {"table", "column", "constraint", "index"}
    for record in rows:
        kind = record["object_kind"]
        table = record["table_name"]
        name = record["object_name"]
        definition = record["definition"]
        if kind not in valid_kinds or table not in TABLES:
            raise ValueError("Unexpected schema audit metadata scope")
        key = (kind, name)
        if key in found[table]:
            raise ValueError("Duplicated schema metadata object")
        found[table][key] = str(definition)

    def add(code, table, name):
        issues.append({"code": code, "table": table, "object": name})

    for table in TABLES:
        actual = found[table]
        if ("table", table) not in actual:
            add("missing_table", table, table)
            continue
        if actual[("table", table)] != "r":
            add("unexpected_relation_kind", table, table)

        expected_columns = _expected_columns(COLUMN_MANIFEST[table])
        actual_columns = {
            name: definition
            for (kind, name), definition in actual.items() if kind == "column"
        }
        for name, specification in expected_columns.items():
            if name not in actual_columns:
                add("missing_column", table, name)
            elif actual_columns[name] != specification:
                add("column_type_or_nullability_drift", table, name)
        for name in sorted(actual_columns.keys() - expected_columns.keys()):
            add("unexpected_column", table, name)

        for name in CONSTRAINT_MANIFEST[table]:
            if ("constraint", name) not in actual:
                add("missing_constraint", table, name)
        for name in EXPLICIT_INDEXES.get(table, ()):
            if ("index", name) not in actual:
                add("missing_index", table, name)

        for (check_table, name), fragments in CRITICAL_CONSTRAINTS.items():
            if check_table != table or ("constraint", name) not in actual:
                continue
            definition = " ".join(actual[("constraint", name)].lower().split())
            if not all(fragment in definition for fragment in fragments):
                add("critical_constraint_definition_drift", table, name)

    return {
        "status": "compatible" if not issues else "drift",
        "expected_table_count": len(TABLES),
        "tables_found": sum(("table", table) in found[table] for table in TABLES),
        "issues": sorted(issues, key=lambda x: (x["table"], x["code"], x["object"])),
    }
