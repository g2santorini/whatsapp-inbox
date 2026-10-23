"""Offline-only 12-calendar-month delivery-history retention preview.

Owner-approved target for bulk-send history: retain for at most twelve calendar
months after TemplateBatchItem.created_at for ordinary status-review purposes.
Later delivery-status changes MUST NOT restart the retention clock.

This module deliberately has NO database, HTTP, scheduler, deletion, or
persistence integration. All inputs are explicitly supplied synthetic metadata.
A candidate is a request for a future scoped, legally validated erasure review,
NEVER permission to delete production data.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .privacy_retention import twelve_month_cutoff


RETENTION_MONTHS = 12


@dataclass(frozen=True)
class DeliveryHistoryRetentionSnapshot:
    """No guest identity, phone, reservation, tenant ID or message content.

    Safety gates are intentionally false/unknown by default, so a caller cannot
    accidentally treat old records as approved for deletion. Status timestamps
    may be checked for consistency but NEVER extend the 12-month deadline.
    """

    created_at: datetime | None
    delivery_status_updated_at: datetime | None = None
    tenant_ownership_verified: bool = False
    controller_instructions_verified: bool = False
    related_records_reviewed: bool = False
    backup_restore_plan_reviewed: bool = False
    legal_hold: bool | None = None


def _utc(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    # Legacy DB uses naive UTC timestamps. Never interpret them as local time.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def review_delivery_history(
    record: DeliveryHistoryRetentionSnapshot, *, as_of: datetime
) -> str:
    """Return only a reason code, never an ID, actual data or SQL command.

    The cutoff is based *solely* on created_at, not WhatsApp status, because
    the owner specified an ordinary 12-month maximum for delivery history.
    """
    cutoff = twelve_month_cutoff(as_of)
    now = _utc(as_of)
    if not isinstance(record, DeliveryHistoryRetentionSnapshot):
        return "invalid_evidence"
    created = _utc(record.created_at)
    if created is None:
        return "missing_created_at"
    if created > now:
        return "future_created_at"
    status_updated = record.delivery_status_updated_at
    if status_updated is not None:
        parsed_status = _utc(status_updated)
        if parsed_status is None or parsed_status > now:
            return "invalid_status_timestamp"
    if created > cutoff:
        return "within_12_calendar_months"
    if record.legal_hold is None:
        return "legal_hold_not_checked"
    if record.legal_hold is True:
        return "legal_hold"
    if record.legal_hold is not False:
        return "invalid_legal_hold"
    if record.tenant_ownership_verified is not True:
        return "tenant_ownership_not_verified"
    if record.controller_instructions_verified is not True:
        return "controller_instructions_not_verified"
    if record.related_records_reviewed is not True:
        return "related_records_not_reviewed"
    if record.backup_restore_plan_reviewed is not True:
        return "backup_restore_plan_not_reviewed"
    return "candidate_for_manual_erasure_review"


def summarize_delivery_history(
    records: Iterable[DeliveryHistoryRetentionSnapshot], *, as_of: datetime
) -> dict:
    """Redacted aggregate counts on caller-provided records; no DB access."""
    twelve_month_cutoff(as_of)
    reasons = Counter(review_delivery_history(item, as_of=as_of)
                      for item in records)
    candidate = "candidate_for_manual_erasure_review"
    return {
        "mode": "offline_synthetic_review_only",
        "retention_months": RETENTION_MONTHS,
        "retention_anchor": "batch_item_created_at_utc",
        "delivery_status_extends_deadline": False,
        "database_connected": False,
        "erasure_enabled": False,
        "erasure_performed": False,
        "total": sum(reasons.values()),
        "candidates_for_manual_review": reasons.get(candidate, 0),
        "blocked_reasons": {
            key: value for key, value in sorted(reasons.items())
            if key != candidate
        },
    }
