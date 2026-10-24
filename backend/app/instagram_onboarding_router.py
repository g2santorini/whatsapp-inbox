"""DORMANT Instagram Login start/complete router: NEVER mounted by Sendro main.

Makes existing OAuth components into a correctly ordered, opt-in boundary.
No import-time I/O, no automatic tables or background workers. Staging and
production share PostgreSQL: only mount after explicit operator approval,
verified backups, reviewed table migrations, limited database privileges,
proxy log redaction and an authenticated browser integration.

Start: real Sendro JWT + current user + recent MFA + tenant owner/admin
       -> committed one-use state -> authorization URL.
Complete: same guards + user/tenant + completed callback + committed
          one-use state/code claim -> Meta verification (outside SQL tx)
          -> second transaction storing ONLY encrypted long-lived token.

The frontend sends the OAuth *state* but NEVER the provider code/token.
GET provider callback is a separate protected and still-unmounted router.
"""
import json
from collections.abc import Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .instagram_account_link import (
    InstagramAccountLinkDenied,
    prepare_verified_instagram_link,
    save_verified_instagram_link,
)
from .instagram_oauth_completion import claim_captured_instagram_code
from .instagram_oauth_http_security import (
    InstagramOAuthLogAttestations,
    InstagramOAuthSafetyDenied,
    require_safe_completion_http,
)
from .instagram_oauth_state import (
    InstagramOAuthDenied,
    issue_instagram_oauth,
)

