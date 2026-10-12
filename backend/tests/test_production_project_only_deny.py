"""Production must reject project-only identities, even with a valid JWT."""
import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "sqlite:///./unused_production_role_test.sqlite")
os.environ.setdefault("SECRET_KEY", "test-only-production-role-guard-secret")

from backend.app import main


@pytest.mark.parametrize("restricted_role", ["developer", "project_viewer"])
def test_production_denies_project_only_roles_with_valid_token(monkeypatch, restricted_role):
    user = SimpleNamespace(username="john", role=restricted_role, auth_version=1)
    monkeypatch.setattr(main, "get_user", lambda db, username: user)
    token = main.create_access_token({"sub": "john", "ver": 1})
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.get_current_user(token, None))
    assert error.value.status_code == 403


@pytest.mark.parametrize("allowed_role", ["admin", "power_user", "user"])
def test_production_keeps_existing_message_roles(monkeypatch, allowed_role):
    user = SimpleNamespace(username="existing", role=allowed_role, auth_version=1)
    monkeypatch.setattr(main, "get_user", lambda db, username: user)
    token = main.create_access_token({"sub": "existing", "ver": 1})
    assert asyncio.run(main.get_current_user(token, None)) is user
