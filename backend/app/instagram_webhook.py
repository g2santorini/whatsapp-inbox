"""Instagram Login webhook handshake and fail-closed delivery stub.

Phase 1 intentionally does NOT store, display, or acknowledge Instagram DMs.
Never switch on the Instagram webhook subscription until the separate
Instagram message ingestion pipeline is implemented, tested, and approved.
Secrets are read from runtime env, never from query logs or source files.
"""
import os
import secrets

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .whatsapp_webhook_security import is_valid_meta_webhook_signature


router = APIRouter(prefix="/webhook/instagram", tags=["Instagram webhook"])


@router.get("", response_class=PlainTextResponse)
def verify_instagram_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
):
    """Answer Meta's verification challenge; never fall back to WhatsApp token."""
    configured_token = os.getenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "")
    if not configured_token:
        raise HTTPException(
            status_code=503,
            detail="Instagram webhook verification is not configured",
        )
    if (
        hub_mode != "subscribe"
        or not hub_challenge
        or not hub_verify_token
        or not secrets.compare_digest(hub_verify_token, configured_token)
    ):
        raise HTTPException(status_code=403, detail="Invalid Instagram webhook challenge")
    return PlainTextResponse(content=hub_challenge)


@router.post("")
async def receive_instagram_webhook(request: Request):
    """Reject actual notifications until we can safely persist every message.

    A 2xx response here would tell Meta delivery succeeded when the
    current Sendro backend has nowhere to store Instagram messages.
    """
    app_secret = os.getenv("INSTAGRAM_APP_SECRET", "")
    if not app_secret:
        raise HTTPException(
            status_code=503,
            detail="Instagram webhook signature verification is not configured",
        )

    payload = await request.body()
    if not is_valid_meta_webhook_signature(
        payload, request.headers.get("X-Hub-Signature-256"), app_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid Instagram webhook signature")

    raise HTTPException(
        status_code=503,
        detail="Instagram messaging ingestion is not enabled",
    )
