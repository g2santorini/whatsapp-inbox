"""Fast no-network tests for independent Instagram watchdog escalation policy."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

import pytest

from backend.app.instagram_watchdog_policy import (
    EXPECTED_FIELDS, WatchdogInputDenied, evaluate_instagram_watchdog,
)

NOW = datetime(2026, 10, 22, 7, 0, tzinfo=timezone.utc)


def snapshot(**changes):
    item = {
        "source": "external_supervisor",
        "captured_at": NOW - timedelta(seconds=3),
        "observer_heartbeat_at": NOW - timedelta(seconds=10),
        "dispatch_heartbeat_at": NOW - timedelta(seconds=20),
        "unacknowledged_incidents": 0,
        "oldest_unacknowledged_at": None,
        "failed_notifications": 0,
    }
    item.update(changes)
    assert set(item) == EXPECTED_FIELDS or changes.keys() - EXPECTED_FIELDS
    return item


def check(item):
    return evaluate_instagram_watchdog(item, now=NOW)


def test_fresh_heartbeat_and_no_alerts_never_means_pilot_approved():
    result = check(snapshot())
    assert result == {
        "decision": "NOMINAL_UNVERIFIED",
        "severity": "none",
        "codes": (),
        "operator_notification_required": False,
        "independently_verified": False,
        "live_pilot_authorized": False,
    }


def test_independent_heartbeat_missing_and_stale_must_escalate_empty_queue():
    cases = (
        ("observer_heartbeat_at", None, "observer_heartbeat_missing"),
        ("observer_heartbeat_at", NOW - timedelta(seconds=121),
         "observer_heartbeat_stale"),
        ("dispatch_heartbeat_at", None, "dispatcher_heartbeat_missing"),
        ("dispatch_heartbeat_at", NOW - timedelta(seconds=301),
         "dispatcher_heartbeat_stale"),
    )
    for field, value, code in cases:
        result = check(snapshot(**{field: value}))
        assert result["decision"] == "ESCALATE"
        assert result["severity"] == "critical"
        assert code in result["codes"]
        assert result["operator_notification_required"] is True


def test_a_stale_independent_feed_masks_no_health_assumptions():
    result = check(snapshot(
        captured_at=NOW - timedelta(seconds=91),
        observer_heartbeat_at=NOW - timedelta(seconds=100),
        dispatch_heartbeat_at=NOW - timedelta(seconds=110),
    ))
    assert "observation_feed_stale" in result["codes"]
    assert result["severity"] == "critical"
    assert not result["live_pilot_authorized"]


def test_failure_of_all_synthetic_notifications_is_critical():
    result = check(snapshot(failed_notifications=3))
    assert result["codes"] == ("notification_delivery_failed",)
    assert result["severity"] == "critical"


def test_overdue_manual_review_is_warning_when_observer_and_dispatch_healthy():
    result = check(snapshot(
        unacknowledged_incidents=2,
        oldest_unacknowledged_at=NOW - timedelta(minutes=16),
    ))
    assert result["codes"] == ("incident_review_overdue",)
    assert result["severity"] == "warning"
    assert result["operator_notification_required"]


def test_both_overdue_ack_and_outage_escalate_to_critical():
    result = check(snapshot(
        observer_heartbeat_at=None, failed_notifications=2,
        unacknowledged_incidents=1,
        oldest_unacknowledged_at=NOW - timedelta(minutes=30),
    ))
    assert result["severity"] == "critical"
    assert result["codes"] == (
        "incident_review_overdue", "notification_delivery_failed",
        "observer_heartbeat_missing",
    )


@pytest.mark.parametrize("bad", [
    None, [], "healthy", True,
    {}, {"source": "external_supervisor"},
])
def test_missing_and_nonmapping_snapshots_refuse_any_result(bad):
    with pytest.raises(WatchdogInputDenied):
        check(bad)


def test_unexpected_personal_fields_are_refused_and_not_echoed():
    dangerous = snapshot()
    dangerous["guest_message"] = "SECRET-PRIVATE-DM-CONTENT"
    dangerous["tenant_id"] = "SECRET-TENANT"
    with pytest.raises(WatchdogInputDenied) as raised:
        check(dangerous)
    assert "SECRET" not in str(raised.value)


@pytest.mark.parametrize("field,value", [
    ("source", "browser-client"),
    ("source", True),
    ("captured_at", "2026-10-22T07:00:00Z"),
    ("captured_at", datetime(2026, 10, 22, 7, 0)),
    ("observer_heartbeat_at", "2026-10-22T07:00:00"),
    ("dispatch_heartbeat_at", 7),
    ("unacknowledged_incidents", -1),
    ("unacknowledged_incidents", True),
    ("unacknowledged_incidents", 1000001),
    ("failed_notifications", 1.0),
    ("oldest_unacknowledged_at", NOW - timedelta(seconds=4)),
])
def test_malformed_metadata_fails_closed(field, value):
    data = snapshot(**{field: value})
    if field == "oldest_unacknowledged_at":
        data["unacknowledged_incidents"] = 0  # mismatched timestamp/count
    with pytest.raises(WatchdogInputDenied):
        check(data)


def test_open_incidents_require_an_oldest_review_timestamp():
    with pytest.raises(WatchdogInputDenied):
        check(snapshot(unacknowledged_incidents=1))
    with pytest.raises(WatchdogInputDenied):
        check(snapshot(oldest_unacknowledged_at=NOW - timedelta(minutes=5)))


def test_future_monitoring_timestamps_flag_clock_anomaly_without_leak():
    result = check(snapshot(captured_at=NOW + timedelta(minutes=3)))
    assert result["codes"] == ("monitor_clock_anomaly",)
    assert result["severity"] == "critical"

    result2 = check(snapshot(
        observer_heartbeat_at=NOW + timedelta(hours=1)
    ))
    assert result2["codes"] == ("monitor_clock_anomaly",)

    # A heartbeat may be only four seconds ahead of its snapshot
    # but still more than five seconds ahead of the trusted clock.
    result3 = check(snapshot(
        captured_at=NOW + timedelta(seconds=5),
        observer_heartbeat_at=NOW + timedelta(seconds=9),
    ))
    assert result3["codes"] == ("monitor_clock_anomaly",)


def test_cleared_issue_never_leaves_persistent_false_alerts():
    before = check(snapshot(failed_notifications=1))
    after = check(snapshot())
    assert before["operator_notification_required"]
    assert not after["operator_notification_required"]
    assert before["codes"] != after["codes"]


def test_repeated_failing_samples_are_deterministic_and_contain_no_pii():
    dangerous_secret = "DO-NOT-LEAK-FAKE-DB-PASSWORD"
    event = snapshot(observer_heartbeat_at=None, failed_notifications=1)
    event["source"] = "external_supervisor"
    first, second = check(event), check(event)
    assert first == second
    assert set(first) == {
        "decision", "severity", "codes", "operator_notification_required",
        "independently_verified", "live_pilot_authorized",
    }
    assert dangerous_secret not in json.dumps(first)
    assert all(isinstance(code, str) and code.startswith(
        ("observer_", "notification_")
    ) for code in first["codes"])


def test_policy_module_is_offline_without_io_hooks():
    source = (Path(__file__).parents[1] / "app" /
              "instagram_watchdog_policy.py").read_text()
    for unsafe in (
        "requests.", "httpx.", "create_engine", "SessionLocal",
        "get_db(", "DATABASE_URL", "FastAPI(", "APIRouter(",
        "send_email", "send_message", "process_one_pending_instagram_delivery",
        "subprocess.", "os.environ", "threading.", "asyncio.",
    ):
        assert unsafe not in source
