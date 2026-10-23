"""Unmounted, durable-store-ready Instagram OAuth state coordinator.

Explicitly NOT included in FastAPI startup. Requires an already authenticated
Sendro user and a manually reviewed PostgreSQL challenge table before use.
No access-token storage, Meta calls, WhatsApp changes, or live account wiring.
The proposed completion method is a future authenticated POST from the
staging UI, not an unauthenticated provider GET callback.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import secrets
import time

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import text

from .instagram_login_oauth import STAGING_CALLBACK, build_authorize_url
from .privacy_mfa_session import require_recent_mfa_token

STATE_LIFETIME_SECONDS = 300
MIN_STATE_LENGTH = 32
MAX_STATE_LENGTH = 128
_TABLE = "public.sendro_instagram_oauth_challenges"


class InstagramOAuthDenied(PermissionError):
    """Constant error messages: do not echo a state, token or identifiers."""


@dataclass(frozen=True)
class IssuedInstagramOAuth:
    authorization_url: str
    expires_at_epoch: int


@dataclass(frozen=True)
class ConsumedInstagramOAuth:
    user_id: int
    tenant_id: int


def _now(now_epoch=None):
    value = int(time.time()) if now_epoch is None else now_epoch
    if type(value) is not int or value <= 0:
        raise InstagramOAuthDenied("Invalid time")
    return value


def _state_hash(state):
    if not isinstance(state, str) or not MIN_STATE_LENGTH <= len(state) <= MAX_STATE_LENGTH:
        raise InstagramOAuthDenied("Invalid Instagram OAuth state")
    if not all(c.isascii() and (c.isalnum() or c in "_-") for c in state):
        raise InstagramOAuthDenied("Invalid Instagram OAuth state")
    return hashlib.sha256(("sendro:instagram:oauth:v1:" + state).encode("ascii")).hexdigest()


def _require_owner_admin(conn, *, tenant_id, user_id):
    if type(tenant_id) is not int or tenant_id <= 0:
        raise InstagramOAuthDenied("Instagram organization access denied")
    if type(user_id) is not int or user_id <= 0:
        raise InstagramOAuthDenied("Instagram organization access denied")
    member = conn.execute(text("""
        SELECT 1 FROM public.sendro_tenant_users
         WHERE tenant_id = :tenant_id
           AND user_id = :user_id
           AND is_active = TRUE
           AND member_role IN ('owner', 'admin')
    """), {"tenant_id": tenant_id, "user_id": user_id}).scalar_one_or_none()
    if member is None:
        raise InstagramOAuthDenied("Instagram organization access denied")


def _require_current_user_and_fresh_mfa(
    user, *, bearer_token, jwt_secret, jwt_algorithm, now_epoch
):
    """Enforce existing Sendro auth-version rules even in isolated use.

    The future route MUST additionally use Sendro's get_current_active_user
    dependency before calling this helper. Never trust a tenant_id from a
    callback alone, and never use a hardcoded JWT signing key.
    """
    if (
        user is None or type(getattr(user, "id", None)) is not int
        or user.id <= 0 or getattr(user, "disabled", True)
        or getattr(user, "must_change_password", False)
        or getattr(user, "mfa_setup_required", False)
        or getattr(user, "role", None) in {"developer", "project_viewer"}
    ):
        raise InstagramOAuthDenied("Instagram onboarding is not authorized")
    if not isinstance(bearer_token, str) or not bearer_token:
        raise InstagramOAuthDenied("Instagram onboarding is not authorized")
    try:
        claims = jwt.decode(
            bearer_token, jwt_secret, algorithms=[jwt_algorithm]
        )
    except (JWTError, TypeError, ValueError):
        raise InstagramOAuthDenied("Instagram onboarding is not authorized") from None
    current_version = getattr(user, "auth_version", 1) or 1
    token_version = claims.get("ver")
    if type(current_version) is not int or current_version <= 0 or (
        token_version is None and current_version != 1
    ) or (
        token_version is not None and (
            type(token_version) is not int or token_version != current_version
        )
    ):
        raise InstagramOAuthDenied("Instagram onboarding is not authorized")
    try:
        require_recent_mfa_token(
            user, token=bearer_token, secret_key=jwt_secret,
            algorithm=jwt_algorithm, now_epoch=now_epoch,
        )
    except HTTPException:
        raise InstagramOAuthDenied("Fresh authenticator verification required") from None


def issue_instagram_oauth(
    conn, *, user, tenant_id, bearer_token,
    jwt_secret, jwt_algorithm, instagram_app_id, now_epoch=None,
):
    """Check fresh MFA + actual tenant role before creating hashed one-time state.

    Caller must wrap this insert in a COMMITTED transaction. No unprotected
    browser-side localStorage state, no auto-install of required table.
    """
    now = _now(now_epoch)
    _require_current_user_and_fresh_mfa(
        user, bearer_token=bearer_token, jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm, now_epoch=now,
    )
    _require_owner_admin(conn, tenant_id=tenant_id, user_id=user.id)
    state = secrets.token_urlsafe(32)
    authorize = build_authorize_url(
        app_id=instagram_app_id, redirect_uri=STAGING_CALLBACK, state=state,
    )
    conn.execute(text(f"""
        INSERT INTO {_TABLE}
          (state_hash, tenant_id, user_id, created_epoch, expires_epoch)
        VALUES
          (:state_hash, :tenant_id, :user_id, :created_epoch, :expires_epoch)
    """), {
        "state_hash": _state_hash(state), "tenant_id": tenant_id,
        "user_id": user.id, "created_epoch": now,
        "expires_epoch": now + STATE_LIFETIME_SECONDS,
    })
    return IssuedInstagramOAuth(
        authorization_url=authorize, expires_at_epoch=now + STATE_LIFETIME_SECONDS,
    )


def consume_instagram_oauth(
    conn, *, state, user, tenant_id, bearer_token,
    jwt_secret, jwt_algorithm, now_epoch=None,
):
    """Atomically burn an exact user's tenant-bound, unexpired state.

    The future frontend flow must send code+state to an authenticated
    same-origin backend endpoint. Exchange the Meta code only AFTER this
    transaction commits; if exchange fails, restart login (never reuse state).
    No token or provider callback is processed by this module.
    """
    now = _now(now_epoch)
    digest = _state_hash(state)
    _require_current_user_and_fresh_mfa(
        user, bearer_token=bearer_token, jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm, now_epoch=now,
    )
    _require_owner_admin(conn, tenant_id=tenant_id, user_id=user.id)
    row = conn.execute(text(f"""
        DELETE FROM {_TABLE}
         WHERE state_hash = :state_hash
           AND tenant_id = :tenant_id
           AND user_id = :user_id
           AND expires_epoch > :now_epoch
        RETURNING user_id, tenant_id
    """), {
        "state_hash": digest, "user_id": user.id,
        "tenant_id": tenant_id, "now_epoch": now,
    }).mappings().one_or_none()
    if row is None:
        raise InstagramOAuthDenied("Instagram OAuth state expired or already used")
    return ConsumedInstagramOAuth(
        user_id=int(row["user_id"]), tenant_id=int(row["tenant_id"])
    )
