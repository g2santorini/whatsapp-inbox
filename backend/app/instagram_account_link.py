"""Dormant Instagram Login account-identity verification and vault coordination.

This module deliberately has NO FastAPI routes, startup hooks, database
connection, scheduler, or automatic HTTP requests. It must never process
real user data before the approved OAuth/session callback and isolated
database-role rollout. No WhatsApp, webhook, posts or comments integration.

Protocol sequence (caller must enforce it):
1. The **real** Sendro authorized claim transaction commits a single-use
   code and passes its server-only ClaimedInstagramCode object.
2. A trusted server invokes prepare_verified_instagram_link() with the
   exact Instagram Login App ID/Secret and an HTTP client.
3. An independently authenticated Sendro tenant owner/admin invokes
   save_verified_instagram_link() within a fresh committed transaction.
4. Never return either credential-bearing object from an API endpoint.

Both token subjects (short- and long-lived) must match a professional account,
and the encrypted vault requires an exactly matching pre-enrolled tenant
Instagram channel account. Any failure requires a NEW login challenge.
"""
from dataclasses import dataclass

from .instagram_oauth_completion import ClaimedInstagramCode
from .instagram_login_oauth import (
    STAGING_CALLBACK, InstagramLoginError,
    exchange_short_lived_token, fetch_authorized_profile,
)
from .instagram_token_lifecycle import (
    InstagramTokenLifecycleError, exchange_instagram_long_lived,
)
from .instagram_token_vault import (
    InstagramTokenVaultDenied, enroll_new_long_lived_token,
)

_PROFESSIONAL_TYPES = frozenset({"BUSINESS", "CREATOR"})


class InstagramAccountLinkDenied(PermissionError):
    """Redacted constant messages; never interpolate Meta-provided content."""


@dataclass(frozen=True, repr=False)
class VerifiedInstagramLink:
    """Server-memory-only credential. Never JSON serialize or log."""
    tenant_id: int
    requested_by_user_id: int
    instagram_user_id: str
    account_type: str
    username: str
    long_lived_access_token: str
    expires_in_seconds: int

    def __repr__(self):
        return "VerifiedInstagramLink(<redacted>)"

    def __str__(self):
        return "<redacted Instagram link>"


def prepare_verified_instagram_link(
    *, claimed_code: ClaimedInstagramCode, instagram_app_id: str,
    instagram_app_secret: str, session=None,
) -> VerifiedInstagramLink:
    """Explicit server-side calls only: code -> short token -> profile
    -> long token -> reverified profile. NO database writes or live routing.

    This function must be invoked only AFTER an authenticated one-time state
    claim has COMMITTED. Profile mismatch aborts before vault persistence.
    """
    if (
        not isinstance(claimed_code, ClaimedInstagramCode)
        or type(claimed_code.tenant_id) is not int
        or claimed_code.tenant_id <= 0
        or type(claimed_code.user_id) is not int
        or claimed_code.user_id <= 0
        or not isinstance(claimed_code.authorization_code, str)
    ):
        raise InstagramAccountLinkDenied("Instagram onboarding claim invalid")
    try:
        short_token = exchange_short_lived_token(
            app_id=instagram_app_id,
            app_secret=instagram_app_secret,
            code=claimed_code.authorization_code,
            redirect_uri=STAGING_CALLBACK,
            session=session,
        )
        short_profile = fetch_authorized_profile(
            access_token=short_token.access_token, session=session,
        )
        if (
            short_profile.instagram_user_id != short_token.instagram_user_id
            or short_profile.account_type not in _PROFESSIONAL_TYPES
        ):
            raise InstagramAccountLinkDenied("Instagram account identity mismatch")

        long_token = exchange_instagram_long_lived(
            short_lived_token=short_token.access_token,
            instagram_app_secret=instagram_app_secret,
            session=session,
        )
        long_profile = fetch_authorized_profile(
            access_token=long_token.access_token, session=session,
        )
        if (
            long_profile.instagram_user_id != short_profile.instagram_user_id
            or long_profile.account_type not in _PROFESSIONAL_TYPES
            or long_profile.account_type != short_profile.account_type
        ):
            raise InstagramAccountLinkDenied("Instagram account identity mismatch")
    except (InstagramLoginError, InstagramTokenLifecycleError):
        raise InstagramAccountLinkDenied("Instagram authorization could not be verified") from None

    return VerifiedInstagramLink(
        tenant_id=claimed_code.tenant_id,
        requested_by_user_id=claimed_code.user_id,
        instagram_user_id=long_profile.instagram_user_id,
        username=long_profile.username,
        account_type=long_profile.account_type,
        long_lived_access_token=long_token.access_token,
        expires_in_seconds=long_token.expires_in_seconds,
    )


def save_verified_instagram_link(
    conn, *, prepared: VerifiedInstagramLink, user,
    tenant_id: int, channel_account_id: int, bearer_token: str,
    jwt_secret: str, jwt_algorithm: str, encryption_key: str,
    now_epoch: int | None = None,
) -> dict:
    """Encrypt credentials only in the exact tenant's existing IG registry.

    The caller MUST begin + COMMIT the DB transaction. The vault rechecks
    fresh MFA, actual tenant membership and exact registered Instagram
    provider ID before INSERT; it rejects duplicate credentials.
    """
    if (
        not isinstance(prepared, VerifiedInstagramLink)
        or user is None
        or type(getattr(user, "id", None)) is not int
        or type(tenant_id) is not int
        or type(channel_account_id) is not int
        or prepared.tenant_id != tenant_id
        or prepared.requested_by_user_id != user.id
        or prepared.account_type not in _PROFESSIONAL_TYPES
    ):
        raise InstagramAccountLinkDenied("Instagram business authorization mismatch")
    try:
        stored = enroll_new_long_lived_token(
            conn, user=user, tenant_id=tenant_id,
            channel_account_id=channel_account_id,
            provider_user_id=prepared.instagram_user_id,
            bearer_token=bearer_token, jwt_secret=jwt_secret,
            jwt_algorithm=jwt_algorithm,
            encryption_key=encryption_key,
            long_lived_token=prepared.long_lived_access_token,
            expires_in_seconds=prepared.expires_in_seconds,
            now_epoch=now_epoch,
        )
    except InstagramTokenVaultDenied:
        raise InstagramAccountLinkDenied("Instagram account could not be linked") from None
    # Deliberately no provider token, email, or Instagram username in result.
    return {
        "connected": bool(stored["connected"]),
        "expires_at_epoch": stored["expires_at_epoch"],
    }
