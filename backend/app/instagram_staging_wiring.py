"""Only-staging wiring for Instagram account status and future OAuth.

Production never mounts these routes. OAuth requires an independently approved
logging review plus separate encryption keys. A successful CI run or the
presence of Instagram database tables is not activation authorization.
"""
import os

from cryptography.fernet import Fernet

from .instagram_account_status import create_dormant_instagram_account_status_router
from .instagram_onboarding_router import create_dormant_instagram_onboarding_router
from .instagram_oauth_callback_inbox import (
    create_dormant_callback_router,
    capture_instagram_authorization_code,
)
from .instagram_oauth_http_security import (
    InstagramOAuthLogAttestations,
    require_safe_callback_http,
)

STAGING_SERVICE_ID = "srv-d806bq0sfn5c7399akng"
STAGING_HOST = "sendro-backend-staging.onrender.com"


def is_exact_staging_service() -> bool:
    """Do not trust Host headers, user input, or branch name alone."""
    return (
        os.getenv("RENDER_SERVICE_ID") == STAGING_SERVICE_ID
        and os.getenv("RENDER_GIT_BRANCH") == "dev"
        and os.getenv("RENDER_EXTERNAL_HOSTNAME") == STAGING_HOST
    )


def approved_attestations() -> InstagramOAuthLogAttestations:
    """Operator-reviewed flags. Never auto-infer safety from missing logs."""
    def approved(name: str) -> bool:
        return os.getenv(name) == "true"

    return InstagramOAuthLogAttestations(
        ingress_proxy_query_redaction_verified=approved(
            "SENDRO_IG_INGRESS_QUERY_REDACTION_VERIFIED"),
        asgi_access_log_redaction_verified=approved(
            "SENDRO_IG_ASGI_LOG_REDACTION_VERIFIED"),
        egress_meta_query_redaction_verified=approved(
            "SENDRO_IG_EGRESS_LOG_REDACTION_VERIFIED"),
        incident_telemetry_redaction_verified=approved(
            "SENDRO_IG_TELEMETRY_REDACTION_VERIFIED"),
        reviewed_release_authorized=approved(
            "SENDRO_IG_OAUTH_RELEASE_AUTHORIZED"),
    )


def _validated_oauth_settings():
    if os.getenv("SENDRO_IG_OAUTH_ENABLED") != "true":
        return None
    attestations = approved_attestations()
    if not attestations.approved():
        return None

    app_id = os.getenv("INSTAGRAM_APP_ID", "")
    app_secret = os.getenv("INSTAGRAM_APP_SECRET", "")
    callback_key = os.getenv("SENDRO_IG_CALLBACK_FERNET_KEY", "")
    vault_key = os.getenv("SENDRO_IG_VAULT_FERNET_KEY", "")
    if not app_id.isascii() or not app_id.isdecimal() or not 5 <= len(app_id) <= 30:
        return None
    if not app_secret or not callback_key or not vault_key or callback_key == vault_key:
        return None
    try:
        Fernet(callback_key.encode("ascii"))
        Fernet(vault_key.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        return None
    return app_id, app_secret, callback_key, vault_key, attestations


def mount_instagram_staging_wiring(
    app, *, current_user_dependency, bearer_dependency,
    transaction, jwt_secret: str, jwt_algorithm: str,
) -> None:
    """Mount read-only status; mount real OAuth only after all gates pass.

    The supplied transaction is the existing SQLAlchemy engine.begin callable.
    Never create a new database engine or install a schema at startup.
    """
    if not is_exact_staging_service():
        return

    # Metadata-only. Requires signed current-user JWT, fresh MFA, and exact
    # tenant owner/admin authorization. Never reads token ciphertext.
    app.include_router(create_dormant_instagram_account_status_router(
        current_user_dependency=current_user_dependency,
        bearer_dependency=bearer_dependency,
        jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm,
        enabled=True,
    ))

    settings = _validated_oauth_settings()
    if settings is None:
        return
    app_id, app_secret, callback_key, vault_key, attestations = settings

    app.include_router(create_dormant_instagram_onboarding_router(
        current_user_dependency=current_user_dependency,
        bearer_dependency=bearer_dependency,
        transaction=transaction,
        log_attestations=attestations,
        jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm,
        instagram_app_id=app_id,
        instagram_app_secret=app_secret,
        authorization_code_key=callback_key,
        token_vault_key=vault_key,
        enabled=True,
    ))

    def capture(state: str, code: str) -> None:
        with transaction() as conn:
            capture_instagram_authorization_code(
                conn, state=state, code=code, encryption_key=callback_key,
            )

    def request_gate(request) -> None:
        require_safe_callback_http(request, attestations)

    app.include_router(create_dormant_callback_router(
        capture, request_gate=request_gate,
    ))
