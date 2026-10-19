"""Fail-closed legacy WhatsApp ownership bridge for the GDPR metadata preview.

Legacy WhatsApp conversations have no tenant_id or trusted Meta business account.
Never infer their company from phone numbers, agent assignment, user membership,
or the fact that only one tenant happens to exist today.

A separately approved MANUAL database operation may create exact conversation
ownership links backed by independent evidence. This module only READS links.
"""
from collections.abc import Mapping

from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

WHATSAPP_FLAG = "SENDRO_PRIVACY_WHATSAPP_VERIFIED_LINKS"
WHATSAPP_VALUE = "reviewed-staging-exact-links-only"
LINK_TABLE = "sendro_privacy_legacy_whatsapp_links"


def whatsapp_links_enabled(settings: Mapping[str, str]) -> bool:
    """Independent opt-in; caller already requires the subject preview gate."""
    return settings.get(WHATSAPP_FLAG) == WHATSAPP_VALUE


def inspect_mapped_whatsapp(db: Session, *, tenant_id: int,
                            conversation_id: int) -> dict:
    """Only count metadata for a specifically verified, non-revoked tenant link.

    The schema is manual-only; a missing table is a safe 409, not a fallback
    to an unscoped query. No phone/subject lookup or raw message exposure.
    """
    bind = db.get_bind()
    if not inspect(bind).has_table(LINK_TABLE, schema="public"):
        raise HTTPException(status_code=409,
                            detail="Verified WhatsApp mapping is not configured")

    matched = db.execute(text("""
        SELECT 1
        FROM public.sendro_privacy_legacy_whatsapp_links l
        JOIN public.conversations c ON c.id = l.conversation_id
        JOIN public.sendro_tenants t ON t.id = l.tenant_id
        WHERE l.tenant_id = :tid AND l.conversation_id = :cid
          AND l.verified_at IS NOT NULL
          AND l.revoked_at IS NULL
          AND l.evidence_ref IS NOT NULL
          AND l.verification_method = 'manual-owner-review'
    """), {"tid": tenant_id, "cid": conversation_id}).scalar_one_or_none()

    if matched is None:
        # Do not reveal whether a conversation exists in another company.
        raise LookupError("Verified conversation not found for this company")

    summary = db.execute(text("""
        SELECT COUNT(*) AS messages,
               COALESCE(SUM(CASE WHEN m.media_id IS NOT NULL
                                      THEN 1 ELSE 0 END), 0) AS media_rows
        FROM public.messages m
        WHERE m.conversation_id = :cid
    """), {"cid": conversation_id}).mappings().one()

    return {
        "platform": "whatsapp",
        "conversation_id": conversation_id,
        "messages": int(summary["messages"]),
        "messages_with_media_metadata": int(summary["media_rows"]),
        "partial_inventory": True,
        "linked_to_case": False,
        "erasure_enabled": False,
        "safe_to_delete_count": 0,
    }
