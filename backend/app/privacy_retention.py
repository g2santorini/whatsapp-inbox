"""Offline-only retention review for Sendro customer conversation records.

This module deliberately has NO database, API, scheduler, or deletion integration.
Passing a review never authorizes erasure. All source data must be separately
verified and supplied by a controlled audit; do not run on the shared live DB.
"""
from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


RETENTION_MONTHS = 12
INACTIVE_STATUSES = frozenset({"closed", "archived"})


@dataclass(frozen=True)
class ConversationRetentionSnapshot:
    """Minimum evidence for a *potential* retention review, not deletion.

    No contact names, phone numbers or message text are accepted here.
    Flags deliberately default to unknown/not reviewed and block candidacy.
    """

    status: str
    created_at: datetime | None
    updated_at: datetime | None
    last_message_at: datetime | None
    latest_related_message_at: datetime | None = None
    unread_count: int = 0
    assigned_to_user_id: int | None = None
    follow_up: bool = False
    activity_review_complete: bool = False
    references_review_complete: bool = False
    legal_hold: bool | None = None


def _as_utc(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        # Legacy SQLAlchemy timestamps use naive UTC. Never infer local time.
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def twelve_month_cutoff(now: datetime) -> datetime:
    """Exactly twelve calendar months ago; clip 29 February if needed."""
    reference = _as_utc(now)
    if reference is None:
        raise ValueError("A valid review time is required")
    year = reference.year - 1
    day = min(reference.day, calendar.monthrange(year, reference.month)[1])
    return reference.replace(year=year, day=day)


def review_retention_candidate(
    record: ConversationRetentionSnapshot, *, as_of: datetime
) -> str:
    """Return a non-identifying reason; never select anything for deletion.

    'candidate_for_manual_review' is NOT authorization to delete: media,
    template reports, tenant boundaries, other platforms, legal rights and
    restore/backups require separately approved controls.
    """
    if not isinstance(record, ConversationRetentionSnapshot):
        return "invalid_evidence"
    cutoff = twelve_month_cutoff(as_of)
    if not record.activity_review_complete:
        return "activity_not_verified"
    if not record.references_review_complete:
        return "references_not_verified"
    if record.legal_hold is None:
        return "legal_hold_not_checked"
    if record.legal_hold is True:
        return "legal_hold"
    if record.status not in INACTIVE_STATUSES:
        return "active_conversation"
    if (
        type(record.unread_count) is not int
        or record.unread_count != 0
        or record.assigned_to_user_id is not None
        or record.follow_up is not False
    ):
        return "pending_work"
    required = (
        _as_utc(record.created_at),
        _as_utc(record.updated_at),
        _as_utc(record.last_message_at),
    )
    if any(value is None for value in required):
        return "missing_activity_timestamp"
    recent = [*required]
    extra = record.latest_related_message_at
    if extra is not None:
        parsed_extra = _as_utc(extra)
        if parsed_extra is None:
            return "invalid_activity_timestamp"
        recent.append(parsed_extra)
    # Include the newest *related message* to defend against a stale
    # conversation.last_message_at; current DB rows are not trusted alone.
    if max(recent) > cutoff:
        return "within_retention_period"
    return "candidate_for_manual_review"


def summarize_offline_review(
    records: Iterable[ConversationRetentionSnapshot], *, as_of: datetime
) -> dict:
    """Only aggregated counts. No customer IDs, raw records or message bodies."""
    twelve_month_cutoff(as_of)
    counts = Counter(review_retention_candidate(item, as_of=as_of)
                     for item in records)
    return {
        "mode": "offline_review_only",
        "retention_months": RETENTION_MONTHS,
        "database_connected": False,
        "deletion_enabled": False,
        "total": sum(counts.values()),
        "candidates_for_manual_review": counts.get("candidate_for_manual_review", 0),
        "blocked_reasons": {
            key: value for key, value in sorted(counts.items())
            if key != "candidate_for_manual_review"
        },
    }
