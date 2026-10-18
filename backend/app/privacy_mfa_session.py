"""Fresh, signed MFA proof required only for the gated GDPR read-only preview.

No database writes, no persistent tokens, no new routes. The existing Sendro
authentication and tenant-role dependencies still apply before this guard.
"""
import time
from collections.abc import Callable
from datetime import datetime

from fastapi import Depends, HTTPException
from jose import JWTError, jwt

PRIVACY_MFA_MAX_AGE_SECONDS = 600


def add_recent_mfa_claim(data: dict, verified_at: datetime) -> dict:
    """Only use after a verified MFA challenge; never after password/device bypass."""
    if not isinstance(verified_at, datetime) or verified_at.tzinfo is None:
        raise ValueError("MFA verification time must be timezone-aware")
    return {**data, "mfa_verified_at": int(verified_at.timestamp())}


def require_recent_mfa_token(
    user, *, token: str, secret_key: str, algorithm: str,
    now_epoch: int | None = None,
):
    """Require a valid, non-expired access token with a fresh verified-MFA claim."""
    if not getattr(user, "mfa_enabled", False):
        raise HTTPException(status_code=403, detail="Authenticator required")

    try:
        claims = jwt.decode(token, secret_key, algorithms=[algorithm])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    if claims.get("sub") != getattr(user, "username", None):
        raise HTTPException(status_code=403, detail="Privacy access denied")

    verified_at = claims.get("mfa_verified_at")
    now = int(time.time()) if now_epoch is None else now_epoch
    if (
        type(verified_at) is not int
        or verified_at > now
        or now - verified_at > PRIVACY_MFA_MAX_AGE_SECONDS
    ):
        raise HTTPException(status_code=403, detail="Recent authenticator login required")
    return user


def create_privacy_verified_user_dependency(
    active_user_dependency: Callable, token_dependency: Callable,
    *, secret_key: str, algorithm: str,
) -> Callable:
    """Build an independent step-up dependency; does not modify normal Sendro routes."""

    async def privacy_verified_user(
        user=Depends(active_user_dependency),
        token: str = Depends(token_dependency),
    ):
        return require_recent_mfa_token(
            user, token=token, secret_key=secret_key, algorithm=algorithm,
        )

    return privacy_verified_user
