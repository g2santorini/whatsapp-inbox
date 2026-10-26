"""Dormant, metadata-only Instagram account connection status.

NOT mounted by Sendro main. No database calls during import, no Meta calls,
no token refresh, no token decrypt, and no production account changes.
Even an account with a saved, unexpired token is NOT proof Meta authorization
is still valid or DM delivery is enabled.

This endpoint must be opt-in only for independently reviewed staging. Both
staging and production currently share PostgreSQL: the encrypted vault
table does NOT exist until an approved manual migration is completed.
"""
import time
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import get_db
from .instagram_oauth_http_security import (
    InstagramOAuthSafetyDenied, _require_exact_backend_host,
)
from .instagram_oauth_state import (
    InstagramOAuthDenied, _require_current_user_and_fresh_mfa,
    _require_owner_admin,
)

_NO_CACHE = {
    "Cache-Control": "private, no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_ALLOWED_CREDENTIAL_STATUSES = {"not_linked", "stored_unverified", "expired"}


class InstagramAccountStatusOut(BaseModel):
    channel_account_id: int
    display_name: str
    registration_status: str
    credential_status: str
    expires_at_epoch: int | None


class InstagramAccountStatusListOut(BaseModel):
    tenant_id: int
    accounts: list[InstagramAccountStatusOut]
    messaging_enabled: bool = False
    meta_authorization_verified_now: bool = False


def read_instagram_account_status(
    conn, *, user, tenant_id: int, bearer_token: str,
    jwt_secret: str, jwt_algorithm: str, now_epoch: int | None = None,
) -> dict:
    """Return ONLY selected registry and expiry columns after current admin MFA.

    The SQL deliberately never selects encrypted_token, provider user ID,
    authorization code, webhook payload, customer data or any Meta token.
    Vault join matches tenant, registry account ID and provider identity.
    """
    now = int(time.time()) if now_epoch is None else now_epoch
    if type(now) is not int or now <= 0 or type(tenant_id) is not int or tenant_id <= 0:
        raise InstagramOAuthDenied("Instagram account status access denied")
    _require_current_user_and_fresh_mfa(
        user, bearer_token=bearer_token, jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm, now_epoch=now,
    )
    _require_owner_admin(conn, tenant_id=tenant_id, user_id=user.id)

    rows = conn.execute(text("""
        SELECT a.id AS channel_account_id,
               a.display_name, a.status AS registration_status,
               v.expires_epoch
        FROM public.sendro_channel_accounts AS a
        LEFT JOIN public.sendro_instagram_token_vault AS v
          ON v.tenant_id = a.tenant_id
         AND v.channel_account_id = a.id
         AND v.provider_user_id = a.external_account_id
        WHERE a.tenant_id = :tenant_id
          AND a.platform = 'instagram'
          AND a.status IN ('testing', 'active')
        ORDER BY a.id
        LIMIT 50
    """), {"tenant_id": tenant_id}).mappings().all()

    accounts = []
    for row in rows:
        expires = row["expires_epoch"]
        if expires is None:
            credential_status = "not_linked"
        elif int(expires) <= now:
            credential_status = "expired"
        else:
            credential_status = "stored_unverified"
        if credential_status not in _ALLOWED_CREDENTIAL_STATUSES:
            raise InstagramOAuthDenied("Instagram credential status invalid")
        # Registry label can be operator-supplied, NOT verified Meta username.
        # Avoid even accidentally returning an unbounded diagnostic string.
        label = str(row["display_name"] or "Instagram account")
        accounts.append({
            "channel_account_id": int(row["channel_account_id"]),
            "display_name": label[:160],
            "registration_status": str(row["registration_status"]),
            "credential_status": credential_status,
            "expires_at_epoch": int(expires) if expires is not None else None,
        })
    return {
        "tenant_id": tenant_id,
        "accounts": accounts,
        "messaging_enabled": False,
        "meta_authorization_verified_now": False,
    }


def create_dormant_instagram_account_status_router(
    *, current_user_dependency: Callable,
    bearer_dependency: Callable, jwt_secret: str, jwt_algorithm: str,
    db_dependency: Callable = get_db, enabled: bool = False,
) -> APIRouter:
    """GET-only opt-in factory; never add to main.py automatically."""
    router = APIRouter(
        prefix="/channels/instagram",
        tags=["Instagram Account Status - UNMOUNTED"],
    )

    @router.get("/account-status", response_model=InstagramAccountStatusListOut)
    def account_status(
        request: Request, tenant_id: int = Query(..., ge=1),
        db: Session = Depends(db_dependency),
        user=Depends(current_user_dependency),
        bearer_token: str = Depends(bearer_dependency),
    ):
        if enabled is not True:
            return JSONResponse(
                {"detail": "Instagram account status unavailable"},
                status_code=503, headers=_NO_CACHE,
            )
        try:
            _require_exact_backend_host(request)
            if request.url.query != f"tenant_id={tenant_id}":
                raise InstagramOAuthSafetyDenied("Unapproved Instagram query")
            result = read_instagram_account_status(
                db, user=user, tenant_id=tenant_id,
                bearer_token=bearer_token, jwt_secret=jwt_secret,
                jwt_algorithm=jwt_algorithm,
            )
            return JSONResponse(result, headers=_NO_CACHE)
        except (InstagramOAuthDenied, InstagramOAuthSafetyDenied):
            return JSONResponse(
                {"detail": "Instagram account access denied"},
                status_code=403, headers=_NO_CACHE,
            )
        except Exception:
            # Includes missing table; never echo SQL, token, tenant details.
            return JSONResponse(
                {"detail": "Instagram account status unavailable"},
                status_code=503, headers=_NO_CACHE,
            )

    return router
