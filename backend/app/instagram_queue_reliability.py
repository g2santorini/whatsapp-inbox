"""Instagram queue health and dormant retry primitives (Phase 2K-A).

This module is NOT a scheduler and is never called on FastAPI startup.
No API calls, no tokens or customer details. Retrying a delivery requires
a separately approved, isolated runner and a rolled-back transient failure.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def is_transient_database_failure(error):
    """Only retry well-identified transient SQL errors, never all DB errors.

    PostgreSQL SQLSTATE 08xxx (connection), 40001 (serialization),
    40P01 (deadlock), 55P03 (lock not available). SQL syntax/schema and
    customer-data failures must not trigger automatic retries.
    """
    if not isinstance(error, DBAPIError):
        return False
    if error.connection_invalidated:
        return True
    orig = getattr(error, "orig", None)
    state = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return isinstance(state, str) and (
        state.startswith("08") or state in {"40001", "40P01", "55P03"}
    )


MAX_RETRY_ATTEMPTS = 5
RETRY_BASE_SECONDS = 30
RETRY_MAX_SECONDS = 3600


def _utc_now(now=None):
    value = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise TypeError("now must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def retry_delay_seconds(attempt_number: int) -> int:
    """Exponential retry delay, capped at one hour, no immediate retry loop."""
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
        raise ValueError("attempt_number must be a positive integer")
    if attempt_number < 1:
        raise ValueError("attempt_number must be positive")
    return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** min(attempt_number - 1, 20)))


def schedule_transient_retry(
    engine, delivery_id: int, expected_attempts: int, *,
    now=None, max_attempts: int = MAX_RETRY_ATTEMPTS,
):
    """CAS-schedule a retry AFTER a failed worker transaction has rolled back.

    Caller must first establish the exact delivery ID/attempts inside its
    locked transaction, and catch ONLY retryable, transient DB exceptions.
    This operation is not wired to the current worker or operator CLI.

    Guarded UPDATE prevents touching a processed/quarantined/other-provider
    row. It does not claim a row or implement a background service. If the
    DB is unavailable the error propagates; it must never be acknowledged
    as successfully scheduled.
    """
    if (
        isinstance(delivery_id, bool) or not isinstance(delivery_id, int)
        or delivery_id < 1
        or isinstance(expected_attempts, bool) or not isinstance(expected_attempts, int)
        or expected_attempts < 0
        or isinstance(max_attempts, bool) or not isinstance(max_attempts, int)
        or max_attempts < 1
    ):
        raise ValueError("invalid delivery retry arguments")

    attempt = expected_attempts + 1
    is_final = attempt >= max_attempts
    next_at = None if is_final else _utc_now(now) + timedelta(seconds=retry_delay_seconds(attempt))
    new_state = "failed" if is_final else "pending"

    with engine.begin() as db:
        result = db.execute(text("""
            UPDATE public.sendro_channel_webhook_deliveries
            SET attempts = :attempt,
                processing_state = :new_state,
                next_attempt_at = :next_attempt_at,
                last_error_code = 'transient_processing_failure',
                processed_at = CASE WHEN :is_final = 1 THEN CURRENT_TIMESTAMP
                                    ELSE NULL END
            WHERE id = :delivery_id
              AND provider = 'instagram'
              AND processing_state = 'pending'
              AND attempts = :expected_attempts
        """), {
            "delivery_id": delivery_id,
            "expected_attempts": expected_attempts,
            "attempt": attempt,
            "new_state": new_state,
            "next_attempt_at": next_at,
            "is_final": int(is_final),
        })
        updated = result.rowcount == 1
    return {"updated": updated, "state": new_state if updated else None,
            "attempts": attempt if updated else None,
            "retry_at": next_at if updated else None}


def _to_datetime(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def read_instagram_queue_health(
    engine, *, now=None, backlog_threshold=50, stale_minutes=15,
):
    """Read aggregate operational health without reading DM contents or IDs."""
    if backlog_threshold < 1 or stale_minutes < 1:
        raise ValueError("invalid alert thresholds")
    current = _utc_now(now)
    with engine.connect() as db:
        state_rows = db.execute(text("""
            SELECT processing_state, COUNT(*) AS total
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram'
            GROUP BY processing_state
        """)).all()
        due = db.execute(text("""
            SELECT COUNT(*) AS due_count, MIN(received_at) AS oldest_received_at
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram'
              AND processing_state = 'pending'
              AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
        """), {"now": current}).one()
        delayed_count = db.execute(text("""
            SELECT COUNT(*)
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram'
              AND processing_state = 'pending'
              AND next_attempt_at > :now
        """), {"now": current}).scalar_one()

    states = {str(state): int(count) for state, count in state_rows}
    due_count = int(due[0])
    oldest = _to_datetime(due[1])
    oldest_age_seconds = (
        max(0, int((current - oldest).total_seconds())) if oldest else None
    )
    alert_codes = []
    if states.get("failed", 0):
        alert_codes.append("failed_deliveries")
    if states.get("quarantined", 0):
        alert_codes.append("quarantined_deliveries")
    # The bounded worker transitions pending -> processed/quarantined inside
    # ONE transaction. A committed 'processing' state is therefore NOT a
    # normal in-flight worker lock; it can be orphaned and would otherwise
    # disappear from due/backlog alerts indefinitely.
    if states.get("processing", 0):
        alert_codes.append("unresolved_processing_delivery")
    if due_count >= backlog_threshold:
        alert_codes.append("pending_backlog")
    if oldest_age_seconds is not None and oldest_age_seconds >= stale_minutes * 60:
        alert_codes.append("stale_pending_delivery")

    return {
        "states": {name: states.get(name, 0) for name in (
            "pending", "processing", "processed", "quarantined", "failed",
        )},
        "due": due_count,
        "deferred": int(delayed_count),
        "oldest_due_age_seconds": oldest_age_seconds,
        "alert_codes": alert_codes,
    }


def main():
    """Optional operator-only read-only health CLI, no side effects."""
    from .database import engine

    try:
        status = read_instagram_queue_health(engine)
    except Exception:
        print("Instagram queue health: ERROR - inspect restricted logs")
        return 1

    print("Instagram queue health: READ ONLY")
    for name, count in status["states"].items():
        print(f"{name}: {count}")
    print(f"due: {status['due']}")
    print(f"deferred: {status['deferred']}")
    print("alerts: " + (", ".join(status["alert_codes"]) or "none"))
    print("No deliveries processed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
