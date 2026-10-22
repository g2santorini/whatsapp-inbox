"""Pure, redacted Instagram attended-pilot evidence preflight (NO rollout).

This is a safety review tool, not an authorization, service, or live Meta
check. Never queries PostgreSQL, Render, Meta or a real account; never
changes flags, secrets, data or permissions. A filled checklist alone
CANNOT grant permission for any live pilot.
"""
from datetime import datetime, timedelta, timezone
import json
import os

from .instagram_live_readiness import inspect_instagram_live_readiness


# Operator-provided evidence MUST come from the named source. No evidence
# is independently fetched or trusted solely because an input says "true".
# The freshness interval is an upper bound for *review consideration* only.
EVIDENCE_REQUIREMENTS = {
    "staging_effective_flags_reviewed": ("render_readonly", 24),
    "production_effective_flags_reviewed": ("render_readonly", 24),
    "meta_subscription_confirmed_off": ("meta_dashboard", 24),
    "meta_app_test_account_permissions_reviewed": ("meta_dashboard", 48),
    "single_business_tenant_mapping_reviewed": ("security_review", 24),
    "shared_database_backup_restore_verified": ("restore_test", 72),
    "shared_database_privilege_boundary_approved": ("security_review", 168),
    "supervised_worker_stop_rehearsed": ("operator_rehearsal", 48),
    "alert_recipient_receipt_rehearsed": ("operator_rehearsal", 48),
    "authenticated_responder_and_mfa_reviewed": ("security_review", 48),
    "exact_single_dm_scope_reviewed": ("operator_rehearsal", 24),
    "incident_quarantine_stop_and_rollback_rehearsed": ("operator_rehearsal", 48),
}
_VALID_FIELDS = frozenset({"verified", "verified_at", "source"})
_MODE = "offline_attended_instagram_pilot_evidence_review"


def _utc_time(value):
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("now must be an aware datetime")
    return value.astimezone(timezone.utc)


def _fresh_supported_evidence(item, *, source, max_age_hours, now):
    if not isinstance(item, dict) or set(item) != _VALID_FIELDS:
        return False
    if item["verified"] is not True or item["source"] != source:
        return False
    when = item["verified_at"]
    if not isinstance(when, str) or len(when) > 40:
        return False
    try:
        parsed = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        return False
    moment = parsed.astimezone(timezone.utc)
    delta = now - moment
    return timedelta(0) <= delta <= timedelta(hours=max_age_hours)


def inspect_instagram_pilot_evidence(environ, evidence=None, *, now=None):
    """Evaluate a caller-provided snapshot with NO I/O, changes or secrets.

    This is NOT independent evidence verification. It never produces an
    executable GO decision: even a perfect form remains HOLD, requiring a
    separately documented owner/operator approval and real source checks.
    """
    current = _utc_time(now)
    standby = inspect_instagram_live_readiness(environ)
    supplied = evidence if isinstance(evidence, dict) else {}
    checklist = {}
    for name, (source, max_age) in EVIDENCE_REQUIREMENTS.items():
        checklist[name] = _fresh_supported_evidence(
            supplied.get(name),
            source=source,
            max_age_hours=max_age,
            now=current,
        )
    unknown_evidence_names = set(supplied) - set(EVIDENCE_REQUIREMENTS)
    unmet = sorted(name for name, passed in checklist.items() if not passed)

    # Only include the fixed names/boolean results of the existing redacted
    # preflight. Never echo raw evidence, timestamps, URLs, tenant/account
    # IDs, Meta tokens, passwords, staff contacts or other free-form data.
    return {
        "mode": _MODE,
        "decision": "HOLD",
        "live_pilot_authorized": False,
        "independently_verified": False,
        "evidence_complete_for_manual_review": (
            not unmet and not unknown_evidence_names
            and standby["secure_standby"]
            and standby["secrets_configured"]
        ),
        "supplied_config_secure_standby": standby["secure_standby"],
        "supplied_config_prepared": standby["secrets_configured"],
        "standby_blockers": standby["unmet_checks"],
        "evidence_checks": checklist,
        "unmet_evidence": unmet,
        "unrecognized_evidence_present": bool(unknown_evidence_names),
        "next_action": "independent_owner_review_required",
        "database_writes": "none",
        "meta_changes": "none",
    }


def main():
    """Safe CLI: no evidence-input option, so defaults to HOLD by design."""
    report = inspect_instagram_pilot_evidence(os.environ)
    print(json.dumps(report, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
