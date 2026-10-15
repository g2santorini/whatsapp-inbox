"""Offline supervised Instagram delivery batch, Phase 2K-B prototype.

STRICTLY INERT: no CLI, daemon, scheduler, FastAPI hook or Render process.
Only approved in-memory SQLite exercise is allowed; a later separate PR must
add isolated PostgreSQL, actual alert transport and supervised deployment.
"""
import os

from .instagram_delivery_worker import (
    InstagramTransientDeliveryFailure,
    process_one_pending_instagram_delivery,
)
from .instagram_queue_reliability import (
    read_instagram_queue_health,
    schedule_transient_retry,
)


MAX_BATCH_SIZE = 25


class InstagramSupervisorDisabled(PermissionError):
    """Fail-closed gate for unapproved runner execution."""


class InstagramSupervisorFailure(RuntimeError):
    """Sanitized error for operational alerting without customer data."""


def _require_isolated_test_gate(engine, key, environ, *, max_deliveries, on_alert):
    if (
        environ.get("INSTAGRAM_SUPERVISOR_TEST_ENABLED", "").strip() != "true"
        or environ.get("INSTAGRAM_ISOLATED_DB_APPROVED", "").strip() != "true"
        or engine.dialect.name != "sqlite"
        or not key
        or not callable(on_alert)
        or isinstance(max_deliveries, bool)
        or not isinstance(max_deliveries, int)
        or not 1 <= max_deliveries <= MAX_BATCH_SIZE
    ):
        raise InstagramSupervisorDisabled(
            "Instagram supervised worker is disabled or isolation is not approved"
        )


def run_isolated_supervised_batch(
    engine,
    encryption_key,
    *,
    environ=None,
    max_deliveries=10,
    on_alert=None,
):
    """Process a bounded, offline test batch in an explicitly gated SQLite DB.

    Events surfaced to the callback contain generic health codes and state
    totals ONLY. Callback errors abort the run instead of silently losing alerts.

    All DB writes occur via the existing transactional Instagram worker and the
    Phase 2K-A guarded, post-rollback retry scheduler. The guard rejects ANY
    PostgreSQL engine even if the environment flags are mistakenly enabled.
    """
    flags = os.environ if environ is None else environ
    _require_isolated_test_gate(
        engine, encryption_key, flags,
        max_deliveries=max_deliveries, on_alert=on_alert,
    )

    counts = {"processed": 0, "quarantined": 0, "deferred": 0,
              "failed": 0, "messages": 0}
    for _ in range(max_deliveries):
        try:
            outcome = process_one_pending_instagram_delivery(engine, encryption_key)
        except InstagramTransientDeliveryFailure as exc:
            # The original worker transaction has already rolled back; this
            # only CAS-updates the exact pending Instagram row and attempt.
            try:
                retry = schedule_transient_retry(
                    engine, exc.delivery_id, exc.expected_attempts
                )
            except Exception:
                raise InstagramSupervisorFailure(
                    "Instagram retry storage unavailable"
                ) from None
            if not retry["updated"]:
                # Another runner may have processed/claimed it; do not
                # overwrite its state or silently count a retry.
                raise InstagramSupervisorFailure(
                    "Instagram retry scheduling conflict"
                ) from None
            counts["failed" if retry["state"] == "failed" else "deferred"] += 1
            continue
        except Exception:
            # Fatal config, unexpected data and unknown database errors must
            # NOT be silently retried or logged with raw payloads.
            raise InstagramSupervisorFailure(
                "Instagram delivery processing requires operator review"
            ) from None

        if outcome.status == "idle":
            break
        if outcome.status not in ("processed", "quarantined"):
            raise InstagramSupervisorFailure("Instagram worker returned unknown state")
        counts[outcome.status] += 1
        counts["messages"] += outcome.inserted_messages

    try:
        health = read_instagram_queue_health(engine)
    except Exception:
        raise InstagramSupervisorFailure(
            "Instagram queue health unavailable"
        ) from None

    # Include all aggregate alert codes, plus terminal failures detected in
    # the just-run batch. No IDs, URLs, message text, tokens or raw exceptions.
    codes = tuple(health["alert_codes"])
    if codes:
        try:
            on_alert({"codes": codes, "states": dict(health["states"]),
                      "due": health["due"], "deferred": health["deferred"]})
        except Exception:
            raise InstagramSupervisorFailure(
                "Instagram operational alert callback failed"
            ) from None

    return {"processed": counts["processed"], "quarantined": counts["quarantined"],
            "deferred": counts["deferred"], "failed": counts["failed"],
            "messages": counts["messages"], "alerts": codes}
