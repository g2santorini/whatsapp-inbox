"""One-shot Instagram aggregate observer with an independently limited SQL role.

INERT: no startup hook, scheduler, CLI, Render DB credential, Meta call,
customer query or outbound notification. The caller must supply a dedicated
connection using role sendro_instagram_observer_ro AND a separate explicit
approval mapping. No live approval or role has been provisioned.

The observation query uses ONLY four nonsensitive delivery metadata columns.
The observer refuses an elevated role or a role with SELECT privilege over
encrypted delivery payloads, hashes, delivery IDs or any DML/DDL privilege.
One short transaction is explicitly READ ONLY. All errors are redacted.

Live deployment cannot be inferred from successful CI: granting privileges
on shared Render PostgreSQL or creating a service requires separate approval.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from .instagram_queue_reliability import _utc_now


APPROVAL_NAME = "SENDRO_IG_RESTRICTED_OBSERVER_ENABLED"
EXACT_APPROVAL = "I_APPROVE_DEDICATED_READ_ONLY_INSTAGRAM_OBSERVER"
ROLE = "sendro_instagram_observer_ro"
CI_APPROVAL = "ephemeral-local-service-only"
EXPECTED_METADATA = ("provider", "processing_state", "next_attempt_at", "received_at")
SECRET_COLUMNS = (
    "payload_ciphertext", "raw_body_sha256", "id", "last_error_code",
)
ALERT_CODES = (
    "failed_deliveries", "quarantined_deliveries",
    "unresolved_processing_delivery", "pending_backlog",
    "stale_pending_delivery",
)
TABLE = "public.sendro_channel_webhook_deliveries"


class ReadonlyObserverDenied(PermissionError):
    """No permitted dedicated read-only PostgreSQL observer identity."""


class ReadonlyObserverUnavailable(RuntimeError):
    """Sanitized database outage or privilege proof failure."""


def _guard(engine, environ):
    """Check claimed role/URL and independent opt-in BEFORE any DB access."""
    url = getattr(engine, "url", None)
    dialect = getattr(getattr(engine, "dialect", None), "name", None)
    if (
        not isinstance(environ, dict)
        or environ.get(APPROVAL_NAME) != EXACT_APPROVAL
        or url is None or dialect != "postgresql"
        or url.drivername != "postgresql+psycopg"
        or url.username != ROLE
    ):
        raise ReadonlyObserverDenied("Dedicated Instagram observer disabled")

    if environ.get("GITHUB_ACTIONS") == "true":
        if not (
            environ.get("SENDRO_INSTAGRAM_PG_CI_APPROVAL") == CI_APPROVAL
            and url.host == "127.0.0.1" and url.port == 55439
            and url.database == "sendro_ig_ci"
        ):
            raise ReadonlyObserverDenied("Dedicated Instagram observer disabled")
    elif not (
        # No accidental loopback CI or unrelated DB usage outside CI.
        environ.get("SENDRO_IG_OBSERVER_OWNER_ATTESTATION")
        == "DEDICATED_ROLE_AND_SHARED_DB_READ_APPROVED"
        and url.database == "sendro"
        and url.host not in (None, "localhost", "127.0.0.1")
        and url.query.get("sslmode") in ("verify-full", "require")
    ):
        raise ReadonlyObserverDenied("Dedicated Instagram observer disabled")


def _prove_restricted_role(db):
    role = db.execute(text("""
        SELECT rolcanlogin, rolsuper, rolcreaterole, rolcreatedb,
               rolreplication, rolbypassrls
        FROM pg_catalog.pg_roles
        WHERE rolname = current_user
    """)).mappings().one_or_none()
    if role is None or (
        role["rolcanlogin"] is not True
        or any(role[key] for key in (
            "rolsuper", "rolcreaterole", "rolcreatedb",
            "rolreplication", "rolbypassrls",
        ))
    ):
        raise ReadonlyObserverDenied("Observer role has elevated privileges")

    permissions = db.execute(text("""
        SELECT
            has_schema_privilege(current_user, 'public', 'CREATE') AS schema_create,
            has_database_privilege(current_user, current_database(), 'CREATE')
                AS database_create,
            has_table_privilege(current_user,
                'public.sendro_channel_webhook_deliveries', 'INSERT')
                AS can_insert,
            has_table_privilege(current_user,
                'public.sendro_channel_webhook_deliveries', 'UPDATE')
                AS can_update,
            has_table_privilege(current_user,
                'public.sendro_channel_webhook_deliveries', 'DELETE')
                AS can_delete,
            has_table_privilege(current_user,
                'public.sendro_channel_webhook_deliveries', 'TRUNCATE')
                AS can_truncate,
            has_column_privilege(current_user,
                'public.sendro_channel_webhook_deliveries', 'provider', 'SELECT')
                AS read_provider,
            has_column_privilege(current_user,
                'public.sendro_channel_webhook_deliveries', 'processing_state', 'SELECT')
                AS read_state,
            has_column_privilege(current_user,
                'public.sendro_channel_webhook_deliveries', 'next_attempt_at', 'SELECT')
                AS read_next,
            has_column_privilege(current_user,
                'public.sendro_channel_webhook_deliveries', 'received_at', 'SELECT')
                AS read_received,
            has_column_privilege(current_user,
                'public.sendro_channel_webhook_deliveries', 'payload_ciphertext', 'SELECT')
                AS read_payload,
            has_column_privilege(current_user,
                'public.sendro_channel_webhook_deliveries', 'raw_body_sha256', 'SELECT')
                AS read_digest,
            has_column_privilege(current_user,
                'public.sendro_channel_webhook_deliveries', 'id', 'SELECT')
                AS read_id,
            has_column_privilege(current_user,
                'public.sendro_channel_webhook_deliveries', 'last_error_code', 'SELECT')
                AS read_error
    """)).mappings().one()
    if (
        any(permissions[name] for name in (
            "schema_create", "database_create",
            "can_insert", "can_update", "can_delete", "can_truncate",
            "read_payload", "read_digest", "read_id", "read_error",
        ))
        or not all(permissions[name] is True for name in (
            "read_provider", "read_state", "read_next", "read_received",
        ))
    ):
        raise ReadonlyObserverDenied("Observer column privileges unsafe")


def observe_instagram_queue_read_only(
    engine, *, environ=None, now=None, backlog_threshold=50, stale_minutes=15,
):
    """One genuine PostgreSQL SELECT after explicit, constrained role proof.

    This does NOT write a heartbeat or deliver an alert, and no endpoint or
    cron runs it. Return only fixed aggregate state counts and alert codes.
    Missing/unsafe permissions fail rather than silently using app credentials.
    """
    _guard(engine, environ)
    if (
        type(backlog_threshold) is not int or not 1 <= backlog_threshold <= 10000
        or type(stale_minutes) is not int or not 1 <= stale_minutes <= 1440
    ):
        raise ReadonlyObserverDenied("Invalid observer thresholds")
    current = _utc_now(now)
    try:
        with engine.connect() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            db.execute(text("SET LOCAL statement_timeout = '2500ms'"))
            db.execute(text("SET LOCAL lock_timeout = '500ms'"))
            _prove_restricted_role(db)
            row = db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE processing_state = 'pending') AS pending,
                    COUNT(*) FILTER (WHERE processing_state = 'processing') AS processing,
                    COUNT(*) FILTER (WHERE processing_state = 'processed') AS processed,
                    COUNT(*) FILTER (WHERE processing_state = 'quarantined') AS quarantined,
                    COUNT(*) FILTER (WHERE processing_state = 'failed') AS failed,
                    COUNT(*) FILTER (
                        WHERE processing_state = 'pending'
                          AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
                    ) AS due,
                    COUNT(*) FILTER (
                        WHERE processing_state = 'pending'
                          AND next_attempt_at > :now
                    ) AS deferred,
                    MIN(received_at) FILTER (
                        WHERE processing_state = 'pending'
                          AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
                    ) AS oldest_due
                FROM public.sendro_channel_webhook_deliveries
                WHERE provider = 'instagram'
            """), {"now": current}).mappings().one()
            # Connection close rolls back the READ ONLY transaction.
    except ReadonlyObserverDenied:
        raise
    except Exception:
        raise ReadonlyObserverUnavailable(
            "Instagram observer read-only snapshot unavailable"
        ) from None

    totals = {name: int(row[name]) for name in (
        "pending", "processing", "processed", "quarantined", "failed",
    )}
    due, deferred = int(row["due"]), int(row["deferred"])
    oldest = row["oldest_due"]
    if oldest is not None and oldest.tzinfo is None:
        raise ReadonlyObserverUnavailable("Instagram observer timestamp invalid")
    old_age = max(0, (current - oldest).total_seconds()) if oldest else None
    alerts = []
    if totals["failed"]:
        alerts.append("failed_deliveries")
    if totals["quarantined"]:
        alerts.append("quarantined_deliveries")
    if totals["processing"]:
        alerts.append("unresolved_processing_delivery")
    if due >= backlog_threshold:
        alerts.append("pending_backlog")
    if old_age is not None and old_age >= stale_minutes * 60:
        alerts.append("stale_pending_delivery")
    return {
        "mode": "dedicated_postgres_readonly_aggregate",
        "states": totals, "due": due, "deferred": deferred,
        "alert_codes": tuple(alerts),
        "operator_notification": "not_configured",
        "heartbeat_persistence": "not_configured",
        "live_pilot_authorized": False,
        "database_writes": "none",
        "meta_access": "none",
    }
