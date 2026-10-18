"""Opt-in, read-only GDPR request preview for Sendro staging.

Fail closed: disabled by default. No route on production, no write route,
no schema change, no deletion and no automatic case creation. Staging
shares the live database, so enabling this requires a separate review.
"""
import os
from collections.abc import Callable, Mapping

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .privacy_case_store import CaseConflict, get_request, list_requests

class PrivacyPreviewOut(BaseModel):
    """Safe, non-identifying contract. Independent of the mutating case API."""
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


STAGING_RENDER_SERVICE_ID = "srv-d806bq0sfn5c7399akng"
FLAG_NAME = "SENDRO_PRIVACY_READONLY_PREVIEW"
APPROVAL_NAME = "SENDRO_PRIVACY_READONLY_REVIEWED"
APPROVAL_VALUE = "reviewed-read-only-tenant-auth"


def preview_is_allowed(settings: Mapping[str, str]) -> bool:
    """All required conditions must hold. No production route, even on misconfig."""
    return (
        settings.get(FLAG_NAME) == "enabled"
        and settings.get(APPROVAL_NAME) == APPROVAL_VALUE
        and settings.get("RENDER_SERVICE_ID") == STAGING_RENDER_SERVICE_ID
    )


def _read_safe(fn, **params):
    try:
        return fn(**params)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Privacy access denied")
    except LookupError:
        raise HTTPException(status_code=404, detail="Request not found")
    except CaseConflict:
        raise HTTPException(status_code=409, detail="Request state conflict")
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid request")


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"


def _require_mfa(user) -> None:
    """All privacy reviewers must have MFA enabled, regardless of tenant role."""
    if not getattr(user, "mfa_enabled", False):
        raise HTTPException(
            status_code=403, detail="Authenticator required for privacy access",
        )


def create_privacy_readonly_router(
    get_current_active_user: Callable,
    get_case_db: Callable,
) -> APIRouter:
    """Only GET handlers; never import or register the mutating case API."""
    router = APIRouter(prefix="/privacy/requests", tags=["Privacy read-only preview"])

    @router.get("", response_model=list[PrivacyPreviewOut])
    def index(
        response: Response,
        tenant_id: int = Query(gt=0),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        db: Session = Depends(get_case_db),
        user=Depends(get_current_active_user),
    ):
        _no_store(response)
        _require_mfa(user)
        return _read_safe(
            list_requests, db=db, tenant_id=tenant_id,
            user_id=user.id, limit=limit, offset=offset,
        )

    @router.get("/{ref}", response_model=PrivacyPreviewOut)
    def detail(
        response: Response,
        ref: str = Path(min_length=36, max_length=36),
        tenant_id: int = Query(gt=0),
        db: Session = Depends(get_case_db),
        user=Depends(get_current_active_user),
    ):
        _no_store(response)
        _require_mfa(user)
        return _read_safe(
            get_request, db=db, tenant_id=tenant_id,
            user_id=user.id, ref=ref,
        )

    return router


def mount_privacy_readonly_preview(
    app, get_current_active_user: Callable, get_case_db: Callable,
    *, settings: Mapping[str, str] | None = None,
) -> bool:
    """Fail closed without breaking Sendro startup on a bad env setting."""
    values = os.environ if settings is None else settings
    if not preview_is_allowed(values):
        return False
    app.include_router(create_privacy_readonly_router(
        get_current_active_user, get_case_db,
    ))
    return True
