"""Fail-closed preflight for dormant Meta/Instagram server-side HTTP egress.

This is NOT a Render/Meta telemetry audit. No HTTP call is made by this
module, and it cannot prevent a reverse proxy or external APM from logging
tokens. Operational attestation (PR #90) is a separate prerequisite.

urllib3's DEBUG logs can include full HTTP request paths with token-bearing
query strings for Instagram long-lived token exchange and refresh. Refuse
all Meta protocol HTTP calls if common Python HTTP wire debugging is active.
Never log, stringify or capture provider credentials here.
"""
import http.client
import logging

from .instagram_oauth_http_security import InstagramOAuthLogAttestations


class InstagramMetaEgressDenied(PermissionError):
    """Fixed error message, contains no URLs or credentials."""


_HTTP_LOGGERS = (
    "urllib3",
    "urllib3.connectionpool",
    "requests",
)


def require_safe_instagram_meta_egress(
    log_attestations: InstagramOAuthLogAttestations | None,
) -> None:
    """A prerequisite, NOT proof that provider credentials cannot be logged.

    Operator attestations must be independently reviewed after inspection
    of Render application, edge, outgoing proxy, APM and exception logging.
    Never set these flags based only on synthetic CI tests.
    """
    if (
        not isinstance(log_attestations, InstagramOAuthLogAttestations)
        or not log_attestations.approved()
    ):
        raise InstagramMetaEgressDenied("Instagram Meta network access blocked")

    # Both the parent and child urllib3 loggers are checked, because either
    # can be enabled explicitly irrespective of the root log level.
    if any(logging.getLogger(name).isEnabledFor(logging.DEBUG)
           for name in _HTTP_LOGGERS):
        raise InstagramMetaEgressDenied("Instagram HTTP debug logging is unsafe")

    if http.client.HTTPConnection.debuglevel != 0:
        raise InstagramMetaEgressDenied("Instagram HTTP wire tracing is unsafe")
