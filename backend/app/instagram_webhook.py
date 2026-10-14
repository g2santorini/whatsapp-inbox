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
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import SQLAlchemyError

from .instagram_ingestion import (
    MAX_INSTAGRAM_WEBHOOK_BODY_BYTES,
    persist_instagram_webhook,
)
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
    """Verify Meta's signed payload. Store only when deliberately enabled.

    No worker is running yet. Keep the ingestion flag OFF and Instagram
    webhook subscription OFF until tenant-safe message processing is ready.
    """
    app_secret = os.getenv("INSTAGRAM_APP_SECRET", "")
    if not app_secret:
        raise HTTPException(
            status_code=503,
            detail="Instagram webhook signature verification is not configured",
        )

    # Bound input before reading it all into memory. Meta's genuine payload
    # signature is computed against these exact, unmodified bytes.
    chunks = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > MAX_INSTAGRAM_WEBHOOK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Instagram webhook body too large")
        chunks.append(chunk)
    payload = b"".join(chunks)

    if not is_valid_meta_webhook_signature(
        payload, request.headers.get("X-Hub-Signature-256"), app_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid Instagram webhook signature")

    if os.getenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "").lower() != "true":
        raise HTTPException(
            status_code=503,
            detail="Instagram messaging ingestion is not enabled",
        )

    encryption_key = os.getenv("INSTAGRAM_WEBHOOK_ENCRYPTION_KEY", "")
    if not encryption_key:
        raise HTTPException(
            status_code=503,
            detail="Instagram webhook encryption is not configured",
        )

    # Import the database only after explicit opt-in. Standalone webhook
    # verification tests must not require a connection to production DB.
    from .database import engine

    try:
        await run_in_threadpool(
            persist_instagram_webhook, payload, encryption_key, engine
        )
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(status_code=400, detail="Invalid Instagram webhook payload or encryption key")
    except SQLAlchemyError:
        # A 5xx tells Meta to retry instead of dropping a guest message.
        raise HTTPException(status_code=503, detail="Instagram webhook storage unavailable")

    return {"status": "stored"}
