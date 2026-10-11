"""Regression checks: project-only accounts must not reach the Inbox API."""
import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request

os.environ.setdefault("DATABASE_URL", "sqlite:///./sendro_project_route_guard_test.sqlite3")
os.environ.setdefault("SECRET_KEY", "test-only-ci-secret-for-project-manager-checks")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test-not-a-real-whatsapp-token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123456789")

from backend.app.main import app, get_current_active_user  # noqa: E402


def request_for(path):
    return Request({
        "type": "http",
        "http_version": "1.1",
        "scheme": "https",
        "server": ("sendro.example.test", 443),
        "client": ("127.0.0.1", 12345),
        "method": "GET",
        "root_path": "",
        "path": path,
        "headers": [],
        "query_string": b"",
    })


def test_project_only_guards_allow_only_project_api():
    for role in ("developer", "project_viewer"):
        user = SimpleNamespace(
            role=role, disabled=False,
            must_change_password=False, mfa_setup_required=False,
        )
        for path in ("/conversations/", "/messages/12/media", "/users/", "/quick-replies/", "/template-reports/"):
            with pytest.raises(HTTPException) as error:
                asyncio.run(get_current_active_user(request_for(path), user))
            assert error.value.status_code == 403, (role, path)
        assert asyncio.run(
            get_current_active_user(request_for("/projects/42"), user)
        ) is user

    admin = SimpleNamespace(
        role="admin", disabled=False,
        must_change_password=False, mfa_setup_required=False,
    )
    assert asyncio.run(
        get_current_active_user(request_for("/conversations/"), admin)
    ) is admin


def test_messaging_api_routes_use_active_user_guard():
    """Fail if future routes accidentally bypass the enforced project-only guard."""
    protected_prefixes = (
        "/conversations", "/messages", "/users/", "/quick-repl", "/template",
        "/reports", "/contacts",
    )
    allowed_self_service_prefixes = (
        "/users/me/", "/users/me/mfa/", "/users/me/password",
    )
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith(protected_prefixes):
            continue
        if route.path.startswith(allowed_self_service_prefixes):
            continue
        deps = {dependency.call for dependency in route.dependant.dependencies}
        assert get_current_active_user in deps, (
            "Sensitive API missing active-user role guard: " + route.path
        )
