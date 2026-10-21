"""CI-only independent Instagram queue health observer / alert persistence proof.

NOT a Render daemon, periodic task, webhook, worker, or live notification
transport. An explicit test caller can inspect a disposable PostgreSQL queue
and persist a sanitized alert after another worker has already committed or
crashed. No Instagram messages are ever processed or modified here.

Every public call is gated on the exact ephemeral GitHub Actions PostgreSQL
identity BEFORE any database connection. Importing this module does nothing.
"""
import os

from .instagram_alert_outbox_ci import (
    _require_disposable_ci,
    persist_ci_instagram_alerts,
)
from .instagram_queue_reliability import read_instagram_queue_health


class InstagramAlertObserverDisabled(PermissionError):
    """The test-only independent observer has not been explicitly enabled."""


class InstagramAlertObserverFailure(RuntimeError):
    """Redacted failure: queue health or durable alert record unavailable."""


def observe_ephemeral_instagram_alerts(
    engine, *, environ=None, now=None, backlog_threshold=50, stale_minutes=15,
):
    """One **explicit** synthetic queue sample, independent of any worker.

    Alerts are durably recorded through the CI-only outbox, not delivered to
    operators. The observer NEVER processes, retries, acknowledges, deletes,
    or rewrites a delivery. No background poll schedule is created.

    If this call is interrupted between reading health and committing the
    alert, the next explicitly invoked sample may recover the incident as
    long as the queue condition remains observable. A one-off transient
    incident that clears before a later sample could still be missed.
    """
    flags = dict(os.environ if environ is None else environ)
    _require_disposable_ci(engine, flags)
    if flags.get("INSTAGRAM_ALERT_OBSERVER_CI_ENABLED") != "true":
        raise InstagramAlertObserverDisabled(
            "Instagram queue observer is only available in disposable CI"
        )

    try:
        health = read_instagram_queue_health(
            engine, now=now, backlog_threshold=backlog_threshold,
            stale_minutes=stale_minutes,
        )
        codes = tuple(health["alert_codes"])
        if not codes:
            return {"alert_codes": (), "persisted": 0}
        safe_event = {
            "codes": codes,
            "states": health["states"],
            "due": health["due"],
            "deferred": health["deferred"],
        }
        saved = persist_ci_instagram_alerts(
            engine, safe_event, environ=flags,
        )
    except Exception:
        # Do not propagate SQL, exception strings, ciphertext or identifiers.
        raise InstagramAlertObserverFailure(
            "Instagram queue observation or alert persistence unavailable"
        ) from None

    return {"alert_codes": codes, "persisted": saved}
