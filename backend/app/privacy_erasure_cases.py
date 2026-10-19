"""Inert GDPR deletion-request case management for synthetic/offline reviews.

NO live data, database/session, API route, storage, scheduler or erasure operation.
This does not confirm requester identity or a lawful deletion entitlement.
Cases carry an opaque random reference and structured, non-PII audit events;
identifying information must stay in a separate future access-controlled system.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID


AUTHORIZED_ROLES = frozenset({"admin", "owner"})
SUPPORTED_CHANNELS = frozenset({"whatsapp", "instagram", "email"})
BLOCKER_FIELDS = (
    "controller_authority_confirmed",
    "identity_authority_verified",
    "tenant_scope_checked",
    "whatsapp_records_checked",
    "instagram_records_checked",
    "template_batches_checked",
    "unlinked_batch_items_checked",
    "media_checked",
    "provider_copies_checked",
    "application_logs_checked",
    "backup_restore_plan_checked",
    "retention_exceptions_checked",
)


@dataclass(frozen=True)
class PrivacyActor:
    tenant_id: int
    user_id: int
    role: str
    active: bool = True


@dataclass(frozen=True)
class ScopeEvidence:
    """Independent verified inputs; all default to unverified (fail closed).

    The reviewer must verify each flag outside this module. A True value here
    is NOT proof; future integration must attach independently authenticated
    evidence and documented controller instructions.
    """
    controller_authority_confirmed: bool = False
    identity_authority_verified: bool = False
    tenant_scope_checked: bool = False
    whatsapp_records_checked: bool = False
    instagram_records_checked: bool = False
    template_batches_checked: bool = False
    unlinked_batch_items_checked: bool = False
    media_checked: bool = False
    provider_copies_checked: bool = False
    application_logs_checked: bool = False
    backup_restore_plan_checked: bool = False
    retention_exceptions_checked: bool = False
    legal_hold: bool | None = None


@dataclass(frozen=True)
class PrivacyAuditEvent:
    action: str
    actor_user_id: int
    recorded_at: datetime


@dataclass(frozen=True)
class PrivacyCase:
    case_ref: str
    tenant_id: int
    channel: str
    received_at: datetime
    status: str = "received"
    scope_blockers: tuple[str, ...] = ()
    response_recorded: bool = False
    events: tuple[PrivacyAuditEvent, ...] = ()


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("An explicit timezone-aware timestamp is required")
    return value.astimezone(timezone.utc)


def _authorized(actor: PrivacyActor, tenant_id: int) -> None:
    if not isinstance(actor, PrivacyActor) or not (
        type(actor.tenant_id) is int and actor.tenant_id > 0
        and type(actor.user_id) is int and actor.user_id > 0
        and actor.active is True
        and actor.role in AUTHORIZED_ROLES
        and type(tenant_id) is int and tenant_id > 0
        and actor.tenant_id == tenant_id
    ):
        raise PermissionError("Authorized same-tenant administrator required")


def _append(case: PrivacyCase, actor: PrivacyActor,
            action: str, now: datetime) -> tuple[PrivacyAuditEvent, ...]:
    timestamp = _utc(now)
    if timestamp < _utc(case.received_at):
        raise ValueError("Event precedes request")
    if case.events and timestamp < case.events[-1].recorded_at:
        raise ValueError("Audit events must be chronological")
    return case.events + (PrivacyAuditEvent(action, actor.user_id, timestamp),)


def create_case(*, actor: PrivacyActor, tenant_id: int,
                case_ref: str, channel: str, now: datetime) -> PrivacyCase:
    """Intake with only a random UUIDv4; never store a customer ID here."""
    _authorized(actor, tenant_id)
    try:
        uuid = UUID(case_ref)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("An opaque UUIDv4 case reference is required") from exc
    if uuid.version != 4 or str(uuid) != case_ref:
        raise ValueError("Only canonical random UUIDv4 case references are allowed")
    if channel not in SUPPORTED_CHANNELS:
        raise ValueError("Unsupported messaging channel")
    timestamp = _utc(now)
    event = PrivacyAuditEvent("received", actor.user_id, timestamp)
    return PrivacyCase(case_ref, tenant_id, channel, timestamp, events=(event,))


def mark_identity_checked(*, case: PrivacyCase, actor: PrivacyActor,
                          independently_verified: bool, now: datetime) -> PrivacyCase:
    _authorized(actor, case.tenant_id)
    if case.status != "received":
        raise ValueError("Identity check is not valid in this case state")
    if independently_verified is not True:
        raise ValueError("Identity must be independently verified first")
    return replace(case, status="identity_checked",
                   events=_append(case, actor, "identity_checked", now))


def review_scope(*, case: PrivacyCase, actor: PrivacyActor,
                 evidence: ScopeEvidence, now: datetime) -> PrivacyCase:
    """Record blockers and evidence review. Never approve/execute erasure."""
    _authorized(actor, case.tenant_id)
    if case.status not in {
        "identity_checked", "needs_evidence", "on_hold",
        "ready_for_manual_decision",
    }:
        raise ValueError("Identity review must precede scope assessment")
    if not isinstance(evidence, ScopeEvidence):
        raise TypeError("Explicit structured evidence required")
    blockers = [
        field for field in BLOCKER_FIELDS
        if getattr(evidence, field) is not True
    ]
    if evidence.legal_hold is None:
        blockers.append("legal_hold_not_checked")
    elif evidence.legal_hold is True:
        blockers.append("legal_hold")
    elif evidence.legal_hold is not False:
        blockers.append("invalid_legal_hold")
    new_status = (
        "on_hold" if "legal_hold" in blockers
        else "needs_evidence" if blockers
        else "ready_for_manual_decision"
    )
    return replace(case, status=new_status, scope_blockers=tuple(blockers),
                   events=_append(case, actor, "scope_reviewed", now))


def record_response(*, case: PrivacyCase, actor: PrivacyActor,
                    response_sent_confirmed: bool, now: datetime) -> PrivacyCase:
    """Log an externally confirmed reply; not data erasure or case closure."""
    _authorized(actor, case.tenant_id)
    if case.status == "received":
        raise ValueError("Identity review must happen first")
    if case.response_recorded:
        raise ValueError("Response has already been recorded")
    if response_sent_confirmed is not True:
        raise ValueError("An actual external response must be confirmed")
    return replace(case, response_recorded=True,
                   events=_append(case, actor, "response_recorded", now))


def case_preview(*, case: PrivacyCase, actor: PrivacyActor) -> dict:
    """Internal non-identifying review summary; cannot trigger deletion."""
    _authorized(actor, case.tenant_id)
    return {
        "case_ref": case.case_ref,
        "received_at": case.received_at.isoformat(),
        "channel": case.channel,
        "status": case.status,
        "blockers": list(case.scope_blockers),
        "response_recorded": case.response_recorded,
        "audit_events": len(case.events),
        "mode": "offline_review_only",
        "identity_verified_by_system": False,
        "erasure_enabled": False,
        "erasure_performed": False,
        "safe_to_delete_count": 0,
    }
