"""Synthetic route-mount and fail-closed tests. No Render/Meta/DB I/O."""
from fastapi import FastAPI
from cryptography.fernet import Fernet

from app.instagram_staging_wiring import (
    STAGING_HOST, STAGING_SERVICE_ID,
    is_exact_staging_service, mount_instagram_staging_wiring,
)


def _staging(monkeypatch):
    monkeypatch.setenv("RENDER_SERVICE_ID", STAGING_SERVICE_ID)
    monkeypatch.setenv("RENDER_GIT_BRANCH", "dev")
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", STAGING_HOST)


def _app():
    app = FastAPI()
    mount_instagram_staging_wiring(
        app,
        current_user_dependency=lambda: None,
        bearer_dependency=lambda: "",
        transaction=lambda: None,
        jwt_secret="synthetic-test-only",
        jwt_algorithm="HS256",
    )
    return app


def _paths(app):
    return {getattr(route, "path", "") for route in app.routes}


def test_production_does_not_mount_any_route(monkeypatch):
    _staging(monkeypatch)
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-production")
    monkeypatch.setenv("SENDRO_IG_OAUTH_ENABLED", "true")
    for key in [
        "SENDRO_IG_INGRESS_QUERY_REDACTION_VERIFIED",
        "SENDRO_IG_ASGI_LOG_REDACTION_VERIFIED",
        "SENDRO_IG_EGRESS_LOG_REDACTION_VERIFIED",
        "SENDRO_IG_TELEMETRY_REDACTION_VERIFIED",
        "SENDRO_IG_OAUTH_RELEASE_AUTHORIZED",
    ]:
        monkeypatch.setenv(key, "true")
    assert not is_exact_staging_service()
    assert all("instagram" not in path for path in _paths(_app()))


def test_staging_mounts_only_readonly_status_by_default(monkeypatch):
    _staging(monkeypatch)
    monkeypatch.delenv("SENDRO_IG_OAUTH_ENABLED", raising=False)
    paths = _paths(_app())
    assert "/channels/instagram/account-status" in paths
    assert "/channels/instagram/oauth/start" not in paths
    assert "/channels/instagram/oauth/complete" not in paths
    assert "/channels/instagram/oauth/callback" not in paths


def test_oauth_flag_alone_cannot_activate_routes(monkeypatch):
    _staging(monkeypatch)
    monkeypatch.setenv("SENDRO_IG_OAUTH_ENABLED", "true")
    paths = _paths(_app())
    assert "/channels/instagram/account-status" in paths
    assert not any("/channels/instagram/oauth/" in item for item in paths)


def test_missing_or_invalid_keys_fail_closed(monkeypatch):
    _staging(monkeypatch)
    monkeypatch.setenv("SENDRO_IG_OAUTH_ENABLED", "true")
    for name in [
        "SENDRO_IG_INGRESS_QUERY_REDACTION_VERIFIED",
        "SENDRO_IG_ASGI_LOG_REDACTION_VERIFIED",
        "SENDRO_IG_EGRESS_LOG_REDACTION_VERIFIED",
        "SENDRO_IG_TELEMETRY_REDACTION_VERIFIED",
        "SENDRO_IG_OAUTH_RELEASE_AUTHORIZED",
    ]:
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("INSTAGRAM_APP_ID", "2862892724096609")
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "fake-unit-test-secret")
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SENDRO_IG_CALLBACK_FERNET_KEY", key)
    monkeypatch.setenv("SENDRO_IG_VAULT_FERNET_KEY", key)
    assert "/channels/instagram/oauth/start" not in _paths(_app())
    monkeypatch.setenv("SENDRO_IG_VAULT_FERNET_KEY", "not-a-fernet-key")
    assert "/channels/instagram/oauth/start" not in _paths(_app())


def test_valid_staging_gates_mount_only_three_expected_routes(monkeypatch):
    _staging(monkeypatch)
    monkeypatch.setenv("SENDRO_IG_OAUTH_ENABLED", "true")
    for name in [
        "SENDRO_IG_INGRESS_QUERY_REDACTION_VERIFIED",
        "SENDRO_IG_ASGI_LOG_REDACTION_VERIFIED",
        "SENDRO_IG_EGRESS_LOG_REDACTION_VERIFIED",
        "SENDRO_IG_TELEMETRY_REDACTION_VERIFIED",
        "SENDRO_IG_OAUTH_RELEASE_AUTHORIZED",
    ]:
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("INSTAGRAM_APP_ID", "2862892724096609")
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "fake-unit-test-secret")
    monkeypatch.setenv("SENDRO_IG_CALLBACK_FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("SENDRO_IG_VAULT_FERNET_KEY", Fernet.generate_key().decode())
    paths = _paths(_app())
    assert "/channels/instagram/account-status" in paths
    assert "/channels/instagram/oauth/start" in paths
    assert "/channels/instagram/oauth/complete" in paths
    assert "/channels/instagram/oauth/callback" in paths
    assert not any("whatsapp" in route for route in paths)
