"""Read-only tenant-scoped Instagram Inbox endpoints.

This feature does NOT send Instagram DMs, modify WhatsApp tables, run workers,
subscribe Meta webhooks or expose encrypted webhook payloads and tokens.
Authentication uses the existing Sendro get_current_active_user dependency.
All queries explicitly require membership in the requested tenant.
"""
from datetime import datetime
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import get_db
from .models import User


class InstagramConversationOut(BaseModel):
    id: int
    tenant_id: int
    channel_account_id: int
    external_customer_id: str
    contact_name: str | None
    status: str
    assigned_to_user_id: int | None
    unread_count: int
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime
    account_name: str | None


class InstagramMessageOut(BaseModel):
    id: int
    conversation_id: int
    direction: str
    message_type: str
    content: str | None
    has_media: bool
    provider_timestamp: datetime | None
    delivery_status: str | None
    is_read: bool
    created_at: datetime


def _require_tenant_membership(db: Session, *, tenant_id: int, user_id: int) -> None:
    """Deny by default, including users belonging only to a different tenant."""
    member = db.execute(text("""
        SELECT 1 FROM public.sendro_tenant_users
        WHERE tenant_id = :tenant_id
          AND user_id = :user_id
          AND is_active = TRUE
          AND member_role IN ('owner', 'admin', 'operator', 'viewer')
    """), {"tenant_id": tenant_id, "user_id": user_id}).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=403, detail="Instagram tenant access denied")


def create_instagram_inbox_router(get_current_active_user: Callable):
    router = APIRouter(prefix="/channels/instagram", tags=["Instagram Inbox"])

    @router.get("/conversations", response_model=list[InstagramConversationOut])
    def list_instagram_conversations(
        tenant_id: int = Query(..., ge=1),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user),
    ):
        _require_tenant_membership(db, tenant_id=tenant_id, user_id=current_user.id)
        rows = db.execute(text("""
            SELECT c.id, c.tenant_id, c.channel_account_id,
                   c.external_customer_id, c.contact_name, c.status,
                   c.assigned_to_user_id, c.unread_count,
                   c.last_message_at, c.created_at, c.updated_at,
                   a.display_name AS account_name
            FROM public.sendro_channel_conversations c
            JOIN public.sendro_channel_accounts a
              ON a.id = c.channel_account_id
             AND a.tenant_id = c.tenant_id
             AND a.platform = 'instagram'
            WHERE c.tenant_id = :tenant_id
              AND a.status IN ('testing', 'active')
            ORDER BY c.updated_at DESC, c.id DESC
            LIMIT :limit OFFSET :offset
        """), {"tenant_id": tenant_id, "limit": limit, "offset": offset}).mappings().all()
        return [dict(row) for row in rows]

    @router.get(
        "/conversations/{conversation_id}/messages",
        response_model=list[InstagramMessageOut],
    )
    def list_instagram_messages(
        conversation_id: int = Path(..., ge=1),
        tenant_id: int = Query(..., ge=1),
        limit: int = Query(default=50, ge=1, le=100),
        before_id: int | None = Query(default=None, ge=1),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user),
    ):
        _require_tenant_membership(db, tenant_id=tenant_id, user_id=current_user.id)

        exists = db.execute(text("""
            SELECT 1 FROM public.sendro_channel_conversations c
            JOIN public.sendro_channel_accounts a
              ON a.id = c.channel_account_id
             AND a.tenant_id = c.tenant_id
             AND a.platform = 'instagram'
            WHERE c.id = :conversation_id
              AND c.tenant_id = :tenant_id
              AND a.status IN ('testing', 'active')
        """), {
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
        }).scalar_one_or_none()
        if exists is None:
            raise HTTPException(status_code=404, detail="Instagram conversation not found")

        rows = db.execute(text("""
            SELECT m.id, m.conversation_id, m.direction,
                   m.message_type, m.content,
                   (m.media_json IS NOT NULL) AS has_media,
                   m.provider_timestamp, m.delivery_status,
                   m.is_read, m.created_at
            FROM public.sendro_channel_messages m
            JOIN public.sendro_channel_conversations c
              ON c.id = m.conversation_id
             AND c.tenant_id = m.tenant_id
             AND c.channel_account_id = m.channel_account_id
            JOIN public.sendro_channel_accounts a
              ON a.id = m.channel_account_id
             AND a.tenant_id = m.tenant_id
             AND a.platform = 'instagram'
            WHERE m.conversation_id = :conversation_id
              AND m.tenant_id = :tenant_id
              AND a.status IN ('testing', 'active')
              AND (:before_id IS NULL OR m.id < :before_id)
            ORDER BY m.id DESC
            LIMIT :limit
        """), {
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "before_id": before_id,
            "limit": limit,
        }).mappings().all()
        return [dict(row) for row in rows]

    return router
