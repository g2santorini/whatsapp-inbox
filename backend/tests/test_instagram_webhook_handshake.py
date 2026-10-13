"""Isolated tests for Instagram callback verification and message safety."""
import hashlib
import hmac

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.instagram_webhook import router


app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_instagram_verify_missing_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN", raising=False)
    response = client.get(
        "/webhook/instagram",
        params={"hub.mode": "subscribe", "hub.challenge": "31337", "hub.verify_token": "guess"},
    )
    assert response.status_code == 503


def test_instagram_verification_returns_exact_challenge(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "ig-test-only-token")
    response = client.get(
        "/webhook/instagram",
        params={"hub.mode": "subscribe", "hub.challenge": "challenge-123", "hub.verify_token": "ig-test-only-token"},
    )
    assert response.status_code == 200
    assert response.text == "challenge-123"
    assert response.headers["content-type"].startswith("text/plain")


def test_instagram_verify_rejects_bad_token_or_mode(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "ig-test-only-token")
    for params in (
        {"hub.mode": "subscribe", "hub.challenge": "123", "hub.verify_token": "bad"},
        {"hub.mode": "not-subscribe", "hub.challenge": "123", "hub.verify_token": "ig-test-only-token"},
        {"hub.mode": "subscribe", "hub.challenge": "", "hub.verify_token": "ig-test-only-token"},
    ):
        response = client.get("/webhook/instagram", params=params)
        assert response.status_code == 403


def test_instagram_post_rejects_missing_secret(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_APP_SECRET", raising=False)
    assert client.post("/webhook/instagram", json={"object": "instagram"}).status_code == 503


def test_instagram_post_rejects_unsigned_and_bad_signature(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "ig-test-secret")
    payload = b'{"object":"instagram","entry":[]}'
    assert client.post("/webhook/instagram", content=payload).status_code == 403
    assert client.post(
        "/webhook/instagram", content=payload,
        headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
    ).status_code == 403


def test_instagram_signed_post_must_not_be_silently_acknowledged(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "ig-test-secret")
    payload = b'{"object":"instagram","entry":[{"id":"test"}]}'
    digest = hmac.new(b"ig-test-secret", payload, hashlib.sha256).hexdigest()
    response = client.post(
        "/webhook/instagram", content=payload,
        headers={"X-Hub-Signature-256": "sha256=" + digest},
    )
    assert response.status_code == 503
    assert "not enabled" in response.json()["detail"]
