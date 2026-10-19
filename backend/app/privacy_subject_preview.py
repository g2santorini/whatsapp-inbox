"""Staging-only GDPR subject metadata preview, never deletion or persistence.

This intentionally supports only tenant-native Instagram conversations. Legacy
WhatsApp records have no trusted tenant_id and must not be searched by phone.
Preview selection is ephemeral: it does NOT persist an identity/link to a case.
"""
import os
from collections.abc import Callable, Mapping
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from .privacy_case_store import CaseConflict, _actor, _read
from .privacy_preview_guards import PrivacyRequestLimiter
from .privacy_readonly_preview import preview_is_allowed

SUBJECT_FLAG = "SENDRO_PRIVACY_SUBJECT_PREVIEW"
SUBJECT_VALUE = "reviewed-staging-metadata-only"
LIMITER = PrivacyRequestLimiter(max_calls=5, window_seconds=60)


def subject_preview_is_allowed(settings: Mapping[str, str]) -> bool:
    """Independent fail-closed gate, on top of all existing GDPR approvals."""
    return (
        preview_is_allowed(settings)
        and settings.get("SENDRO_PRIVACY_MANUAL_WORKFLOW") == "reviewed-staging-manual-only"
        and settings.get("SENDRO_PRIVACY_EMAIL_SCHEMA_READY") == "verified-email-channel-check"
        and settings.get(SUBJECT_FLAG) == SUBJECT_VALUE
    )


class SubjectLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: int = Field(gt=0)
    platform: Literal["instagram", "whatsapp"]
    conversation_id: int = Field(gt=0)


class SubjectPreview(BaseModel):
    platform: str
    conversation_id: int
    messages: int
    messages_with_media_metadata: int
    partial_inventory: bool = True
    linked_to_case: bool = False
    erasure_enabled: bool = False
    safe_to_delete_count: int = 0


def inspect_subject(db: Session, *, tenant_id: int, user_id: int,
                    case_ref: str, platform: str, conversation_id: int) -> dict:
    """Tenant-checked bounded metadata counts; no identity fields or writes."""
    try:
        _actor(db, tenant_id, user_id)
        case, _ = _read(db, tenant_id, case_ref)
        if case.status == "received":
            raise HTTPException(status_code=409,
                                detail="Independent identity review required before preview")
        if platform == "whatsapp":
            raise HTTPException(status_code=409,
                detail="Legacy WhatsApp data cannot yet be safely tenant-matched")
        if platform != "instagram":
            raise HTTPException(status_code=422, detail="Unsupported platform")

        # A conversation ID is NOT proof of requester identity. This tenant
        # and channel-account join prevents cross-company record enumeration.
        exists = db.execute(text("""
            SELECT 1
            FROM public.sendro_channel_conversations c
            JOIN public.sendro_channel_accounts a
              ON a.id = c.channel_account_id AND a.tenant_id = c.tenant_id
            WHERE c.tenant_id = :tid AND c.id = :cid
              AND a.platform = 'instagram'
        """), {"tid": tenant_id, "cid": conversation_id}).scalar_one_or_none()
        if exists is None:
            raise LookupError("Conversation not found for this company")

        counts = db.execute(text("""
            SELECT COUNT(*) AS messages,
                   COUNT(CASE WHEN media_json IS NOT NULL THEN 1 END)
                       AS messages_with_media_metadata
            FROM public.sendro_channel_messages
            WHERE tenant_id = :tid AND conversation_id = :cid
        """), {"tid": tenant_id, "cid": conversation_id}).mappings().one()
        return {
            "platform": "instagram",
            "conversation_id": conversation_id,
            "messages": int(counts["messages"]),
            "messages_with_media_metadata": int(counts["messages_with_media_metadata"]),
            "partial_inventory": True,
            "linked_to_case": False,
            "erasure_enabled": False,
            "safe_to_delete_count": 0,
        }
    finally:
        db.rollback()


def create_subject_preview_router(
    get_current_verified_user: Callable, get_case_db: Callable,
) -> APIRouter:
    router = APIRouter(tags=["GDPR subject preview — non-mutating staging"])

    @router.post("/privacy/requests/{ref}/subject-preview", response_model=SubjectPreview)
    def subject_preview(
        payload: SubjectLookup,
        response: Response,
        ref: str = Path(min_length=36, max_length=36),
        db: Session = Depends(get_case_db),
        user=Depends(get_current_verified_user),
    ):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        LIMITER.check(user.id)
        try:
            return inspect_subject(
                db, tenant_id=payload.tenant_id, user_id=user.id,
                case_ref=ref, platform=payload.platform,
                conversation_id=payload.conversation_id,
            )
        except PermissionError:
            raise HTTPException(status_code=403, detail="Privacy access denied")
        except LookupError:
            raise HTTPException(status_code=404, detail="Record not found")
        except CaseConflict:
            raise HTTPException(status_code=409, detail="Request state conflict")
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Invalid subject preview")

    return router


def mount_subject_preview(
    app, get_current_verified_user: Callable, get_case_db: Callable,
    *, settings: Mapping[str, str] | None = None,
) -> bool:
    values = os.environ if settings is None else settings
    if not subject_preview_is_allowed(values):
        return False
    app.include_router(create_subject_preview_router(
        get_current_verified_user, get_case_db,
    ))
    return True
