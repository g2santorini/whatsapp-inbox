"""No live DB/network; all retention review inputs are fabricated."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.privacy_retention import (
    ConversationRetentionSnapshot,
    review_retention_candidate,
    summarize_offline_review,
    twelve_month_cutoff,
)


NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def synthetic_record(**overrides):
    base = ConversationRetentionSnapshot(
        status="archived",
        created_at=datetime(2024, 5, 10),
        updated_at=datetime(2025, 9, 15),
        last_message_at=datetime(2025, 9, 10),
        latest_related_message_at=datetime(2025, 9, 14),
        unread_count=0,
        assigned_to_user_id=None,
        follow_up=False,
        activity_review_complete=True,
        references_review_complete=True,
        legal_hold=False,
    )
    return replace(base, **overrides)


def evaluate(**overrides):
    return review_retention_candidate(synthetic_record(**overrides), as_of=NOW)


def test_exact_twelve_calendar_months_not_fixed_days():
    assert twelve_month_cutoff(NOW) == datetime(2025, 10, 16, 12, tzinfo=timezone.utc)
    assert twelve_month_cutoff(datetime(2024, 2, 29, tzinfo=timezone.utc)) == (
        datetime(2023, 2, 28, tzinfo=timezone.utc)
    )
    with pytest.raises(ValueError):
        twelve_month_cutoff(None)


def test_old_closed_or_archived_can_only_be_review_candidates():
    assert evaluate() == "candidate_for_manual_review"
    assert evaluate(status="closed") == "candidate_for_manual_review"


@pytest.mark.parametrize("status", ["open", "taken", "pending", "unknown", ""])
def test_active_or_unknown_status_is_never_a_candidate(status):
    assert evaluate(status=status) == "active_conversation"


@pytest.mark.parametrize("override", [
    {"unread_count": 1},
    {"unread_count": -1},
    {"unread_count": True},
    {"assigned_to_user_id": 17},
    {"follow_up": True},
])
def test_pending_or_invalid_work_is_blocked(override):
    assert evaluate(**override) == "pending_work"


def test_legal_hold_is_explicit_and_fail_closed():
    assert evaluate(legal_hold=True) == "legal_hold"
    assert evaluate(legal_hold=None) == "legal_hold_not_checked"


def test_missing_approvals_block_even_old_archived_messages():
    assert evaluate(activity_review_complete=False) == "activity_not_verified"
    assert evaluate(references_review_complete=False) == "references_not_verified"


@pytest.mark.parametrize("field", ["created_at", "updated_at", "last_message_at"])
def test_missing_required_activity_date_blocks(field):
    assert evaluate(**{field: None}) == "missing_activity_timestamp"


def test_newer_message_overrides_stale_conversation_timestamp():
    assert evaluate(
        latest_related_message_at=NOW - timedelta(days=3)
    ) == "within_retention_period"


def test_recent_update_or_creation_also_blocks():
    assert evaluate(updated_at=NOW) == "within_retention_period"
    assert evaluate(created_at=NOW) == "within_retention_period"


def test_boundary_inclusive_and_future_timestamp_blocked():
    cutoff = twelve_month_cutoff(NOW)
    assert evaluate(created_at=cutoff, updated_at=cutoff,
                    last_message_at=cutoff, latest_related_message_at=cutoff
                    ) == "candidate_for_manual_review"
    assert evaluate(last_message_at=NOW + timedelta(days=1)
                    ) == "within_retention_period"


def test_timezone_offsets_and_legacy_naive_utc_are_consistent():
    offset = timezone(timedelta(hours=3))
    recent = datetime(2025, 10, 16, 16, 0, tzinfo=offset)
    assert evaluate(latest_related_message_at=recent) == "within_retention_period"
    assert evaluate() == "candidate_for_manual_review"


def test_bad_message_timestamp_fails_closed():
    assert evaluate(latest_related_message_at="not-a-date"
                    ) == "invalid_activity_timestamp"


def test_invalid_evidence_is_blocked():
    assert review_retention_candidate("not-a-record", as_of=NOW) == "invalid_evidence"


def test_summary_is_aggregate_only_and_never_deletes_or_exposes_pii():
    result = summarize_offline_review([
        synthetic_record(),
        synthetic_record(status="open"),
        synthetic_record(last_message_at=NOW),
    ], as_of=NOW)
    assert result == {
        "mode": "offline_review_only",
        "retention_months": 12,
        "database_connected": False,
        "deletion_enabled": False,
        "total": 3,
        "candidates_for_manual_review": 1,
        "blocked_reasons": {
            "active_conversation": 1,
            "within_retention_period": 1,
        },
    }


def test_module_is_inert_no_database_api_network_scheduler_or_erasure():
    from pathlib import Path
    source = (Path(__file__).parents[1] / "app" /
              "privacy_retention.py").read_text(encoding="utf-8")
    for dangerous in (
        "create_engine(", "SessionLocal", "get_db(", "DELETE FROM",
        "db.execute(", "db.commit(", "requests.", "httpx.",
        "FastAPI(", "@app.", "router.", "DATABASE_URL", "subprocess.",
        "os.environ", "schedule.", "apscheduler", "celery",
    ):
        assert dangerous not in source
