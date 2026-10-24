"""Dormant Instagram Business Login protocol adapter (staging preparation).

No FastAPI route, startup hook, database/queue/WhatsApp import, or credential
storage. An approved server-side onboarding flow must separately bind a
one-time OAuth state to an authenticated tenant owner/admin before using this.
Do not enable Instagram webhooks or DM sends based on this module.
"""

from dataclasses import dataclass
import hmac
import secrets
from urllib.parse import urlencode, urlsplit

import requests

INSTAGRAM_AUTHORIZE = "https://www.instagram.com/oauth/authorize"
INSTAGRAM_TOKEN = "https://api.instagram.com/oauth/access_token"
INSTAGRAM_PROFILE = "https://graph.instagram.com/me"
SCOPES = ("instagram_business_basic", "instagram_business_manage_messages")
STAGING_CALLBACK = "https://sendro-backend-staging.onrender.com/channels/instagram/oauth/callback"
TIMEOUT_SECONDS = 8


class InstagramLoginError(Exception):
    """Sanitized error: never include Meta's token-bearing response body."""


@dataclass(frozen=True, repr=False)
class InstagramShortToken:
    access_token: str
    instagram_user_id: str

    def __repr__(self):
        return "InstagramShortToken(<redacted>)"

    def __str__(self):
        return "<redacted Instagram authorization token>"


@dataclass(frozen=True)
class InstagramProfile:
    instagram_user_id: str
    username: str
    account_type: str | None
    profile_picture_url: str | None


def _check_staging_callback(redirect_uri: str) -> None:
    # Pin the intended callback, rather than accepting an arbitrary redirect.
    if redirect_uri != STAGING_CALLBACK:
        raise InstagramLoginError("Unapproved staging redirect URI")
    parsed = urlsplit(redirect_uri)
    if parsed.scheme != "https" or parsed.query or parsed.fragment:
        raise InstagramLoginError("Invalid staging redirect URI")


def new_state() -> str:
    """A random nonce; the future authenticated endpoint MUST store it once."""
    return secrets.token_urlsafe(32)


def verify_state(expected: str, received: str) -> bool:
    """Only compare: one-time consumption and user/tenant binding are caller duties."""
    return (
        isinstance(expected, str) and isinstance(received, str)
        and len(expected) >= 32 and len(received) >= 32
        and hmac.compare_digest(expected, received)
    )


def build_authorize_url(*, app_id: str, redirect_uri: str, state: str) -> str:
    _check_staging_callback(redirect_uri)
    if not isinstance(app_id, str) or not app_id.isdecimal() or not 5 <= len(app_id) <= 30:
        raise InstagramLoginError("Invalid Instagram Login app ID")
    if not isinstance(state, str) or not 32 <= len(state) <= 128 or not all(
        c.isascii() and (c.isalnum() or c in "-_") for c in state
    ):
        raise InstagramLoginError("Invalid OAuth state")
    return INSTAGRAM_AUTHORIZE + "?" + urlencode({
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ",".join(SCOPES),
        "state": state,
    })


def exchange_short_lived_token(
    *, app_id: str, app_secret: str, code: str, redirect_uri: str,
    session=None,
) -> InstagramShortToken:
    """Server-only code exchange. Caller must never persist plaintext tokens."""
    _check_staging_callback(redirect_uri)
    if not isinstance(app_id, str) or not app_id.isdecimal():
        raise InstagramLoginError("Invalid Instagram Login app ID")
    if not isinstance(app_secret, str) or not app_secret:
        raise InstagramLoginError("Instagram Login is not configured")
    if not isinstance(code, str) or not 1 <= len(code) <= 2048:
        raise InstagramLoginError("Invalid authorization code")
    transport = session or requests
    try:
        result = transport.post(
            INSTAGRAM_TOKEN,
            data={"client_id": app_id, "client_secret": app_secret,
                  "grant_type": "authorization_code", "redirect_uri": redirect_uri,
                  "code": code},
            timeout=TIMEOUT_SECONDS,
            allow_redirects=False,
        )
        if result.status_code != 200:
            raise InstagramLoginError("Instagram authorization failed")
        payload = result.json()
    except InstagramLoginError:
        raise
    except (requests.RequestException, ValueError, TypeError, KeyError):
        raise InstagramLoginError("Instagram authorization unavailable") from None
    if not isinstance(payload, dict):
        raise InstagramLoginError("Invalid Instagram authorization response")
    token = payload.get("access_token")
    user_id = payload.get("user_id")
    if not isinstance(token, str) or not 10 <= len(token) <= 8192:
        raise InstagramLoginError("Invalid Instagram authorization response")
    if not isinstance(user_id, (str, int)) or not str(user_id).isdigit():
        raise InstagramLoginError("Invalid Instagram authorization response")
    return InstagramShortToken(token, str(user_id))


def fetch_authorized_profile(*, access_token: str, session=None) -> InstagramProfile:
    """Only retrieve the authorized business account's profile, not posts or DMs."""
    if not isinstance(access_token, str) or not 10 <= len(access_token) <= 8192:
        raise InstagramLoginError("Invalid Instagram access token")
    transport = session or requests
    try:
        result = transport.get(
            INSTAGRAM_PROFILE,
            params={"fields": "user_id,username,account_type,profile_picture_url"},
            headers={"Authorization": "Bearer " + access_token},
            timeout=TIMEOUT_SECONDS,
            allow_redirects=False,
        )
        if result.status_code != 200:
            raise InstagramLoginError("Instagram profile request failed")
        payload = result.json()
    except InstagramLoginError:
        raise
    except (requests.RequestException, ValueError, TypeError):
        raise InstagramLoginError("Instagram profile unavailable") from None
    if not isinstance(payload, dict):
        raise InstagramLoginError("Invalid Instagram profile response")
    user_id = payload.get("user_id") or payload.get("id")
    username = payload.get("username")
    account_type = payload.get("account_type")
    picture = payload.get("profile_picture_url")
    if not isinstance(user_id, (str, int)) or not str(user_id).isdigit():
        raise InstagramLoginError("Invalid Instagram profile response")
    if not isinstance(username, str) or not 1 <= len(username) <= 100:
        raise InstagramLoginError("Invalid Instagram profile response")
    if account_type is not None and account_type not in {"BUSINESS", "CREATOR"}:
        raise InstagramLoginError("Instagram account is not a supported professional account")
    if picture is not None and (not isinstance(picture, str) or not picture.startswith("https://")):
        raise InstagramLoginError("Invalid Instagram profile response")
    return InstagramProfile(str(user_id), username, account_type, picture)
