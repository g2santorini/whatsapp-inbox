"""CI-ONLY, explicit-call durable redacted Instagram alert outbox prototype.

This is NOT a production notification transport or a Render worker. It
cannot create tables or start a scheduler. Every entry point rejects
non-disposable PostgreSQL identities BEFORE acquiring a database connection.
Only fabricated messages in GitHub Actions are permitted.
"""
import json
import os

from sqlalchemy import text


APPROVED_CODES = frozenset({
    "failed_deliveries", "quarantined_deliveries",
    "unresolved_processing_delivery", "pending_backlog",
    "stale_pending_delivery",
})
STATE_KEYS = frozenset({
    "pending", "processing", "processed", "quarantined", "failed",
})


class InstagramAlertOutboxDisabled(PermissionError):
    """The disposable CI-only database identity or feature gate is wrong."""


class InstagramAlertOutboxInvalid(ValueError):
    """Alert contains an unsupported code or unexpected/private data."""


def _require_disposable_ci(engine, flags):
    """Fail before any DB access if this is not the exact test-only DB."""
    url = getattr(engine, "url", None)
    dialect = getattr(getattr(engine, "dialect", None), "name", None)
    if not (
        isinstance(flags, dict)
        and flags.get("GITHUB_ACTIONS") == "true"
        and flags.get("SENDRO_INSTAGRAM_PG_CI_APPROVAL") == "ephemeral-local-service-only"
        and flags.get("INSTAGRAM_ALERT_OUTBOX_CI_ENABLED") == "true"
        and dialect == "postgresql"
        and url is not None
        and url.host == "127.0.0.1"
        and url.port == 55439
        and url.database == "sendro_ig_ci"
        and url.username == "sendro_ci"
    ):
        raise InstagramAlertOutboxDisabled(
            "Instagram alert outbox requires disposable GitHub PostgreSQL CI"
        )


def _nonnegative_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2147483647


def _validated_alert(alert):
    """Whitelist fields and values so customer identifiers cannot be stored."""
    if not isinstance(alert, dict) or set(alert) != {"codes", "states", "due", "deferred"}:
        raise InstagramAlertOutboxInvalid("Invalid redacted Instagram alert shape")
    codes = alert["codes"]
    states = alert["states"]
    if (
        not isinstance(codes, (tuple, list))
        or not codes
        or len(codes) > len(APPROVED_CODES)
        or any(not isinstance(code, str) or code not in APPROVED_CODES for code in codes)
        or len(set(codes)) != len(codes)
        or not isinstance(states, dict)
        or set(states) != STATE_KEYS
        or not all(_nonnegative_count(value) for value in states.values())
        or not _nonnegative_count(alert["due"])
        or not _nonnegative_count(alert["deferred"])
    ):
        raise InstagramAlertOutboxInvalid("Invalid Instagram alert metadata")
    # Persist counts only; no delivery IDs, account IDs, URLs or ciphertext.
    snapshot = {
        "states": {key: states[key] for key in sorted(STATE_KEYS)},
        "due": alert["due"],
        "deferred": alert["deferred"],
    }
    return tuple(codes), json.dumps(snapshot, separators=(",", ":"), sort_keys=True)


def persist_ci_instagram_alerts(engine, alert, *, environ=None):
    """Persist redacted codes in a CI-created table, atomically.

    The table is deliberately NOT provisioned by this function. A missing
    table fails closed. Repeated codes update occurrence counts, not duplicate
    rows. Returning means committed to disposable PostgreSQL, NOT delivered
    to a person or acknowledged.
    """
    flags = dict(os.environ if environ is None else environ)
    _require_disposable_ci(engine, flags)
    codes, snapshot = _validated_alert(alert)
    with engine.begin() as db:
        for code in codes:
            db.execute(text("""
                INSERT INTO public.sendro_ci_instagram_alert_outbox
                    (alert_code, snapshot, observation_count)
                VALUES (:code, CAST(:snapshot AS jsonb), 1)
                ON CONFLICT (alert_code) DO UPDATE
                SET snapshot = EXCLUDED.snapshot,
                    observation_count =
                        public.sendro_ci_instagram_alert_outbox.observation_count + 1,
                    last_seen_at = CURRENT_TIMESTAMP
            """), {"code": code, "snapshot": snapshot})
    return len(codes)


def read_ci_instagram_alerts(engine, *, environ=None):
    """Read redacted test incidents from a fresh database connection."""
    flags = dict(os.environ if environ is None else environ)
    _require_disposable_ci(engine, flags)
    with engine.connect() as db:
        rows = db.execute(text("""
            SELECT alert_code, snapshot, observation_count
            FROM public.sendro_ci_instagram_alert_outbox
            ORDER BY alert_code
        """)).mappings().all()
    return tuple({
        "code": row["alert_code"],
        "snapshot": row["snapshot"],
        "observations": row["observation_count"],
    } for row in rows)
