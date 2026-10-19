#!/usr/bin/env python3
"""READ-ONLY ownership-mapping dry run for legacy Sunset Oia WhatsApp history.

This script cannot backfill or approve any conversation. It opens a single
repeatable-read READ ONLY PostgreSQL transaction and prints aggregate counts
only. No contact names, phone numbers, messages, or individual IDs are output.

Usage, from Render staging backend Shell:
    python ops/privacy_whatsapp_mapping_dry_run.py

Set DATABASE_URL in the runtime. Never paste the connection URL into a chat.
There is no --apply, --write, --commit, or migration mode.
"""
import json
import os
import sys

import psycopg
from psycopg.rows import dict_row

EXPECTED_DATABASE = "sendro"
EXPECTED_TENANT_ID = 1
EXPECTED_TENANT_NAME = "Sunset Oia Sailing Cruises"

# Single snapshot, aggregate-only SELECT. Do not replace with phone lookups or
# user_id-based inferred ownership, and do not output customer identifiers.
COUNTS_SQL = """
WITH
phone_groups AS (
    SELECT regexp_replace(contact_phone, '[^0-9]', '', 'g') AS digits,
           COUNT(*) AS number_of_conversations
    FROM public.conversations
    GROUP BY 1
),
legacy_conversations AS (
    SELECT COUNT(*) AS total,
           COUNT(*) FILTER (WHERE l.conversation_id IS NULL) AS unmapped,
           COUNT(*) FILTER (WHERE l.conversation_id IS NOT NULL) AS linked_total,
           COUNT(*) FILTER (WHERE l.tenant_id = %(tid)s AND l.revoked_at IS NULL
                             AND l.verification_method = 'manual-owner-review'
                             AND l.evidence_ref IS NOT NULL) AS mapped_active_to_tenant,
           COUNT(*) FILTER (WHERE l.tenant_id IS NOT NULL
                             AND l.tenant_id <> %(tid)s) AS mapped_other_tenant,
           COUNT(*) FILTER (WHERE l.revoked_at IS NOT NULL) AS revoked,
           MAX(c.id) AS high_water_conversation_id
    FROM public.conversations AS c
    LEFT JOIN public.sendro_privacy_legacy_whatsapp_links AS l
      ON l.conversation_id = c.id
)
SELECT
    (SELECT total FROM legacy_conversations) AS conversations,
    (SELECT unmapped FROM legacy_conversations) AS unmapped_conversations,
    (SELECT linked_total FROM legacy_conversations) AS existing_links,
    (SELECT mapped_active_to_tenant FROM legacy_conversations) AS mapped_active_to_tenant,
    (SELECT mapped_other_tenant FROM legacy_conversations) AS mapped_other_tenant,
    (SELECT revoked FROM legacy_conversations) AS revoked_links,
    (SELECT high_water_conversation_id FROM legacy_conversations) AS high_water_conversation_id,
    (SELECT COUNT(*) FROM public.messages) AS messages,
    (SELECT COUNT(*) FROM public.messages m
       LEFT JOIN public.conversations c ON c.id=m.conversation_id
       WHERE c.id IS NULL) AS orphan_messages,
    (SELECT COUNT(*) FROM public.template_batch_items) AS template_batch_items,
    (SELECT COUNT(*) FROM public.template_batch_items
       WHERE conversation_id IS NULL) AS unlinked_template_batch_items,
    (SELECT COUNT(*) FROM phone_groups
       WHERE number_of_conversations > 1) AS duplicate_phone_groups,
    (SELECT COUNT(*) FROM public.conversations
       WHERE contact_phone IS NULL
          OR contact_phone !~ '^[+][1-9][0-9]{6,14}$') AS invalid_e164_phones,
    (SELECT COUNT(*) FROM public.sendro_privacy_legacy_whatsapp_links
       WHERE verification_method <> 'manual-owner-review'
          OR evidence_ref IS NULL OR verified_at IS NULL) AS invalid_verified_links,
    (SELECT COUNT(*) FROM public.sendro_channel_accounts
       WHERE tenant_id = %(tid)s AND platform = 'whatsapp') AS tenant_whatsapp_accounts,
    (SELECT COUNT(*) FROM public.sendro_tenants) AS registered_tenants
"""

