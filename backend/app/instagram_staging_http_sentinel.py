"""External-facing, READ-ONLY staging HTTP sentinel: disabled until approved.

This *one-shot* command proves only that the Sendro staging backend answers
its unauthenticated GET / with expected public JSON. It does NOT prove a
working Instagram webhook, worker, database, queue, dispatcher or operator
alert. Never mount it in the app or assume a cron is configured.

No database imports, service API tokens, Meta calls, query strings, guest
data, cookies, or other request content. Only a HARD-CODED public staging
origin can be contacted, and then only after explicit opt-in. The CLI is
safe to deploy inertly without creating new services.
"""
import json
import os
import urllib.error
import urllib.request

STAGING_STATUS_URL = "https://sendro-backend-staging.onrender.com/"
APPROVAL_KEY = "SENDRO_IG_STAGING_HTTP_SENTINEL_ENABLED"
EXACT_APPROVAL = "I_APPROVE_STAGING_PUBLIC_STATUS_GET_ONLY"
MAX_BYTES = 1024
TIMEOUT_SECONDS = 5


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Never follow an open redirect onto an attacker-controlled host.
        return None


def _fetch_public_staging_status():
    """The ONLY network-capable function. Fixed HTTPS public GET /."""
    request = urllib.request.Request(
        STAGING_STATUS_URL,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "Sendro-staging-status-sentinel/1.0",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
            body = response.read(MAX_BYTES + 1)
            content_type = response.headers.get("Content-Type", "")
    except (OSError, urllib.error.URLError, TimeoutError):
        return False
    if (
        status != 200
        or len(body) > MAX_BYTES
        or "application/json" not in content_type.lower()
    ):
        return False
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeError):
        return False
    return (
        isinstance(decoded, dict)
        and decoded.get("status") == "ok"
        and isinstance(decoded.get("version"), str)
        and 0 < len(decoded["version"]) <= 100
    )


def inspect_staging_http_sentinel(*, environ=None, fetch_status=None):
    """Provide only fixed redacted statuses; never print exception strings.

    An injected fake fetcher permits offline tests. No default network
    attempt is allowed without a literal, dedicated operator approval.
    """
    flags = os.environ if environ is None else environ
    if flags.get(APPROVAL_KEY) != EXACT_APPROVAL:
        return {
            "mode": "staging_public_http_only",
            "backend_http": "disabled",
            "instagram_pipeline": "not_checked",
            "operator_notification": "not_configured",
            "live_pilot_authorized": False,
            "database_access": "none",
            "meta_access": "none",
        }
    try:
        fetch = _fetch_public_staging_status if fetch_status is None else fetch_status
        reachable = fetch() is True
    except Exception:
        reachable = False
    return {
        "mode": "staging_public_http_only",
        "backend_http": "reachable" if reachable else "unavailable",
        "instagram_pipeline": "not_checked",
        "operator_notification": "not_configured",
        "live_pilot_authorized": False,
        "database_access": "none",
        "meta_access": "none",
    }


def main():
    status = inspect_staging_http_sentinel()
    print(json.dumps(status, sort_keys=True))
    # A future separately approved Render cron can notify on non-zero exit.
    # Disabled always exits non-zero: no silent success before commissioning.
    return 0 if status["backend_http"] == "reachable" else 2


if __name__ == "__main__":
    raise SystemExit(main())
