"""Dedicated, short-lived outbound HTTPS session for dormant Instagram Login.

Do NOT import from Sendro WhatsApp transport. No startup hooks, network calls
on import, database work, or user data. Network calls remain blocked by the
separate operator-attested egress guard before entering this context.

Real HTTP sessions NEVER honor environment HTTPS_PROXY/ALL_PROXY, NETRC,
custom CA bundles or Requests response hooks. Calls are restricted to the
four exact Meta endpoints/methods used by Instagram Login; redirects, HTTP,
custom proxies, TLS verification bypass, and automatic retries are denied.
This does NOT prevent external infrastructure/APM from logging request URLs.
"""
from contextlib import contextmanager
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter


class InstagramMetaTransportDenied(PermissionError):
    """Fixed diagnostic; do not include URL, query string or secrets."""


_METHOD_TARGETS = frozenset({
    ("POST", "https://api.instagram.com/oauth/access_token"),
    ("GET", "https://graph.instagram.com/me"),
    ("GET", "https://graph.instagram.com/access_token"),
    ("GET", "https://graph.instagram.com/refresh_access_token"),
})


class _PinnedInstagramHTTPS(requests.Session):
    """Do not construct directly outside the context manager."""

    def __init__(self):
        super().__init__()
        self.trust_env = False  # disables .netrc, proxies, env CA settings
        self.proxies.clear()
        self.auth = None
        self.verify = True
        self.max_redirects = 0
        self.hooks = {"response": []}
        self.cookies.clear()
        self.mount("https://", HTTPAdapter(max_retries=0))
        http_adapter = self.adapters.pop("http://", None)
        if http_adapter is not None:
            http_adapter.close()

    def request(self, method, url, **kwargs):
        if not isinstance(method, str) or not isinstance(url, str):
            raise InstagramMetaTransportDenied("Unapproved Instagram HTTP target")
        parts = urlsplit(url)
        if ((method.upper(), url) not in _METHOD_TARGETS
                or parts.query or parts.fragment
                or parts.username or parts.password):
            raise InstagramMetaTransportDenied("Unapproved Instagram HTTP target")
        if kwargs.get("allow_redirects") is not False:
            raise InstagramMetaTransportDenied("Instagram HTTP redirects denied")
        timeout = kwargs.get("timeout")
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not 0 < timeout <= 10):
            raise InstagramMetaTransportDenied("Instagram HTTP timeout denied")
        if any(key in kwargs for key in (
            "proxies", "auth", "verify", "cert", "hooks", "cookies", "stream",
        )):
            raise InstagramMetaTransportDenied("Instagram HTTP options denied")
        return super().request(method.upper(), url, **kwargs)


@contextmanager
def instagram_meta_session(test_session=None):
    """Use pinned real transport, or an explicit OFFLINE test fake.

    Injected transports must be limited to controlled synthetic tests.
    Never inject a general telemetry-wrapped or proxy-enabled HTTP client
    for real Meta credentials. This is NOT an authorization mechanism:
    callers must independently pass the operator-approved egress guard.
    """
    if test_session is not None:
        yield test_session
        return
    with _PinnedInstagramHTTPS() as transport:
        yield transport