def make_report(snapshot):
    """Pure reporting function; never describes candidates as verified."""
    required = (
        "conversations", "unmapped_conversations", "existing_links", "mapped_active_to_tenant",
        "mapped_other_tenant", "revoked_links", "messages", "orphan_messages",
        "template_batch_items", "unlinked_template_batch_items",
        "duplicate_phone_groups", "invalid_e164_phones",
        "invalid_verified_links", "tenant_whatsapp_accounts",
        "registered_tenants",
    )
    counts = {}
    for key in required:
        value = snapshot.get(key)
        if type(value) is not int or value < 0:
            raise ValueError("Invalid aggregate for " + key)
        counts[key] = value

    if (counts["unmapped_conversations"] + counts["existing_links"]
            != counts["conversations"]):
        raise ValueError("Conversation mapping totals do not reconcile")
    if counts["mapped_active_to_tenant"] > counts["existing_links"]:
        raise ValueError("Verified mappings exceed existing links")
    if counts["registered_tenants"] < 1:
        raise ValueError("Expected at least one registered company")
    high_water = snapshot.get("high_water_conversation_id")
    if high_water is not None and (type(high_water) is not int or high_water < 1):
        raise ValueError("Invalid high-water ID")

    return {
        "mode": "DRY_RUN_READ_ONLY",
        "database": EXPECTED_DATABASE,
        "company": EXPECTED_TENANT_NAME,
        "snapshot_high_water_conversation_id": high_water,
        "counts": counts,
        "unverified_candidate_conversations": counts["unmapped_conversations"],
        "verified_ready_for_backfill": 0,
        "writes_performed": 0,
        "erasure_enabled": False,
        "automatic_mapping_supported": False,
        "next_step_requires_separate_approval": True,
        "limitations": [
            "Business ownership declaration is not independently retained account evidence",
            "Legacy records have no historical receiving WhatsApp business account ID",
            "Unlinked template batches require separate assessment for GDPR erasure",
            "A read-only snapshot is not authorization to create mappings",
        ],
    }


def read_snapshot(database_url):
    # autocommit prevents implicit transactions before the explicit
    # repeatable-read READ ONLY transaction is opened.
    with psycopg.connect(
        database_url, connect_timeout=10, row_factory=dict_row, autocommit=True
    ) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                cur.execute("SET LOCAL lock_timeout = '5s'")
                cur.execute("SET LOCAL statement_timeout = '30s'")
                cur.execute("""
                    SELECT current_database() AS db_name,
                           current_setting('transaction_read_only') AS read_only,
                           to_regclass(
                               'public.sendro_privacy_legacy_whatsapp_links'
                           ) IS NOT NULL AS mapping_exists
                """)
                guard = cur.fetchone()
                if (guard["db_name"] != EXPECTED_DATABASE
                        or guard["read_only"] != "on"
                        or guard["mapping_exists"] is not True):
                    raise RuntimeError("Wrong DB, non-read-only session, or missing table")

                cur.execute("""
                    SELECT display_name FROM public.sendro_tenants
                    WHERE id = %(tid)s
                """, {"tid": EXPECTED_TENANT_ID})
                tenant = cur.fetchone()
                if not tenant or tenant["display_name"] != EXPECTED_TENANT_NAME:
                    raise RuntimeError("Expected company does not match")

                # The read-only snapshot neither reads nor prints customer PII.
                cur.execute(COUNTS_SQL, {"tid": EXPECTED_TENANT_ID})
                snapshot = cur.fetchone()
                return make_report(snapshot)


def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("STOP: DATABASE_URL is not set", file=sys.stderr)
        return 2
    try:
        report = read_snapshot(dsn)
    except (psycopg.Error, RuntimeError, ValueError, TypeError) as exc:
        # Never echo a connection string or raw SQL diagnostics.
        print("DRY RUN STOPPED: " + type(exc).__name__, file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
) AS invalid_e164_phones,
    (SELECT COUNT(*) FROM public.sendro_privacy_legacy_whatsapp_links
       WHERE verification_method <> 'manual-owner-review'
          OR evidence_ref IS NULL OR verified_at IS NULL) AS invalid_verified_links,
    (SELECT COUNT(*) FROM public.sendro_channel_accounts
       WHERE tenant_id = %(tid)s AND platform = 'whatsapp') AS tenant_whatsapp_accounts,
    (SELECT COUNT(*) FROM public.sendro_tenants) AS registered_tenants
