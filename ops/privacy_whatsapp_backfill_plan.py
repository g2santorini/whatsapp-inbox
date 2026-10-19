#!/usr/bin/env python3
"""Plan only: bounded legacy WhatsApp tenant-link cohorts. NEVER writes data.

Uses the already-reviewed aggregate PostgreSQL READ ONLY dry-run snapshot.
There is no backfill/commit mode, no INSERT and no database migration.
"""
import json
import math
import os
import sys

try:
    from .privacy_whatsapp_mapping_dry_run import read_snapshot
except ImportError:
    # Allows `python ../ops/privacy_whatsapp_backfill_plan.py` in Render Shell.
    from privacy_whatsapp_mapping_dry_run import read_snapshot

EXPECTED_TENANT_ID = 1
BATCH_SIZE = 500


def build_plan(report):
    """Produce bounded planning statistics; candidate != verified/approved."""
    if report.get("mode") != "DRY_RUN_READ_ONLY" or report.get("writes_performed") != 0:
        raise ValueError("Requires a no-write verified snapshot")
    counts = report.get("counts")
    if not isinstance(counts, dict):
        raise ValueError("Missing aggregate counts")
    keys = (
        "conversations", "unmapped_conversations", "existing_links",
        "orphan_messages", "duplicate_phone_groups", "invalid_e164_phones",
        "invalid_verified_links", "mapped_other_tenant", "revoked_links",
        "unlinked_template_batch_items", "tenant_whatsapp_accounts",
    )
    for key in keys:
        if type(counts.get(key)) is not int or counts[key] < 0:
            raise ValueError("Invalid aggregate: " + key)
    if counts["unmapped_conversations"] + counts["existing_links"] != counts["conversations"]:
        raise ValueError("Inconsistent linkage totals")
    high_water = report.get("snapshot_high_water_conversation_id")
    if high_water is not None and (type(high_water) is not int or high_water <= 0):
        raise ValueError("Invalid snapshot watermark")

    blockers = []
    for field, label in (
        ("existing_links", "Existing mappings must be independently reconciled"),
        ("orphan_messages", "Unlinked legacy messages require manual review"),
        ("duplicate_phone_groups", "Repeated normalized numbers require manual review"),
        ("invalid_e164_phones", "Nonstandard customer number formatting"),
        ("invalid_verified_links", "Invalid pre-existing mapping evidence"),
        ("mapped_other_tenant", "Mapping conflict with another tenant"),
        ("revoked_links", "Revoked ownership links require investigation"),
    ):
        if counts[field]:
            blockers.append(label)

    # Always blocked: the READ ONLY preflight is not an authorization to
    # insert records or a proof of historical controller ownership.
    blockers.extend([
        "Store independent Meta business-account ownership evidence in restricted records",
        "Independent controller approval of exact historical scope is required",
        "Rehearse on a verified isolated PostgreSQL restore with rollback plan",
        "Obtain separate authorization before live/shared-DB inserts",
        "Protect future inbound/outbound WhatsApp provenance; new rows are not covered",
    ])

    candidates = counts["unmapped_conversations"]
    return {
        "mode": "PLAN_ONLY_NO_WRITES",
        "company": report.get("company"),
        "tenant_id": EXPECTED_TENANT_ID,
        "snapshot_high_water_conversation_id": high_water,
        "candidate_conversations_not_verified": candidates,
        "planning_batch_size": BATCH_SIZE,
        "estimated_planning_batches": math.ceil(candidates / BATCH_SIZE),
        "estimated_verified_links_to_insert": 0,
        "existing_links": counts["existing_links"],
        "outside_conversation_scope_batch_items": counts["unlinked_template_batch_items"],
        "independently_verified_historical_scope": False,
        "can_execute": False,
        "sql_mutations_available": False,
        "writes_performed": 0,
        "erasure_enabled": False,
        "blockers": blockers,
    }


def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("STOP: DATABASE_URL not set", file=sys.stderr)
        return 2
    try:
        report = read_snapshot(dsn)  # repeatable-read, read-only
        plan = build_plan(report)
    except (RuntimeError, ValueError, TypeError, Exception) as error:
        # Do not emit SQL, identifiers or the DATABASE_URL on errors.
        print("PLAN STOPPED: " + type(error).__name__, file=sys.stderr)
        return 2
    print(json.dumps(plan, sort_keys=True, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
