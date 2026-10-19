"""GDPR case manager offline tests: synthetic UUIDs, no live data/DB."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.app.privacy_erasure_cases import (
    PrivacyActor,
    ScopeEvidence,
    BLOCKER_FIELDS,
    case_preview,
    create_case,
    mark_identity_checked,
    record_response,
    review_scope,
)


REF = "7fbfdd4e-b6ed-4ce4-b4e6-837fd564b998"
NOW = datetime(2026, 10, 16, 13, tzinfo=timezone.utc)
ADMIN = PrivacyActor(tenant_id=101, user_id=5, role="admin")
OWNER = PrivacyActor(tenant_id=101, user_id=6, role="owner")
OTHER_TENANT = PrivacyActor(tenant_id=202, user_id=7, role="admin")


def intake(actor=ADMIN, channel="whatsapp"):
    return create_case(actor=actor, tenant_id=101, case_ref=REF,
                       channel=channel, now=NOW)


def verified():
    return mark_identity_checked(
        case=intake(), actor=ADMIN,
        independently_verified=True, now=NOW + timedelta(minutes=1),
    )


def complete_evidence(**override):
    items = {field: True for field in BLOCKER_FIELDS}
    items["legal_hold"] = False
    items.update(override)
    return ScopeEvidence(**items)


def test_intake_has_opaque_reference_and_no_subject_identity():
    case = intake()
    assert case.status == "received"
    assert case.channel == "whatsapp"
    assert case.events[0].action == "received"
    assert case_preview(case=case, actor=ADMIN) == {
        "case_ref": REF,
        "received_at": NOW.isoformat(),
        "channel": "whatsapp",
        "status": "received",
        "blockers": [],
        "response_recorded": False,
        "audit_events": 1,
        "mode": "offline_review_only",
        "identity_verified_by_system": False,
        "erasure_enabled": False,
        "erasure_performed": False,
        "safe_to_delete_count": 0,
    }
    assert not hasattr(case, "phone")
    assert not hasattr(case, "customer_name")


@pytest.mark.parametrize("bad_ref", [
    "customer@example.com", "+306900000000", "request123", "",
    "00000000-0000-0000-0000-000000000000",
    "00000000-0000-1000-8000-000000000000",
])
def test_rejects_identifying_and_nonrandom_case_references(bad_ref):
    with pytest.raises(ValueError):
        create_case(actor=ADMIN, tenant_id=101, case_ref=bad_ref,
                    channel="whatsapp", now=NOW)


@pytest.mark.parametrize("channel", ["tiktok", "", None])
def test_unknown_channels_cannot_be_invented(channel):
    with pytest.raises(ValueError):
        intake(channel=channel)


@pytest.mark.parametrize("actor", [
    PrivacyActor(101, 7, "operator"),
    PrivacyActor(101, 7, "viewer"),
    PrivacyActor(101, 7, "developer"),
    PrivacyActor(101, 7, "admin", active=False),
    PrivacyActor(101, 0, "admin"),
    PrivacyActor(101, 8, "ADMIN"),
    OTHER_TENANT,
    None,
])
def test_no_unprivileged_or_cross_tenant_intake(actor):
    with pytest.raises(PermissionError):
        intake(actor=actor)


def test_owner_may_view_but_cross_tenant_cannot_inspect():
    case = intake()
    assert case_preview(case=case, actor=OWNER)["status"] == "received"
    with pytest.raises(PermissionError):
        case_preview(case=case, actor=OTHER_TENANT)
    with pytest.raises(PermissionError):
        mark_identity_checked(case=case, actor=OTHER_TENANT,
                              independently_verified=True, now=NOW)


def test_identity_requires_independent_confirmation():
    case = intake()
    with pytest.raises(ValueError, match="independently verified"):
        mark_identity_checked(case=case, actor=ADMIN,
                              independently_verified=False, now=NOW)
    with pytest.raises(ValueError, match="Identity review"):
        review_scope(case=case, actor=ADMIN,
                     evidence=complete_evidence(), now=NOW)
    with pytest.raises(ValueError, match="Identity review"):
        record_response(case=case, actor=ADMIN,
                        response_sent_confirmed=True, now=NOW)


def test_missing_scopes_fail_closed_including_unlinked_batches_and_backups():
    reviewed = review_scope(case=verified(), actor=ADMIN,
                            evidence=ScopeEvidence(),
                            now=NOW + timedelta(minutes=2))
    assert reviewed.status == "needs_evidence"
    assert "unlinked_batch_items_checked" in reviewed.scope_blockers
    assert "backup_restore_plan_checked" in reviewed.scope_blockers
    assert "legal_hold_not_checked" in reviewed.scope_blockers
    assert case_preview(case=reviewed, actor=ADMIN)["safe_to_delete_count"] == 0


@pytest.mark.parametrize("missing", list(BLOCKER_FIELDS))
def test_every_single_missing_verification_blocks_review(missing):
    reviewed = review_scope(
        case=verified(), actor=ADMIN,
        evidence=complete_evidence(**{missing: False}),
        now=NOW + timedelta(minutes=2),
    )
    assert reviewed.status == "needs_evidence"
    assert missing in reviewed.scope_blockers


def test_legal_hold_blocks_even_fully_reviewed_case():
    reviewed = review_scope(case=verified(), actor=ADMIN,
                            evidence=complete_evidence(legal_hold=True),
                            now=NOW + timedelta(minutes=2))
    assert reviewed.status == "on_hold"
    assert reviewed.scope_blockers == ("legal_hold",)


def test_manual_decision_not_a_deletion_approval():
    case = review_scope(case=verified(), actor=OWNER,
                        evidence=complete_evidence(),
                        now=NOW + timedelta(minutes=2))
    assert case.status == "ready_for_manual_decision"
    assert case.scope_blockers == ()
    preview = case_preview(case=case, actor=ADMIN)
    assert preview["erasure_performed"] is False
    assert preview["erasure_enabled"] is False
    assert preview["safe_to_delete_count"] == 0
    assert [ev.action for ev in case.events] == [
        "received", "identity_checked", "scope_reviewed",
    ]


def test_scope_can_be_rechecked_without_mutating_prior_snapshot():
    first = review_scope(case=verified(), actor=ADMIN,
                         evidence=ScopeEvidence(),
                         now=NOW + timedelta(minutes=2))
    second = review_scope(case=first, actor=ADMIN,
                          evidence=complete_evidence(),
                          now=NOW + timedelta(minutes=3))
    assert first.status == "needs_evidence"
    assert second.status == "ready_for_manual_decision"
    assert len(first.events) == 3
    assert len(second.events) == 4


def test_response_is_external_confirmation_not_erasure_or_closure():
    checked = verified()
    with pytest.raises(ValueError, match="actual external response"):
        record_response(case=checked, actor=ADMIN,
                        response_sent_confirmed=False, now=NOW + timedelta(minutes=2))
    responded = record_response(case=checked, actor=ADMIN,
                                response_sent_confirmed=True,
                                now=NOW + timedelta(minutes=2))
    assert responded.response_recorded
    assert responded.status == "identity_checked"
    assert responded.events[-1].action == "response_recorded"
    assert not case_preview(case=responded, actor=ADMIN)["erasure_performed"]
    with pytest.raises(ValueError, match="already"):
        record_response(case=responded, actor=ADMIN,
                        response_sent_confirmed=True, now=NOW + timedelta(minutes=3))


def test_rejects_backdated_audit_and_naive_timestamps():
    case = intake()
    with pytest.raises(ValueError, match="precedes request"):
        mark_identity_checked(case=case, actor=ADMIN, independently_verified=True,
                              now=NOW - timedelta(minutes=1))
    with pytest.raises(ValueError, match="timezone-aware"):
        mark_identity_checked(case=case, actor=ADMIN, independently_verified=True,
                              now=datetime(2026, 10, 16, 13))
    with pytest.raises(ValueError, match="timezone-aware"):
        create_case(actor=ADMIN, tenant_id=101, case_ref=REF, channel="instagram",
                    now=datetime(2026, 10, 16, 13))


def test_invalid_evidence_and_cross_tenant_review_rejected():
    case = verified()
    with pytest.raises(TypeError):
        review_scope(case=case, actor=ADMIN, evidence={},
                     now=NOW + timedelta(minutes=2))
    with pytest.raises(PermissionError):
        review_scope(case=case, actor=OTHER_TENANT,
                     evidence=complete_evidence(),
                     now=NOW + timedelta(minutes=2))
    with pytest.raises(PermissionError):
        record_response(case=case, actor=OTHER_TENANT,
                        response_sent_confirmed=True,
                        now=NOW + timedelta(minutes=2))


def test_offline_engine_contains_no_storage_or_delete_entrypoint():
    source = (Path(__file__).parents[1] / "app" /
              "privacy_erasure_cases.py").read_text(encoding="utf-8")
    for prohibited in (
        "create_engine(", "SessionLocal", "get_db(", "DELETE FROM",
        "db.execute(", "db.commit(", "requests.", "httpx.",
        "FastAPI(", "@app.", "router.", "DATABASE_URL", "subprocess.",
        "os.environ", "schedule.", "apscheduler", "celery",
    ):
        assert prohibited not in source


def test_email_channel_is_accepted_as_nonidentifying_intake():
    case = intake(channel="email")
    assert case.channel == "email"
    assert case.status == "received"
