"""GDPR request storage: tenant-scoped, non-identifying and not wired to main.py.

No DB/schema creation, no message/subject lookup, no erasure operation.
Only a separately provisioned database and explicitly injected session can use it.
"""
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from .privacy_erasure_cases import (
    PrivacyActor, PrivacyAuditEvent, PrivacyCase, ScopeEvidence,
    create_case, mark_identity_checked, review_scope, record_response, case_preview,
)


class CaseConflict(Exception):
    pass


def _date(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Missing timezone-aware audit timestamp")
    return value.astimezone(timezone.utc)


def _actor(db, tenant_id, user_id):
    if type(tenant_id) is not int or tenant_id < 1 or type(user_id) is not int or user_id < 1:
        raise PermissionError("Denied")
    # Membership and disabled state are from trusted DB, NEVER from request body.
    role = db.execute(text("""
        SELECT tu.member_role
        FROM public.sendro_tenant_users tu
        INNER JOIN public.users u ON u.id = tu.user_id
        WHERE tu.tenant_id=:tid AND tu.user_id=:uid
          AND tu.is_active=TRUE AND u.disabled=FALSE
          AND tu.member_role IN ('admin','owner')
    """), {"tid": tenant_id, "uid": user_id}).scalar_one_or_none()
    if role is None:
        raise PermissionError("Denied")
    return PrivacyActor(tenant_id, user_id, role)


def _read(db, tenant_id, ref):
    row = db.execute(text("""
        SELECT case_ref, tenant_id, channel, status, scope_blockers,
               response_recorded, received_at, version
        FROM public.sendro_privacy_cases
        WHERE tenant_id=:tid AND case_ref=:ref
    """), {"tid": tenant_id, "ref": ref}).mappings().first()
    if row is None:
        raise LookupError("Case not found")
    events = db.execute(text("""
        SELECT actor_user_id, action, recorded_at
        FROM public.sendro_privacy_case_events
        WHERE tenant_id=:tid AND case_ref=:ref ORDER BY seq
    """), {"tid": tenant_id, "ref": ref}).mappings().all()
    blockers = json.loads(row["scope_blockers"])
    if not isinstance(blockers, list) or not all(isinstance(x, str) for x in blockers):
        raise CaseConflict("Invalid audit state")
    case = PrivacyCase(
        case_ref=row["case_ref"], tenant_id=int(row["tenant_id"]),
        channel=row["channel"], received_at=_date(row["received_at"]),
        status=row["status"], scope_blockers=tuple(blockers),
        response_recorded=bool(row["response_recorded"]),
        events=tuple(PrivacyAuditEvent(
            item["action"], int(item["actor_user_id"]), _date(item["recorded_at"])
        ) for item in events),
    )
    version = int(row["version"])
    if version != len(case.events):
        raise CaseConflict("Audit history mismatch")
    return case, version


def create_request(db, *, tenant_id, user_id, channel):
    try:
        actor = _actor(db, tenant_id, user_id)
        case = create_case(
            actor=actor, tenant_id=tenant_id, case_ref=str(uuid4()),
            channel=channel, now=datetime.now(timezone.utc),
        )
        db.execute(text("""
            INSERT INTO public.sendro_privacy_cases
                (case_ref, tenant_id, channel, status, scope_blockers,
                 response_recorded, version, received_at, updated_at)
            VALUES (:ref, :tid, :channel, 'received', '[]', FALSE, 1, :when, :when)
        """), {"ref": case.case_ref, "tid": tenant_id, "channel": channel,
               "when": case.received_at})
        db.execute(text("""
            INSERT INTO public.sendro_privacy_case_events
                (case_ref, tenant_id, seq, actor_user_id, action, recorded_at)
            VALUES (:ref, :tid, 1, :uid, 'received', :when)
        """), {"ref": case.case_ref, "tid": tenant_id, "uid": user_id,
               "when": case.received_at})
        db.commit()
        return case_preview(case=case, actor=actor)
    except Exception:
        db.rollback()
        raise


def get_request(db, *, tenant_id, user_id, ref):
    try:
        actor = _actor(db, tenant_id, user_id)
        case, _ = _read(db, tenant_id, ref)
        return case_preview(case=case, actor=actor)
    finally:
        db.rollback()


def list_requests(db, *, tenant_id, user_id, limit=50, offset=0):
    try:
        actor = _actor(db, tenant_id, user_id)
        refs = db.execute(text("""
            SELECT case_ref FROM public.sendro_privacy_cases
            WHERE tenant_id=:tid
            ORDER BY received_at DESC, case_ref DESC LIMIT :limit OFFSET :offset
        """), {"tid": tenant_id, "limit": max(1, min(100, limit)),
               "offset": max(0, offset)}).scalars().all()
        return [case_preview(case=_read(db, tenant_id, ref)[0], actor=actor)
                for ref in refs]
    finally:
        db.rollback()


def update_request(db, *, tenant_id, user_id, ref, action,
                   attested=False, evidence=None):
    """Only manual review/attestation state changes. NO erase/approve action."""
    try:
        actor = _actor(db, tenant_id, user_id)
        old, version = _read(db, tenant_id, ref)
        now = datetime.now(timezone.utc)
        if action == "identity":
            updated = mark_identity_checked(
                case=old, actor=actor, independently_verified=attested, now=now)
        elif action == "scope":
            if not isinstance(evidence, ScopeEvidence):
                raise ValueError("Structured evidence required")
            updated = review_scope(case=old, actor=actor, evidence=evidence, now=now)
        elif action == "response":
            updated = record_response(
                case=old, actor=actor, response_sent_confirmed=attested, now=now)
        else:
            raise ValueError("Unsupported action")
        if updated.events[:-1] != old.events or len(updated.events) != version+1:
            raise CaseConflict("Audit event mismatch")
        result = db.execute(text("""
            UPDATE public.sendro_privacy_cases
            SET status=:status, scope_blockers=:blockers,
                response_recorded=:responded, updated_at=:when,
                version=:new_version
            WHERE tenant_id=:tid AND case_ref=:ref AND version=:version
        """), {
            "status": updated.status,
            "blockers": json.dumps(list(updated.scope_blockers)),
            "responded": updated.response_recorded,
            "when": now, "new_version": version+1,
            "tid": tenant_id, "ref": ref, "version": version,
        })
        if result.rowcount != 1:
            raise CaseConflict("Concurrent update")
        event = updated.events[-1]
        db.execute(text("""
            INSERT INTO public.sendro_privacy_case_events
                (case_ref, tenant_id, seq, actor_user_id, action, recorded_at)
            VALUES (:ref, :tid, :seq, :uid, :action, :when)
        """), {"ref": ref, "tid": tenant_id, "seq": version+1,
               "uid": user_id, "action": event.action,
               "when": event.recorded_at})
        db.commit()
        return case_preview(case=updated, actor=actor)
    except Exception:
        db.rollback()
        raise


def list_review_tenants(db, *, user_id):
    """List only tenants with an active owner/admin membership for this user.

    Do not reuse Instagram tenant discovery; those memberships have
    different privacy roles and depend on Instagram account configuration.
    """
    if type(user_id) is not int or user_id < 1:
        raise PermissionError("Denied")
    try:
        rows = db.execute(text("""
            SELECT t.id, t.display_name
            FROM public.sendro_tenant_users tu
            INNER JOIN public.sendro_tenants t ON t.id = tu.tenant_id
            INNER JOIN public.users u ON u.id = tu.user_id
            WHERE tu.user_id = :uid AND tu.is_active = TRUE
              AND u.disabled = FALSE
              AND tu.member_role IN ('owner', 'admin')
            ORDER BY t.display_name, t.id
        """), {"uid": user_id}).mappings().all()
        return [dict(row) for row in rows]
    finally:
        db.rollback()
