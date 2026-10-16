"""Phase 2Q: offline, redacted Instagram live-readiness configuration preflight.

This module NEVER connects to PostgreSQL, Render, Meta, the WhatsApp backend,
or any network; it cannot enable features or alter configuration. It is not
imported by FastAPI startup, a scheduler, or a worker.

Manual operator invocation (from backend/):
    python -m app.instagram_live_readiness

The result is redacted. It is NOT approval to start a production-shared
database worker or subscribe to Instagram messages in Meta.
"""
import hmac
import json
import os

from cryptography.fernet import Fernet


_OFF_VALUES = frozenset({"", "false", "off", "no", "0"})
# Include dormant supervisor gates: these must NEVER be used to justify
# PostgreSQL execution (the SQLite-only supervisor rejects PostgreSQL).
_DISALLOWED_ENABLED_FLAGS = (
    "INSTAGRAM_WEBHOOK_INGESTION_ENABLED",
    "INSTAGRAM_WORKER_MANUAL_ENABLED",
    "INSTAGRAM_SUPERVISOR_TEST_ENABLED",
    "INSTAGRAM_ISOLATED_DB_APPROVED",
)


def _disabled(value):
    """Unknown, misspelled, or permissive values are NOT treated as OFF."""
    return isinstance(value, str) and value.strip().lower() in _OFF_VALUES


def inspect_instagram_live_readiness(environ):
    """Pure, redacted inspection of an explicitly supplied environment mapping.

    No secrets, tokens, URLs, account IDs or password material are included
    in the result. Missing secret values are reported as boolean statuses.
    This checks *only* the supplied environment, not Render's true config
    until separately run by an authorized operator on the staging backend.
    """
    env = dict(environ)
    checks = {}
    for flag in _DISALLOWED_ENABLED_FLAGS:
        checks[flag + "_off"] = _disabled(env.get(flag, ""))

    checks["instagram_app_secret_present"] = bool(
        str(env.get("INSTAGRAM_APP_SECRET") or "").strip()
    )
    verify_token = env.get("INSTAGRAM_WEBHOOK_VERIFY_TOKEN") or ""
    checks["instagram_verify_token_present"] = bool(
        isinstance(verify_token, str) and verify_token.strip()
    )
    whatsapp_verify_token = env.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN") or ""
    checks["instagram_verify_token_distinct_from_whatsapp"] = not (
        isinstance(verify_token, str)
        and isinstance(whatsapp_verify_token, str)
        and verify_token
        and whatsapp_verify_token
        and hmac.compare_digest(verify_token, whatsapp_verify_token)
    )

    encryption_key = env.get("INSTAGRAM_WEBHOOK_ENCRYPTION_KEY") or ""
    try:
        Fernet(encryption_key.encode("ascii"))
        checks["instagram_fernet_key_valid"] = True
    except (ValueError, TypeError, AttributeError, UnicodeError):
        checks["instagram_fernet_key_valid"] = False

    off_keys = [flag + "_off" for flag in _DISALLOWED_ENABLED_FLAGS]
    secure_standby = all(checks[k] for k in off_keys)
    secret_keys = [
        "instagram_app_secret_present",
        "instagram_verify_token_present",
        "instagram_verify_token_distinct_from_whatsapp",
        "instagram_fernet_key_valid",
    ]
    config_prepared = all(checks[k] for k in secret_keys)
    failures = [k for k, value in checks.items() if not value]
    return {
        "mode": "redacted_offline_configuration_preflight",
        "secure_standby": secure_standby,
        "secrets_configured": config_prepared,
        "pilot_ready": False,
        "meta_webhook_subscription": "not_verified",
        "live_database_writes": "not_performed",
        "checks": checks,
        "unmet_checks": sorted(failures),
    }


def main():
    """No database engine, secret printout, config write or network calls."""
    report = inspect_instagram_live_readiness(os.environ)
    print(json.dumps(report, sort_keys=True))
    # Standby safety is a hard gate. Missing future pilot configuration is
    # actionable but not dangerous while ingress/workers remain disabled.
    return 0 if report["secure_standby"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
