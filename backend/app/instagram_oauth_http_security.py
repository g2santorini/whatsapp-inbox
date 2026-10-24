"""Fail-closed HTTP policy for a FUTURE Instagram OAuth callback.

No deployment, database, Meta, logging system or environment inspection is
performed here. Positive booleans are OPERATOR ASSERTIONS, not independent
proof about Render / reverse proxy / Meta. A real release must separately
audit ingress and egress logs before providing a positive gate.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit

CALLBACK_PATH = "/channels/instagram/oauth/callback"
STAGING_BACKEND_HOST = "sendro-backend-staging.onrender.com"
STAGING_FRONTEND_ORIGIN = "https://sendro-frontend-staging.onrender.com"
_MAX_CALLBACK_QUERY_BYTES = 3072


class InstagramOAuthSafetyDenied(PermissionError):
    """Do not echo URLs, credentials, OAuth state or header values."""


@dataclass(frozen=True)
class InstagramOAuthLogAttestations:
    """Explicit checks, default ALL false; never infer from code/tests alone."""
    ingress_proxy_query_redaction_verified: bool = False
    asgi_access_log_redaction_verified: bool = False
    egress_meta_query_redaction_verified: bool = False
    incident_telemetry_redaction_verified: bool = False
    reviewed_release_authorized: bool = False

    def approved(self) -> bool:
        return all(
            getattr(self, k) is True
            for k in (
                "ingress_proxy_query_redaction_verified",
                "asgi_access_log_redaction_verified",
                "egress_meta_query_redaction_verified",
                "incident_telemetry_redaction_verified",
                "reviewed_release_authorized",
            )
        )


def _require_approved(config: InstagramOAuthLogAttestations) -> None:
    if not isinstance(config, InstagramOAuthLogAttestations) or not config.approved():
        raise InstagramOAuthSafetyDenied("Instagram OAuth callback activation is blocked")


def _require_exact_backend_host(request) -> None:
    host_values = request.headers.getlist("host")
    if len(host_values) != 1 or host_values[0] != STAGING_BACKEND_HOST:
        raise InstagramOAuthSafetyDenied("Instagram OAuth host is not permitted")
    # Do not trust client-provided forwarded host/proto metadata. Real trusted
    # proxy scheme handling and TLS enforcement remain deployment blockers.
    if any(request.headers.getlist(name) for name in (
        "forwarded", "x-forwarded-host", "x-original-url", "x-rewrite-url"
    )):
        raise InstagramOAuthSafetyDenied("Ambiguous Instagram OAuth request routing")


def require_safe_callback_http(request, config: InstagramOAuthLogAttestations) -> None:
    """Reject an unapproved, non-pinned or malformed Meta GET callback.

    This does NOT sanitize earlier ingress proxy logs. It does not read
    request.query_params to generate logs or send any values downstream.
    """
    _require_approved(config)
    _require_exact_backend_host(request)
    if request.method != "GET" or request.url.path != CALLBACK_PATH:
        raise InstagramOAuthSafetyDenied("Unexpected Instagram OAuth callback route")
    raw = request.scope.get("query_string", b"")
    if not isinstance(raw, bytes) or len(raw) > _MAX_CALLBACK_QUERY_BYTES:
        raise InstagramOAuthSafetyDenied("Invalid Instagram callback request")
    params = request.query_params
    allowed = {"code", "state", "error", "error_reason", "error_description"}
    if not set(params.keys()).issubset(allowed):
        raise InstagramOAuthSafetyDenied("Unsupported Instagram callback parameter")
    if any(len(params.getlist(k)) != 1 for k in params.keys()):
        raise InstagramOAuthSafetyDenied("Duplicate Instagram callback parameter")
    state = params.get("state")
    if not isinstance(state, str) or not 32 <= len(state) <= 128:
        raise InstagramOAuthSafetyDenied("Invalid Instagram callback state")
    # The lower-level capture handler checks character restrictions and
    # rejects missing/invalid codes and provider-error responses.
    if "code" in params and "error" in params:
        raise InstagramOAuthSafetyDenied("Conflicting Instagram callback parameters")
    if "code" not in params and "error" not in params:
        raise InstagramOAuthSafetyDenied("Missing Instagram callback outcome")


def require_safe_completion_http(request, config: InstagramOAuthLogAttestations) -> None:
    """Layered POST guard, NOT a substitute for real Sendro JWT+MFA+CSRF.

    Future POST route must independently use get_current_active_user, exact
    tenant owner/admin access, a committed one-time state claim and proper
    browser-session binding before any Meta token exchange.
    """
    _require_approved(config)
    _require_exact_backend_host(request)
    if request.method != "POST":
        raise InstagramOAuthSafetyDenied("Instagram completion must use POST")
    if request.headers.get("origin") != STAGING_FRONTEND_ORIGIN:
        raise InstagramOAuthSafetyDenied("Instagram completion origin denied")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise InstagramOAuthSafetyDenied("Instagram completion content type denied")
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or len(header) < 18:
        raise InstagramOAuthSafetyDenied("Instagram completion requires Sendro authentication")


def safe_oauth_audit_event(*, event: str, status: str) -> dict[str, str]:
    """Structured event, with NO dynamic URL or sensitive source text."""
    permitted_events = {
        "callback_received", "callback_rejected",
        "completion_received", "completion_rejected",
    }
    permitted_statuses = {"accepted", "denied", "unavailable"}
    if event not in permitted_events or status not in permitted_statuses:
        raise InstagramOAuthSafetyDenied("Unsupported OAuth audit category")
    return {"component": "instagram_oauth", "event": event, "status": status}


def describe_meta_http_target_for_audit(value: str) -> str:
    """Categorical target label only. Never include a Graph query or token."""
    if not isinstance(value, str):
        return "external_request_redacted"
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "external_request_redacted"
    if parsed.scheme == "https" and parsed.netloc == "graph.instagram.com":
        if parsed.path == "/access_token":
            return "instagram_long_lived_exchange"
        if parsed.path == "/refresh_access_token":
            return "instagram_long_lived_refresh"
        if parsed.path == "/me":
            return "instagram_professional_profile"
    return "external_request_redacted"
