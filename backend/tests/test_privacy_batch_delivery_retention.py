"""Synthetic-only evidence for 12-calendar-month bulk-send delivery history."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.privacy_batch_delivery_retention import (
    DeliveryHistoryRetentionSnapshot,
    review_delivery_history,
    summarize_delivery_history,
)
from backend.app.privacy_retention import twelve_month_cutoff


NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def row(**updates):
    base = DeliveryHistoryRetentionSnapshot(
        created_at=datetime(2025, 6, 11, 9, 0),
        delivery_status_updated_at=datetime(2025, 6, 11, 9, 10),
        tenant_ownership_verified=True,
        controller_instructions_verified=True,
        related_records_reviewed=True,
        backup_restore_plan_reviewed=True,
        legal_hold=False,
    )
    return replace(base, **updates)


def check(**changes):
    return review_delivery_history(row(**changes), as_of=NOW)


def test_reached_twelve_calendar_months_inclusive():
    assert check() == "candidate_for_manual_erasure_review"
    assert check(created_at=datetime(2025, 10, 23, 12),
                 delivery_status_updated_at=None
                 ) == "candidate_for_manual_erasure_review"
    assert check(created_at=datetime(2025, 10, 23, 12, 0, 1),
                 delivery_status_updated_at=None
                 ) == "within_12_calendar_months"


def test_status_changes_do_not_restart_clock():
    assert check(
        delivery_status_updated_at=datetime(2026, 10, 22)
    ) == "candidate_for_manual_erasure_review"
    assert check(
        delivery_status_updated_at=datetime(2026, 10, 23, 11, 59)
    ) == "candidate_for_manual_erasure_review"



def test_provider_status_older_than_local_row_creation_is_not_a_new_clock():
    # Provider event timestamps can predate a locally persisted row.
    assert check(
        delivery_status_updated_at=datetime(2025, 6, 11, 8, 59)
    ) == "candidate_for_manual_erasure_review"


def test_leap_year_cutoff_calendar_based_not_365_days():
    leap = datetime(2024, 2, 29, 11, tzinfo=timezone.utc)
    assert twelve_month_cutoff(leap) == datetime(
        2023, 2, 28, 11, tzinfo=timezone.utc
    )
    assert review_delivery_history(
        row(created_at=datetime(2023, 2, 28, 11),
            delivery_status_updated_at=None),
        as_of=leap,
    ) == "candidate_for_manual_erasure_review"


@pytest.mark.parametrize("created,expected", [
    (None, "missing_created_at"),
    ("2025-01-01", "missing_created_at"),
    (datetime(2027, 1, 1), "future_created_at"),
])
def test_invalid_creation_fails_closed(created, expected):
    assert check(created_at=created) == expected


@pytest.mark.parametrize("status_date", [
    "not-a-timestamp",
    datetime(2027, 1, 1),
])
def test_invalid_or_future_delivery_status_is_blocked(status_date):
    assert check(delivery_status_updated_at=status_date) == (
        "invalid_status_timestamp"
    )


def test_legal_hold_not_checked_or_true_blocks_expiry():
    assert check(legal_hold=None) == "legal_hold_not_checked"
    assert check(legal_hold=True) == "legal_hold"
    assert check(legal_hold="no") == "invalid_legal_hold"


@pytest.mark.parametrize("flag,reason", [
    ("tenant_ownership_verified", "tenant_ownership_not_verified"),
    ("controller_instructions_verified", "controller_instructions_not_verified"),
    ("related_records_reviewed", "related_records_not_reviewed"),
    ("backup_restore_plan_reviewed", "backup_restore_plan_not_reviewed"),
])
def test_missing_production_review_flags_cannot_approve_delete(flag, reason):
    assert check(**{flag: False}) == reason


def test_defaults_fail_closed_even_if_twelve_months_passed():
    x = DeliveryHistoryRetentionSnapshot(
        created_at=datetime(2025, 1, 1)
    )
    assert review_delivery_history(x, as_of=NOW) == (
        "legal_hold_not_checked"
    )


def test_legacy_naive_utc_and_offset_aware_dates_consistent():
    assert check() == "candidate_for_manual_erasure_review"
    assert check(
        created_at=datetime(2025, 6, 11, 12, tzinfo=timezone(timedelta(hours=3))),
        delivery_status_updated_at=None,
    ) == "candidate_for_manual_erasure_review"


def test_no_data_ever_exposed_by_aggregate_and_no_erasure():
    result = summarize_delivery_history([
        row(),
        row(created_at=NOW - timedelta(days=2),
            delivery_status_updated_at=None),
        row(legal_hold=True),
    ], as_of=NOW)
    assert result == {
        "mode": "offline_synthetic_review_only",
        "retention_months": 12,
        "retention_anchor": "batch_item_created_at_utc",
        "delivery_status_extends_deadline": False,
        "database_connected": False,
        "erasure_enabled": False,
        "erasure_performed": False,
        "total": 3,
        "candidates_for_manual_review": 1,
        "blocked_reasons": {
            "legal_hold": 1,
            "within_12_calendar_months": 1,
        },
    }


def test_no_db_api_scheduler_or_delete_in_module():
    from pathlib import Path
    source = (Path(__file__).parents[1] / "app" /
              "privacy_batch_delivery_retention.py").read_text(encoding="utf-8")
    for unsafe in (
        "sqlalchemy", "SessionLocal", "get_db(", "DELETE FROM",
        "db.execute(", "db.commit(", "requests.", "httpx.", "psycopg",
        "FastAPI(", "@app.", "router.", "DATABASE_URL",
        "subprocess.", "os.environ", "schedule.", "apscheduler",
        "celery", "import http", "template_batch_items",
    ):
        assert unsafe not in source


def test_invalid_instance_is_not_a_candidate():
    assert review_delivery_history({"created_at": NOW}, as_of=NOW) == (
        "invalid_evidence"
    )


def test_summary_only_counts_evidence_in_memory():
    summary = summarize_delivery_history([], as_of=NOW)
    assert summary["total"] == 0
    assert summary["candidates_for_manual_review"] == 0
    assert summary["erasure_performed"] is False