_MAX_REQUEST_BYTES = 512
_ERROR_HEADERS = {
    "Cache-Control": "no-store, private",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class InstagramOnboardingRequestDenied(ValueError):
    """Fixed failure only: do not reflect state/provider response/URL."""


async def _validated_body(request: Request, *, complete: bool) -> dict:
    if request.url.query:
        raise InstagramOnboardingRequestDenied("Query not permitted")
    raw = await request.body()
    if len(raw) > _MAX_REQUEST_BYTES:
        raise InstagramOnboardingRequestDenied("Invalid request size")
    try:
        value = json.loads(raw)
    except (ValueError, TypeError, UnicodeError):
        raise InstagramOnboardingRequestDenied("Malformed Instagram request") from None
    expected = {"tenant_id", "state", "channel_account_id"} if complete else {"tenant_id"}
    if type(value) is not dict or set(value) != expected:
        raise InstagramOnboardingRequestDenied("Invalid Instagram request")
    if type(value["tenant_id"]) is not int or value["tenant_id"] <= 0:
        raise InstagramOnboardingRequestDenied("Invalid Instagram business")
    if complete:
        state = value["state"]
        if (not isinstance(state, str) or not 32 <= len(state) <= 128
                or not all(c.isascii() and (c.isalnum() or c in "-_") for c in state)):
            raise InstagramOnboardingRequestDenied("Invalid Instagram state")
        if type(value["channel_account_id"]) is not int or value["channel_account_id"] <= 0:
            raise InstagramOnboardingRequestDenied("Invalid Instagram account")
    return value


def create_dormant_instagram_onboarding_router(
    *,
    current_user_dependency: Callable,
    bearer_dependency: Callable,
    transaction: Callable,
    log_attestations: InstagramOAuthLogAttestations,
    jwt_secret: str,
    jwt_algorithm: str,
    instagram_app_id: str,
    instagram_app_secret: str,
    authorization_code_key: str,
    token_vault_key: str,
    enabled: bool = False,
    prepare_link: Callable = prepare_verified_instagram_link,
    save_link: Callable = save_verified_instagram_link,
) -> APIRouter:
    """Factory only; injection is explicit. DO NOT include_router in main.

    `transaction` must yield a SQLAlchemy Connection in a context manager
    which commits on successful exit, rolls back on errors (engine.begin).
    The calling service must provide real get_current_active_user and the
    actual OAuth2 bearer extractor — never client-supplied user identity.
    """
    router = APIRouter(
        prefix="/channels/instagram/oauth",
        tags=["Instagram Login - UNMOUNTED"],
    )

    def deny(status: int, message: str) -> JSONResponse:
        return JSONResponse({"detail": message}, status_code=status,
                            headers=_ERROR_HEADERS)

    def check_http(request: Request) -> None:
        if enabled is not True:
            raise InstagramOAuthSafetyDenied("Instagram onboarding not activated")
        require_safe_completion_http(request, log_attestations)
        if request.url.path not in {
            "/channels/instagram/oauth/start",
            "/channels/instagram/oauth/complete",
        }:
            raise InstagramOAuthSafetyDenied("Instagram onboarding route denied")

    @router.post("/start")
    async def start_instagram(
        request: Request,
        current_user=Depends(current_user_dependency),
        bearer_token: str = Depends(bearer_dependency),
    ):
        try:
            check_http(request)
            payload = await _validated_body(request, complete=False)
            with transaction() as conn:
                issued = issue_instagram_oauth(
                    conn, user=current_user, tenant_id=payload["tenant_id"],
                    bearer_token=bearer_token, jwt_secret=jwt_secret,
                    jwt_algorithm=jwt_algorithm, instagram_app_id=instagram_app_id,
                )
            # The state is already within this one-time URL; the frontend
            # keeps it only in memory and never logs the URL.
            return JSONResponse({
                "authorization_url": issued.authorization_url,
                "expires_at_epoch": issued.expires_at_epoch,
            }, headers=_ERROR_HEADERS)
        except InstagramOAuthSafetyDenied:
            return deny(503, "Instagram onboarding is not available")
        except InstagramOnboardingRequestDenied:
            return deny(400, "Invalid Instagram onboarding request")
        except InstagramOAuthDenied:
            return deny(403, "Instagram onboarding is not authorized")
        except Exception:
            # Includes unset vault table/config or SQL errors. Never reflect
            # exception, SQL params, URLs or provider tokens to client.
            return deny(503, "Instagram onboarding is unavailable")

    @router.post("/complete")
    async def complete_instagram(
        request: Request,
        current_user=Depends(current_user_dependency),
        bearer_token: str = Depends(bearer_dependency),
    ):
        try:
            check_http(request)
            payload = await _validated_body(request, complete=True)
            tenant = payload["tenant_id"]
            with transaction() as conn:
                claimed = claim_captured_instagram_code(
                    conn, state=payload["state"], user=current_user,
                    tenant_id=tenant, bearer_token=bearer_token,
                    jwt_secret=jwt_secret, jwt_algorithm=jwt_algorithm,
                    encryption_key=authorization_code_key,
                )
            # The DELETE above MUST be committed before provider network
            # calls or token-vault write. On failure, restart from /start.
            prepared = prepare_link(
                claimed_code=claimed,
                instagram_app_id=instagram_app_id,
                instagram_app_secret=instagram_app_secret,
            )
            with transaction() as conn:
                result = save_link(
                    conn, prepared=prepared, user=current_user,
                    tenant_id=tenant, channel_account_id=payload["channel_account_id"],
                    bearer_token=bearer_token, jwt_secret=jwt_secret,
                    jwt_algorithm=jwt_algorithm, encryption_key=token_vault_key,
                )
            return JSONResponse({
                "connected": result["connected"],
                "expires_at_epoch": result["expires_at_epoch"],
            }, headers=_ERROR_HEADERS)
        except InstagramOAuthSafetyDenied:
            return deny(503, "Instagram onboarding is not available")
        except InstagramOnboardingRequestDenied:
            return deny(400, "Invalid Instagram onboarding request")
        except InstagramOAuthDenied:
            return deny(403, "Instagram onboarding is not authorized")
        except InstagramAccountLinkDenied:
            return deny(409, "Instagram onboarding must be restarted")
        except Exception:
            return deny(503, "Instagram onboarding is unavailable")

    return router
