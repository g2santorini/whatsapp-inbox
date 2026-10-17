"""GDPR request API FACTORY ONLY; deliberately not mounted in main.py.

Accept injected authentication and DB dependencies in isolated tests. No live
data, customer IDs, message text, deletion function, or automatic migration.
"""
from collections.abc import Callable
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.orm import Session
from .privacy_erasure_cases import ScopeEvidence
from .privacy_case_store import (
    create_request, get_request, list_requests, update_request, CaseConflict,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Intake(_Strict):
    tenant_id: int = Field(gt=0)
    channel: Literal["whatsapp", "instagram"]


class Attestation(_Strict):
    externally_confirmed: StrictBool


class Scope(_Strict):
    controller_authority_confirmed: StrictBool = False
    identity_authority_verified: StrictBool = False
    tenant_scope_checked: StrictBool = False
    whatsapp_records_checked: StrictBool = False
    instagram_records_checked: StrictBool = False
    template_batches_checked: StrictBool = False
    unlinked_batch_items_checked: StrictBool = False
    media_checked: StrictBool = False
    provider_copies_checked: StrictBool = False
    application_logs_checked: StrictBool = False
    backup_restore_plan_checked: StrictBool = False
    retention_exceptions_checked: StrictBool = False
    legal_hold: StrictBool | None = None


class Summary(BaseModel):
    case_ref: str
    channel: str
    status: str
    blockers: list[str]
    response_recorded: bool
    audit_events: int
    mode: str
    identity_verified_by_system: bool
    erasure_enabled: bool
    erasure_performed: bool
    safe_to_delete_count: int


def _handle(fn, **kwargs):
    try:
        return fn(**kwargs)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Privacy access denied")
    except LookupError:
        raise HTTPException(status_code=404, detail="Request not found")
    except CaseConflict:
        raise HTTPException(status_code=409, detail="Request state conflict")
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Invalid request transition")


def create_privacy_case_router(
    get_current_active_user: Callable, get_case_db: Callable
) -> APIRouter:
    router = APIRouter(prefix="/privacy/requests", tags=["Privacy — gated"])

    @router.post("", response_model=Summary, status_code=201)
    def intake(payload: Intake, db: Session = Depends(get_case_db),
               user=Depends(get_current_active_user)):
        return _handle(create_request, db=db, tenant_id=payload.tenant_id,
                       user_id=user.id, channel=payload.channel)

    @router.get("", response_model=list[Summary])
    def index(tenant_id: int = Query(gt=0), limit: int = Query(default=50, ge=1, le=100),
              offset: int = Query(default=0, ge=0),
              db: Session = Depends(get_case_db),
              user=Depends(get_current_active_user)):
        return _handle(list_requests, db=db, tenant_id=tenant_id,
                       user_id=user.id, limit=limit, offset=offset)

    @router.get("/{ref}", response_model=Summary)
    def detail(ref: str = Path(min_length=36, max_length=36),
               tenant_id: int = Query(gt=0), db: Session = Depends(get_case_db),
               user=Depends(get_current_active_user)):
        return _handle(get_request, db=db, tenant_id=tenant_id, user_id=user.id,
                       ref=ref)

    @router.post("/{ref}/identity-check", response_model=Summary)
    def identity(payload: Attestation, ref: str = Path(min_length=36, max_length=36),
                 tenant_id: int = Query(gt=0), db: Session = Depends(get_case_db),
                 user=Depends(get_current_active_user)):
        return _handle(update_request, db=db, tenant_id=tenant_id, user_id=user.id,
                       ref=ref, action="identity",
                       attested=payload.externally_confirmed)

    @router.post("/{ref}/scope-review", response_model=Summary)
    def scope(payload: Scope, ref: str = Path(min_length=36, max_length=36),
              tenant_id: int = Query(gt=0), db: Session = Depends(get_case_db),
              user=Depends(get_current_active_user)):
        return _handle(update_request, db=db, tenant_id=tenant_id, user_id=user.id,
                       ref=ref, action="scope",
                       evidence=ScopeEvidence(**payload.model_dump()))

    @router.post("/{ref}/response", response_model=Summary)
    def response(payload: Attestation, ref: str = Path(min_length=36, max_length=36),
                 tenant_id: int = Query(gt=0), db: Session = Depends(get_case_db),
                 user=Depends(get_current_active_user)):
        return _handle(update_request, db=db, tenant_id=tenant_id, user_id=user.id,
                       ref=ref, action="response",
                       attested=payload.externally_confirmed)
    return router
