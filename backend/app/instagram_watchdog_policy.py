"""Pure independent Instagram operational watchdog policy (NO I/O, NO rollout).

This reusable decision function evaluates *redacted, independently gathered*
liveness/review metrics, not messages or business identifiers. It does NOT
connect to PostgreSQL, read Render/Meta, schedule jobs, deliver notifications,
enable Instagram, or attest that a live monitor exists.

Deployment requires a separate external supervisor / heartbeat collection
design and a distinct alert delivery channel with owner approval.
"""
from datetime import datetime, timedelta, timezone


class WatchdogInputDenied(ValueError):
    """Malformed or untrusted monitoring observation. Never echo input."""


EXPECTED_FIELDS = frozenset({
    "source", "captured_at", "observer_heartbeat_at",
    "dispatch_heartbeat_at", "unacknowledged_incidents",
    "oldest_unacknowledged_at", "failed_notifications",
})
EXPECTED_SOURCE = "external_supervisor"
MAX_COUNT = 1_000_000
MAX_CLOCK_SKEW = timedelta(seconds=5)
POLICY = {
    "feed_max_age": timedelta(seconds=90),
    "observer_max_age": timedelta(seconds=120),
    "dispatcher_max_age": timedelta(seconds=300),
    "human_review_max_age": timedelta(minutes=15),
}
CRITICAL_CODES = frozenset({
    "observation_feed_stale", "observer_heartbeat_missing",
    "observer_heartbeat_stale", "dispatcher_heartbeat_missing",
    "dispatcher_heartbeat_stale", "notification_delivery_failed",
    "monitor_clock_anomaly",
})


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise WatchdogInputDenied("Invalid redacted monitoring timestamp")
    return value.astimezone(timezone.utc)


def _count(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise WatchdogInputDenied("Invalid redacted monitoring count")
    if not 0 <= value <= MAX_COUNT:
        raise WatchdogInputDenied("Invalid redacted monitoring count")
    return value


def evaluate_instagram_watchdog(snapshot, *, now):
    """Return generic operational escalation codes, never input contents.

    All input keys are exact and explicit. A caller cannot accidentally
    smuggle guest IDs or tokens into output. This is a POLICY decision
    for a separately deployed watchdog; it cannot send an alert or
    guarantee that its supplied observations are independently verified.

    Missing or stale observer/dispatcher heartbeats escalate EVEN WHEN
    there are zero queued messages, so an inactive worker cannot look
    healthy merely because no queue health alerts were produced.
    """
    moment = _utc(now)
    if not isinstance(snapshot, dict) or set(snapshot) != EXPECTED_FIELDS:
        raise WatchdogInputDenied("Invalid redacted monitoring snapshot")
    if snapshot["source"] != EXPECTED_SOURCE:
        raise WatchdogInputDenied("Invalid monitoring source")
    captured = _utc(snapshot["captured_at"])
    observer = (
        _utc(snapshot["observer_heartbeat_at"])
        if snapshot["observer_heartbeat_at"] is not None else None
    )
    dispatcher = (
        _utc(snapshot["dispatch_heartbeat_at"])
        if snapshot["dispatch_heartbeat_at"] is not None else None
    )
    review = (
        _utc(snapshot["oldest_unacknowledged_at"])
        if snapshot["oldest_unacknowledged_at"] is not None else None
    )
    unacknowledged = _count(snapshot["unacknowledged_incidents"])
    failures = _count(snapshot["failed_notifications"])
    if (unacknowledged == 0) != (review is None):
        raise WatchdogInputDenied("Invalid open incident timestamp")
    if any(
        value > captured + MAX_CLOCK_SKEW
        or value > moment + MAX_CLOCK_SKEW
        for value in (observer, dispatcher, review)
        if value is not None
    ):
        return {
            "decision": "ESCALATE",
            "severity": "critical",
            "codes": ("monitor_clock_anomaly",),
            "operator_notification_required": True,
            "independently_verified": False,
            "live_pilot_authorized": False,
        }

    codes = set()
    # If the independent source itself has stopped publishing, never
    # report a nominal outcome from old success heartbeats.
    if captured > moment + MAX_CLOCK_SKEW:
        codes.add("monitor_clock_anomaly")
    elif moment - captured > POLICY["feed_max_age"]:
        codes.add("observation_feed_stale")
    if observer is None:
        codes.add("observer_heartbeat_missing")
    elif moment - observer > POLICY["observer_max_age"]:
        codes.add("observer_heartbeat_stale")
    if dispatcher is None:
        codes.add("dispatcher_heartbeat_missing")
    elif moment - dispatcher > POLICY["dispatcher_max_age"]:
        codes.add("dispatcher_heartbeat_stale")
    if failures:
        codes.add("notification_delivery_failed")
    if review is not None and moment - review > POLICY["human_review_max_age"]:
        codes.add("incident_review_overdue")

    ordered = tuple(sorted(codes))
    severity = (
        "critical" if any(c in CRITICAL_CODES for c in ordered)
        else "warning" if ordered else "none"
    )
    return {
        "decision": "ESCALATE" if ordered else "NOMINAL_UNVERIFIED",
        "severity": severity,
        "codes": ordered,
        "operator_notification_required": bool(ordered),
        "independently_verified": False,
        "live_pilot_authorized": False,
    }
