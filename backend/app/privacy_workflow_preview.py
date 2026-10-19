"""Staging-only manual GDPR case workflow, separate from read-only preview.

NO customer lookup, identity data, deletion, retention purge, outbound reply,
or automatic webhook/email intake. The tenant admin records independent steps.
Enabling this on shared staging/production PostgreSQL requires separate
explicit approval and channel-schema verification; fail closed by default.
"""
import os
from collections.abc import Callable, Mapping

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy.orm import Session
from .privacy_case_api import Intake, Attestation, Scope, Summary, _handle
from .privacy_case_store import create_request, update_request, list_review_tenants
from .privacy_erasure_cases import ScopeEvidence
from .privacy_preview_guards import PrivacyRequestLimiter
from .privacy_readonly_preview import preview_is_allowed
from .privacy_subject_preview import subject_preview_is_allowed

WORKFLOW_FLAG = "SENDRO_PRIVACY_MANUAL_WORKFLOW"
WORKFLOW_VALUE = "reviewed-staging-manual-only"
SCHEMA_FLAG = "SENDRO_PRIVACY_EMAIL_SCHEMA_READY"
SCHEMA_VALUE = "verified-email-channel-check"
limiter = PrivacyRequestLimiter(max_calls=10, window_seconds=60)


def workflow_is_allowed(settings: Mapping[str, str]) -> bool:
    """Extra opt-in on top of three read-only/staging service checks."""
    return (
        preview_is_allowed(settings)
        and settings.get(WORKFLOW_FLAG) == WORKFLOW_VALUE
        and settings.get(SCHEMA_FLAG) == SCHEMA_VALUE
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"


def create_privacy_workflow_router(
    get_current_verified_user: Callable,
    get_case_db: Callable,
) -> APIRouter:
    router = APIRouter(tags=["Privacy manual workflow — staging only"])

    @router.get("/privacy/workflow")
    def workflow_status(
        response: Response,
        db: Session = Depends(get_case_db),
        user=Depends(get_current_verified_user),
    ):
        _no_store(response)
        limiter.check(user.id)
        tenants = _handle(list_review_tenants, db=db, user_id=user.id)
        if not tenants:
            raise HTTPException(status_code=403, detail="Privacy access denied")
        return {"manual_workflow_enabled": True, "erasure_enabled": False,
                "subject_preview_enabled": subject_preview_is_allowed(os.environ)}

    @router.post("/privacy/requests", response_model=Summary, status_code=201)
    def intake(
        payload: Intake,
        response: Response,
        db: Session = Depends(get_case_db),
        user=Depends(get_current_verified_user),
    ):
        _no_store(response)
        limiter.check(user.id)
        return _handle(create_request, db=db, tenant_id=payload.tenant_id,
                       user_id=user.id, channel=payload.channel)

    @router.post("/privacy/requests/{ref}/identity-check", response_model=Summary)
    def identity(
        payload: Attestation,
        response: Response,
        ref: str = Path(min_length=36, max_length=36),
        tenant_id: int = Query(gt=0),
        db: Session = Depends(get_case_db),
        user=Depends(get_current_verified_user),
    ):
        _no_store(response)
        limiter.check(user.id)
        return _handle(update_request, db=db, tenant_id=tenant_id,
                       user_id=user.id, ref=ref, action="identity",
                       attested=payload.externally_confirmed)

    @router.post("/privacy/requests/{ref}/scope-review", response_model=Summary)
    def scope(
        payload: Scope,
        response: Response,
        ref: str = Path(min_length=36, max_length=36),
        tenant_id: int = Query(gt=0),
        db: Session = Depends(get_case_db),
        user=Depends(get_current_verified_user),
    ):
        _no_store(response)
        limiter.check(user.id)
        return _handle(update_request, db=db, tenant_id=tenant_id,
                       user_id=user.id, ref=ref, action="scope",
                       evidence=ScopeEvidence(**payload.model_dump()))

    @router.post("/privacy/requests/{ref}/response", response_model=Summary)
    def record_reply(
        payload: Attestation,
        response: Response,
        ref: str = Path(min_length=36, max_length=36),
        tenant_id: int = Query(gt=0),
        db: Session = Depends(get_case_db),
        user=Depends(get_current_verified_user),
    ):
        _no_store(response)
        limiter.check(user.id)
        return _handle(update_request, db=db, tenant_id=tenant_id,
                       user_id=user.id, ref=ref, action="response",
                       attested=payload.externally_confirmed)

    return router


def mount_privacy_workflow_preview(
    app, get_current_verified_user: Callable, get_case_db: Callable,
    *, settings: Mapping[str, str] | None = None,
) -> bool:
    values = os.environ if settings is None else settings
    if not workflow_is_allowed(values):
        return False
    app.include_router(create_privacy_workflow_router(
        get_current_verified_user, get_case_db,
    ))
    return True
