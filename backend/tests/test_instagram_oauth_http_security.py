"""Offline callback fail-closed tests. Never contact Meta, Render or Sendro DB."""
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.instagram_oauth_callback_inbox import create_dormant_callback_router
from backend.app.instagram_oauth_http_security import (
    InstagramOAuthSafetyDenied,
    InstagramOAuthLogAttestations,
    require_safe_callback_http,
    require_safe_completion_http,
    safe_oauth_audit_event,
    describe_meta_http_target_for_audit,
    STAGING_BACKEND_HOST, STAGING_FRONTEND_ORIGIN, CALLBACK_PATH,
)

CODE = "FAKE_SENSITIVE_INSTAGRAM_CODE_ONLY_FOR_CI"
STATE = "n" * 43
BASE = "https://" + STAGING_BACKEND_HOST


def reviewed():
    """Synthetic switches: never evidence that real proxies were reviewed."""
    return InstagramOAuthLogAttestations(
        ingress_proxy_query_redaction_verified=True,
        asgi_access_log_redaction_verified=True,
        egress_meta_query_redaction_verified=True,
        incident_telemetry_redaction_verified=True,
        reviewed_release_authorized=True,
    )


def callback_client(config=None, capture=None):
    app = FastAPI()
    events = []

    def save(state, code):
        events.append((state, code))
        if capture:
            capture(state, code)

    guard = None if config is None else lambda req: require_safe_callback_http(req, config)
    app.include_router(create_dormant_callback_router(save, request_gate=guard))
    return TestClient(app, base_url=BASE), events


def test_callback_without_guard_is_blocked_by_default():
    client, calls = callback_client()
    response = client.get(CALLBACK_PATH, params={"state": STATE, "code": CODE})
    assert response.status_code == 503
    assert calls == []
    assert CODE not in response.text and STATE not in response.text
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("flag", [
    "ingress_proxy_query_redaction_verified",
    "asgi_access_log_redaction_verified",
    "egress_meta_query_redaction_verified",
    "incident_telemetry_redaction_verified",
    "reviewed_release_authorized",
])
def test_missing_single_attestation_blocks_callback(flag):
    values = {name: True for name in reviewed().__dataclass_fields__}
    values[flag] = False
    client, calls = callback_client(InstagramOAuthLogAttestations(**values))
    response = client.get(CALLBACK_PATH, params={"state": STATE, "code": CODE})
    assert response.status_code == 503
    assert calls == []


def test_no_attestation_or_string_true_is_never_approval():
    assert not InstagramOAuthLogAttestations().approved()
    values = {name: True for name in reviewed().__dataclass_fields__}
    values["reviewed_release_authorized"] = "true"
    assert not InstagramOAuthLogAttestations(**values).approved()


def test_synthetic_positive_gate_can_capture_without_reflection():
    client, calls = callback_client(reviewed())
    response = client.get(CALLBACK_PATH, params={"state": STATE, "code": CODE})
    assert response.status_code == 200 and calls == [(STATE, CODE)]
    assert CODE not in response.text and STATE not in response.text
    assert "no-referrer" in response.headers.get("referrer-policy", "")
    assert "no-store" in response.headers.get("cache-control", "")


@pytest.mark.parametrize("query", [
    [("state", STATE), ("code", CODE), ("code", CODE)],
    [("state", STATE), ("code", CODE), ("unexpected", "true")],
    [("state", STATE), ("code", CODE), ("error", "access_denied")],
    [("state", "small"), ("code", CODE)],
    [("state", STATE), ("code", CODE), ("error_description", "a" * 5000)],
])
def test_callback_ambiguous_or_large_queries_are_rejected(query):
    client, calls = callback_client(reviewed())
    response = client.get(CALLBACK_PATH + "?" + urlencode(query))
    assert response.status_code == 503
    assert calls == [] and CODE not in response.text


def test_wrong_host_or_forwarded_host_rejected():
    client, calls = callback_client(reviewed())
    for headers in (
        {"Host": "other.example"},
        {"X-Forwarded-Host": "other.example"},
        {"Forwarded": "host=other.example"},
        {"X-Original-URL": "/other"},
    ):
        response = client.get(CALLBACK_PATH,
                              params={"state": STATE, "code": CODE}, headers=headers)
        assert response.status_code == 503
    assert calls == []


def test_meta_error_is_not_an_authorization():
    client, calls = callback_client(reviewed())
    response = client.get(CALLBACK_PATH, params={
        "state": STATE, "error": "access_denied",
        "error_description": "synthetic sensitive provider text",
    })
    assert response.status_code == 400
    assert "synthetic sensitive" not in response.text and calls == []


def completion_client(config):
    app = FastAPI()

    @app.post("/channels/instagram/oauth/complete")
    async def complete(request: Request):
        try:
            require_safe_completion_http(request, config)
        except InstagramOAuthSafetyDenied:
            return JSONResponse({"detail": "Instagram OAuth unavailable"}, status_code=403)
        return {"request_policy_accepted": True}

    return TestClient(app, base_url=BASE)


def test_completion_requires_pinned_frontend_origin_and_bearer_auth():
    client = completion_client(reviewed())
    accepted = {
        "Origin": STAGING_FRONTEND_ORIGIN,
        "Content-Type": "application/json",
        "Authorization": "Bearer synthetic-not-a-real-JWT",
    }
    assert client.post("/channels/instagram/oauth/complete", headers=accepted,
                       json={"state": STATE}).status_code == 200
    for change in (
        {"Origin": "https://evil.example"},
        {"Origin": ""},
        {"Content-Type": "text/plain"},
        {"Authorization": ""},
        {"Host": "evil.example"},
    ):
        headers = {**accepted, **change}
        response = client.post("/channels/instagram/oauth/complete",
                               headers=headers, json={"state": STATE})
        assert response.status_code == 403
        assert CODE not in response.text and STATE not in response.text


def test_completion_is_blocked_with_no_attestation():
    client = completion_client(InstagramOAuthLogAttestations())
    response = client.post("/channels/instagram/oauth/complete", headers={
        "Origin": STAGING_FRONTEND_ORIGIN,
        "Content-Type": "application/json",
        "Authorization": "Bearer synthetic-not-a-real-JWT",
    }, json={"state": STATE})
    assert response.status_code == 403


def test_safe_audit_never_accepts_dynamic_values():
    safe = safe_oauth_audit_event(event="callback_received", status="accepted")
    assert safe == {
        "component": "instagram_oauth",
        "event": "callback_received", "status": "accepted",
    }
    with pytest.raises(InstagramOAuthSafetyDenied):
        safe_oauth_audit_event(event=CODE, status="denied")
    with pytest.raises(InstagramOAuthSafetyDenied):
        safe_oauth_audit_event(event="callback_received", status=STATE)


def test_external_graph_urls_never_log_query_secrets():
    link = ("https://graph.instagram.com/access_token?client_secret="
            + CODE + "&access_token=" + STATE)
    assert describe_meta_http_target_for_audit(link) == "instagram_long_lived_exchange"
    for uri in (
        "https://graph.instagram.com/refresh_access_token?access_token=" + CODE,
        "https://attacker.example/my-token/" + CODE,
        "not-a-url?" + STATE,
    ):
        summary = describe_meta_http_target_for_audit(uri)
        assert CODE not in summary and STATE not in summary


def test_callback_and_security_modules_unmounted_from_sendro():
    source = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "instagram_oauth_http_security" not in source
    assert "instagram_oauth_callback_inbox" not in source