"""

def make_report(snapshot):
    """Pure reporting function; never describes candidates as verified."""
    required = (
        "conversations", "unmapped_conversations", "mapped_active_to_tenant",
        "mapped_other_tenant", "revoked_links", "messages", "orphan_messages",
        "template_batch_items", "unlinked_template_batch_items",
        "duplicate_phone_groups", "invalid_e164_phones",
        "invalid_verified_links", "tenant_whatsapp_accounts",
        "registered_tenants",
    )
    counts = {}
    for key in required:
        value = snapshot.get(key)
        if type(value) is not int or value < 0:
            raise ValueError("Invalid aggregate for " + key)
        counts[key] = value

    if counts["unmapped_conversations"] > counts["conversations"]:
        raise ValueError("Unmapped count exceeds conversations")
    if (counts["unmapped_conversations"]
            + counts["mapped_active_to_tenant"]
            + counts["mapped_other_tenant"]
            + counts["revoked_links"] < counts["conversations"]):
        # Possible if historical links have other states; do not pretend
        # every record has been categorized.
        raise ValueError("Conversation ownership states do not reconcile")
    if counts["registered_tenants"] < 1:
        raise ValueError("Expected at least one registered company")
    high_water = snapshot.get("high_water_conversation_id")
    if high_water is not None and (type(high_water) is not int or high_water < 1):
        raise ValueError("Invalid high-water ID")

    return {
        "mode": "DRY_RUN_READ_ONLY",
        "database": EXPECTED_DATABASE,
        "company": EXPECTED_TENANT_NAME,
        "snapshot_high_water_conversation_id": high_water,
        "counts": counts,
        "unverified_candidate_conversations": counts["unmapped_conversations"],
        "verified_ready_for_backfill": 0,
        "writes_performed": 0,
        "erasure_enabled": False,
        "mapping_enabled": False,
        "next_step_requires_separate_approval": True,
        "limitations": [
            "Business ownership declaration is not independently retained account evidence",
            "Legacy records have no historical receiving WhatsApp business account ID",
            "Unlinked template batches require separate assessment for GDPR erasure",
            "A read-only snapshot is not authorization to create mappings",
        ],
    }


def read_snapshot(database_url):
    # autocommit prevents implicit transactions before the explicit
    # repeatable-read READ ONLY transaction is opened.
    with psycopg.connect(
        database_url, connect_timeout=10, row_factory=dict_row, autocommit=True
    ) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                cur.execute("SET LOCAL lock_timeout = '5s'")
                cur.execute("SET LOCAL statement_timeout = '30s'")
                cur.execute("""
                    SELECT current_database() AS db_name,
                           current_setting('transaction_read_only') AS read_only,
                           to_regclass(
                               'public.sendro_privacy_legacy_whatsapp_links'
                           ) IS NOT NULL AS mapping_exists
                """)
                guard = cur.fetchone()
                if (guard["db_name"] != EXPECTED_DATABASE
                        or guard["read_only"] != "on"
                        or guard["mapping_exists"] is not True):
                    raise RuntimeError("Wrong DB, non-read-only session, or missing table")

                cur.execute("""
                    SELECT display_name FROM public.sendro_tenants
                    WHERE id = %(tid)s
                """, {"tid": EXPECTED_TENANT_ID})
                tenant = cur.fetchone()
                if not tenant or tenant["display_name"] != EXPECTED_TENANT_NAME:
                    raise RuntimeError("Expected company does not match")

                # The read-only snapshot neither reads nor prints customer PII.
                cur.execute(COUNTS_SQL, {"tid": EXPECTED_TENANT_ID})
                snapshot = cur.fetchone()
                return make_report(snapshot)


def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("STOP: DATABASE_URL is not set", file=sys.stderr)
        return 2
    try:
        report = read_snapshot(dsn)
    except (psycopg.Error, RuntimeError, ValueError, TypeError) as exc:
        # Never echo a connection string or raw SQL diagnostics.
        print("DRY RUN STOPPED: " + type(exc).__name__, file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
