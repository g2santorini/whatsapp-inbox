"""Phase 2R: bounded Instagram supervisor rehearsal on *ephemeral CI PostgreSQL*.

This is NOT a live PostgreSQL runner, not a daemon, not a Render CLI, and not
wired into FastAPI startup or a scheduler. Its gate deliberately REJECTS the
production-shared Render database even when feature flags are set. It has no
outbound Meta API calls and no real alert transport. All content is synthetic.
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


MAX_CI_BATCH_SIZE = 5


class InstagramPostgresSupervisorDisabled(PermissionError):
    """CI-only operator gate has not been fully satisfied."""


class InstagramPostgresSupervisorFailure(RuntimeError):
    """Sanitized failure; do not pass raw database exceptions or customer data."""


def _require_ci_only(engine, key, flags, *, max_deliveries, on_alert):
    """Reject all other engines BEFORE the first database connection/statement."""
    url = getattr(engine, "url", None)
    dialect = getattr(getattr(engine, "dialect", None), "name", None)
    if (
        not isinstance(flags, dict)
        or flags.get("GITHUB_ACTIONS") != "true"
        or flags.get("SENDRO_INSTAGRAM_PG_CI_APPROVAL") != "ephemeral-local-service-only"
        or flags.get("INSTAGRAM_PG_SUPERVISION_CI_ENABLED") != "true"
        or dialect != "postgresql"
        or url is None
        or url.host != "127.0.0.1"
        or url.port != 55439
        or url.database != "sendro_ig_ci"
        or url.username != "sendro_ci"
        or not isinstance(key, str)
        or not key
        or not callable(on_alert)
        or isinstance(max_deliveries, bool)
        or not isinstance(max_deliveries, int)
        or not 1 <= max_deliveries <= MAX_CI_BATCH_SIZE
    ):
        raise InstagramPostgresSupervisorDisabled(
            "Instagram PostgreSQL supervision requires disposable GitHub CI"
        )


def run_ephemeral_postgres_supervised_batch(
    engine, encryption_key, *, environ=None, max_deliveries=3, on_alert=None
):
    """Run a tiny, supervised synthetic batch in disposable CI PostgreSQL only.

    Each delivery uses the existing atomic, SKIP LOCKED worker transaction.
    Only identified transient database errors are retried after rollback,
    using compare-and-swap. Unexpected errors, retry conflicts and health/
    alert callback failures stop processing with a sanitized error.

    The on_alert callback is in-process, NOT a reliable production alert
    transport. The final result exposes only aggregate counts and generic
    alert codes. No IDs, ciphertext, personal data, secrets, SQL or URLs.
    """
    flags = dict(os.environ if environ is None else environ)
    _require_ci_only(
        engine, encryption_key, flags,
        max_deliveries=max_deliveries, on_alert=on_alert,
    )
    counts = {
        "processed": 0, "quarantined": 0, "deferred": 0,
        "failed": 0, "messages": 0,
    }
    for _ in range(max_deliveries):
        try:
            outcome = process_one_pending_instagram_delivery(
                engine, encryption_key
            )
        except InstagramTransientDeliveryFailure as exc:
            # The original worker transaction has completely rolled back.
            try:
                retry = schedule_transient_retry(
                    engine, exc.delivery_id, exc.expected_attempts
                )
            except Exception:
                raise InstagramPostgresSupervisorFailure(
                    "Instagram retry state unavailable"
                ) from None
            if not retry["updated"]:
                raise InstagramPostgresSupervisorFailure(
                    "Instagram retry scheduling conflict"
                ) from None
            if retry["state"] not in ("failed", "pending"):
                raise InstagramPostgresSupervisorFailure(
                    "Instagram retry returned unknown state"
                ) from None
            counts["failed" if retry["state"] == "failed" else "deferred"] += 1
            continue
        except Exception:
            raise InstagramPostgresSupervisorFailure(
                "Instagram delivery requires operator review"
            ) from None

        if outcome.status == "idle":
            break
        if outcome.status not in ("processed", "quarantined"):
            raise InstagramPostgresSupervisorFailure(
                "Instagram delivery returned unknown state"
            )
        counts[outcome.status] += 1
        counts["messages"] += outcome.inserted_messages

    try:
        health = read_instagram_queue_health(engine)
    except Exception:
        raise InstagramPostgresSupervisorFailure(
            "Instagram queue health unavailable"
        ) from None

    codes = tuple(health["alert_codes"])
    if codes:
        # Sanitize payload. The callback is a TEST HOOK, not a remote service.
        safe_alert = {
            "codes": codes,
            "states": dict(health["states"]),
            "due": health["due"],
            "deferred": health["deferred"],
        }
        try:
            on_alert(safe_alert)
        except Exception:
            raise InstagramPostgresSupervisorFailure(
                "Instagram alert callback failed"
            ) from None

    return {**counts, "alerts": codes}
