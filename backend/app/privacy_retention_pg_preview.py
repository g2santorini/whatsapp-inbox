"""Disposable-CI-only aggregate rehearsal for legacy Sendro conversation retention.

No API, worker, scheduler, live database engine, row-level response or erasure.
The caller supplies a pre-established PostgreSQL READ ONLY connection.
"""
from __future__ import annotations

from datetime import datetime
from collections.abc import Mapping
from sqlalchemy import text
from .privacy_retention import twelve_month_cutoff

# SQL returns counts only; identifiers and message contents never leave the DB.
CONVERSATION_COUNTS_SQL = """
WITH evidence AS (
    SELECT
        c.status IN ('closed', 'archived') AS inactive,
        (
            c.unread_count = 0 AND c.assigned_to_user_id IS NULL
            AND c.follow_up IS FALSE
        ) AS clear_work,
        (
            c.created_at <= :cutoff AND c.updated_at <= :cutoff
            AND c.last_message_at <= :cutoff
            AND NOT EXISTS (
                SELECT 1 FROM public.messages m
                WHERE m.conversation_id = c.id
                  AND (m.created_at IS NULL OR m.created_at > :cutoff)
            )
        ) AS older_than_cutoff,
        EXISTS (
            SELECT 1
            FROM public.template_batch_items t
            LEFT JOIN public.messages m ON m.id = t.message_id
            WHERE t.conversation_id = c.id OR m.conversation_id = c.id
        ) AS has_direct_batch_reference
    FROM public.conversations c
)
SELECT
    count(*) AS total,
    count(*) FILTER (WHERE inactive IS NOT TRUE) AS active_or_unknown,
    count(*) FILTER (WHERE clear_work IS NOT TRUE) AS pending_or_unknown,
    count(*) FILTER (WHERE older_than_cutoff IS NOT TRUE) AS recent_or_unknown,
    count(*) FILTER (
        WHERE inactive AND clear_work AND older_than_cutoff
    ) AS older_inactive_clear_work,
    count(*) FILTER (
        WHERE inactive AND clear_work AND older_than_cutoff
        AND has_direct_batch_reference
    ) AS older_with_direct_batch_reference,
    count(*) FILTER (
        WHERE inactive AND clear_work AND older_than_cutoff
        AND NOT has_direct_batch_reference
    ) AS older_without_direct_batch_reference
FROM evidence
"""

BATCH_COUNTS_SQL = """
SELECT count(*) AS template_batch_items,
       count(*) FILTER (
           WHERE conversation_id IS NULL AND message_id IS NULL
       ) AS unlinked_template_batch_items
FROM public.template_batch_items
"""


def preview_disposable_postgres(
    connection, *, now: datetime, ci_flags: Mapping[str, str]
) -> dict:
    """Fail closed outside GitHub Actions disposable localhost Postgres."""
    url = getattr(getattr(connection, "engine", None), "url", None)
    if not isinstance(ci_flags, Mapping) or not (
        ci_flags.get("GITHUB_ACTIONS") == "true"
        and ci_flags.get("SENDRO_INSTAGRAM_PG_CI_APPROVAL")
        == "ephemeral-local-service-only"
        and url is not None
        and url.get_backend_name() == "postgresql"
        and url.host in ("localhost", "127.0.0.1")
        and url.port == 55439
        and url.username == "sendro_ci"
        and url.database == "sendro_ig_ci"
    ):
        raise PermissionError("Disposable CI PostgreSQL only")
    if connection.execute(text("SHOW transaction_read_only")).scalar_one() != "on":
        raise PermissionError("Server read-only transaction required")
    if connection.execute(text("SELECT current_database()")).scalar_one() != "sendro_ig_ci":
        raise PermissionError("Unexpected database")

    cutoff = twelve_month_cutoff(now).replace(tzinfo=None)
    conversations = connection.execute(
        text(CONVERSATION_COUNTS_SQL), {"cutoff": cutoff}
    ).mappings().one()
    batches = connection.execute(text(BATCH_COUNTS_SQL)).mappings().one()
    return {
        "mode": "disposable_ci_aggregate_only",
        "months_proposed": 12,
        "deletion_enabled": False,
        "eligible_for_deletion": 0,
        "legal_hold_checked": False,
        "backup_restore_checked": False,
        "counts": {
            k: int(v)
            for group in (conversations, batches)
            for k, v in group.items()
        },
    }
