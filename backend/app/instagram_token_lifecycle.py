"""Manual-call-only Instagram Login long-lived token exchange/refresh adapter.

The Meta Graph token endpoints require GET query parameters containing secrets.
Do NOT call before HTTP client/proxy/telemetry URL-query redaction is verified.
Not routed, scheduled or imported by Sendro app startup.
"""
from dataclasses import dataclass
import requests

from .instagram_meta_egress_guard import require_safe_instagram_meta_egress
from .instagram_meta_transport import instagram_meta_session

GRAPH_LONG_LIVED_EXCHANGE_URL = "https://graph.instagram.com/access_token"
GRAPH_REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
_MAX_TOKEN_LENGTH = 8192
_MIN_LIFETIME_SECONDS = 24 * 3600
_MAX_LIFETIME_SECONDS = 62 * 24 * 3600
_TIMEOUT = 8


class InstagramTokenLifecycleError(RuntimeError):
    """Fixed messages: never forward Meta error bodies or request URLs."""


@dataclass(frozen=True, repr=False)
class InstagramGraphLongLivedToken:
    access_token: str
    expires_in_seconds: int

    def __repr__(self):
        return "InstagramGraphLongLivedToken(<redacted>)"

    def __str__(self):
        return "<redacted Instagram credential>"


def _token(value):
    if (not isinstance(value, str) or not 10 <= len(value) <= _MAX_TOKEN_LENGTH
            or not value.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise InstagramTokenLifecycleError("Invalid Instagram access token")
    return value


def _parse(result):
    try:
        payload = result.json()
    except (ValueError, TypeError):
        raise InstagramTokenLifecycleError("Invalid Instagram token response") from None
    if type(payload) is not dict:
        raise InstagramTokenLifecycleError("Invalid Instagram token response")
    token = _token(payload.get("access_token"))
    expires = payload.get("expires_in")
    token_type = payload.get("token_type")
    if (type(expires) is not int
            or not _MIN_LIFETIME_SECONDS <= expires <= _MAX_LIFETIME_SECONDS
            or (token_type is not None and (
                not isinstance(token_type, str) or token_type.lower() != "bearer"
            ))):
        raise InstagramTokenLifecycleError("Invalid Instagram token response")
    return InstagramGraphLongLivedToken(token, expires)


def _send_get(url, *, params, session=None, egress_approval=None):
    # Validate BEFORE constructing any token-bearing outgoing request.
    require_safe_instagram_meta_egress(egress_approval)
    try:
        with instagram_meta_session(session) as transport:
            reply = transport.get(
                url, params=params, timeout=_TIMEOUT, allow_redirects=False,
                headers={"Accept": "application/json"},
            )
            if reply.status_code != 200:
                raise InstagramTokenLifecycleError("Instagram token request was rejected")
            return _parse(reply)
    except InstagramTokenLifecycleError:
        raise
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        raise InstagramTokenLifecycleError("Instagram token service unavailable") from None


def exchange_instagram_long_lived(*, short_lived_token, instagram_app_secret,
                                  session=None, egress_approval=None):
    """Instagram Login short-lived to long-lived. Explicit server-side call only."""
    token = _token(short_lived_token)
    if not isinstance(instagram_app_secret, str) or not instagram_app_secret:
        raise InstagramTokenLifecycleError("Instagram Login credentials unavailable")
    return _send_get(GRAPH_LONG_LIVED_EXCHANGE_URL, params={
        "grant_type": "ig_exchange_token",
        "client_secret": instagram_app_secret,
        "access_token": token,
    }, session=session, egress_approval=egress_approval)


def refresh_instagram_long_lived(*, long_lived_token, session=None,
                                  egress_approval=None):
    """Caller checks age/expiry first. No automatic scheduling/service grants."""
    token = _token(long_lived_token)
    return _send_get(GRAPH_REFRESH_URL, params={
        "grant_type": "ig_refresh_token", "access_token": token,
    }, session=session, egress_approval=egress_approval)
