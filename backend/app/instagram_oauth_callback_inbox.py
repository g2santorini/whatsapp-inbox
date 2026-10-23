"""Dormant Instagram OAuth callback bridge: encrypted code capture only.

Not mounted by Sendro's FastAPI app. Does not exchange codes, persist tokens,
start Instagram ingestion, access WhatsApp, or connect to a database on import.
A future manually approved migration must add two nullable fields to the
separate OAuth state table. No live Meta credentials or traffic are required.
"""
from datetime import datetime, timezone
import hashlib
import time
from collections.abc import Callable

from cryptography.fernet import Fernet
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text


class InstagramCallbackDenied(ValueError):
    """Generic, non-reflecting reason; never echo a code or OAuth state."""


_TABLE = "public.sendro_instagram_oauth_challenges"
_HTML_OK = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Sendro Instagram</title></head><body><h1>Instagram authorization received</h1>
<p>Return to your original Sendro tab to complete the connection.</p>
<p>Do not share the authorization address or screenshots containing it.</p>
</body></html>"""
_HTML_ERROR = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Sendro Instagram</title></head><body><h1>Instagram authorization could not be completed</h1>
<p>Return to your Sendro tab and start a new connection request.</p>
</body></html>"""
_HEADERS = {
    "Cache-Control": "no-store, no-cache, max-age=0, private",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _state_digest(state: str) -> str:
    """Match PR #85 state digest; no raw state is recorded in PostgreSQL."""
    if not isinstance(state, str) or not 32 <= len(state) <= 128:
        raise InstagramCallbackDenied("Invalid Instagram callback")
    if not all(c.isascii() and (c.isalnum() or c in "_-") for c in state):
        raise InstagramCallbackDenied("Invalid Instagram callback")
    return hashlib.sha256(("sendro:instagram:oauth:v1:" + state).encode("ascii")).hexdigest()


def capture_instagram_authorization_code(
    conn, *, state: str, code: str, encryption_key: str, now_epoch: int | None = None,
) -> None:
    """Within caller's transaction, encrypt once for an existing unexpired state.

    An authenticated completion handler (not implemented here) must consume
    state+code atomically while rechecking tenant-admin + fresh MFA. Never
    expose the ciphertext or access code in the HTTP response.
    """
    digest = _state_digest(state)
    if not isinstance(code, str) or not 1 <= len(code) <= 2048 or not code.isascii():
        raise InstagramCallbackDenied("Invalid Instagram callback")
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in code):
        raise InstagramCallbackDenied("Invalid Instagram callback")
    now = int(time.time()) if now_epoch is None else now_epoch
    if type(now) is not int or now <= 0:
        raise InstagramCallbackDenied("Invalid Instagram callback")
    try:
        key_bytes = encryption_key.encode("ascii")
        cipher = Fernet(key_bytes).encrypt(code.encode("ascii"))
    except (ValueError, TypeError, UnicodeError, AttributeError):
        raise InstagramCallbackDenied("Instagram callback encryption unavailable") from None

    updated = conn.execute(text(f"""
        UPDATE {_TABLE}
           SET encrypted_authorization_code = :encrypted,
               received_epoch = :now_epoch
         WHERE state_hash = :state_hash
           AND expires_epoch > :now_epoch
           AND encrypted_authorization_code IS NULL
        RETURNING state_hash
    """), {
        "encrypted": cipher, "now_epoch": now, "state_hash": digest,
    }).scalar_one_or_none()
    if updated is None:
        raise InstagramCallbackDenied("Instagram callback expired or already received")


def create_dormant_callback_router(capture: Callable[[str, str], None]) -> APIRouter:
    """Opt-in router factory; never mount automatically or use live DB here.

    The callback intentionally does not redirect to another URL, use cookies,
    reveal OAuth state/code, load assets, or execute browser-side JavaScript.
    Reverse proxy/ASGI query-string access logs MUST be redacted before mount.
    """
    router = APIRouter(tags=["Instagram OAuth - NOT MOUNTED"])

    @router.get("/channels/instagram/oauth/callback", response_class=HTMLResponse)
    def instagram_callback(request: Request):
        params = request.query_params
        # Duplicate values can introduce parser disagreement. Fail closed.
        if any(len(params.getlist(field)) > 1 for field in ("state", "code", "error")):
            return HTMLResponse(_HTML_ERROR, status_code=400, headers=_HEADERS)
        state = params.get("state", "")
        code = params.get("code", "")
        if params.get("error") or not code or not state:
            return HTMLResponse(_HTML_ERROR, status_code=400, headers=_HEADERS)
        try:
            capture(state, code)
        except InstagramCallbackDenied:
            return HTMLResponse(_HTML_ERROR, status_code=400, headers=_HEADERS)
        except Exception:
            # Do not reflect provider payload or exception. Real route must
            # privately monitor only redacted error categories.
            return HTMLResponse(_HTML_ERROR, status_code=503, headers=_HEADERS)
        return HTMLResponse(_HTML_OK, status_code=200, headers=_HEADERS)

    return router
