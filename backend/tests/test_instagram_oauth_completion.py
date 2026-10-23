"""Synthetic Instagram OAuth create -> callback -> one-time admin claim tests.

No real database/Render/Meta interactions and no plaintext token storage.
"""
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend.app.instagram_oauth_state import (
    issue_instagram_oauth, InstagramOAuthDenied,
)
from backend.app.instagram_oauth_callback_inbox import capture_instagram_authorization_code
from backend.app.instagram_oauth_completion import claim_captured_instagram_code

SECRET = "offline-synthetic-jwt-key-not-real"
KEY = Fernet.generate_key().decode("ascii")
CODE = "synthetic_code_A123"
APP_ID = "123456789"
NOW = int(time.time())


def _user(user_id=7, username="fixture-admin", role="admin", active=True, version=1):
    return SimpleNamespace(
        id=user_id, username=username, role=role,
        disabled=not active, auth_version=version,
        must_change_password=False, mfa_setup_required=False, mfa_enabled=True,
    )


def _jwt(user, *, fresh=True, version=None):
    return jwt.encode({
        "sub": user.username,
        "ver": user.auth_version if version is None else version,
        "mfa_verified_at": NOW if fresh else NOW - 700,
        "exp": NOW + 3600,
    }, SECRET, algorithm="HS256")


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        conn.execute(text("ATTACH DATABASE ':memory:' AS public"))
        conn.execute(text("""
            CREATE TABLE public.sendro_tenant_users (
                tenant_id INTEGER, user_id INTEGER,
                member_role TEXT NOT NULL, is_active BOOLEAN NOT NULL,
                PRIMARY KEY(tenant_id,user_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE public.sendro_instagram_oauth_challenges (
                state_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL, tenant_id INTEGER NOT NULL,
                created_epoch INTEGER NOT NULL, expires_epoch INTEGER NOT NULL,
                encrypted_authorization_code BLOB,
                received_epoch INTEGER
            )
        """))
        for tenant, uid, role, active in (
            (10, 7, "owner", True),
            (20, 8, "admin", True),
            (10, 9, "viewer", True),
        ):
            conn.execute(text("""
                INSERT INTO public.sendro_tenant_users
                (tenant_id,user_id,member_role,is_active)
                VALUES (:tenant,:uid,:role,:active)
            """), dict(tenant=tenant, uid=uid, role=role, active=active))
    yield engine
    engine.dispose()


def _start(engine, user=None, tenant_id=10):
    user = user or _user()
    with engine.begin() as conn:
        start = issue_instagram_oauth(
            conn, user=user, tenant_id=tenant_id,
            bearer_token=_jwt(user), jwt_secret=SECRET, jwt_algorithm="HS256",
            instagram_app_id=APP_ID, now_epoch=NOW,
        )
    return parse_qs(urlsplit(start.authorization_url).query)["state"][0]


def _capture(engine, state, code=CODE):
    with engine.begin() as conn:
        capture_instagram_authorization_code(
            conn, state=state, code=code, encryption_key=KEY, now_epoch=NOW + 1,
        )


def _claim(engine, state, *, user=None, tenant_id=10, token=None, key=KEY, now=NOW + 2):
    user = user or _user()
    with engine.begin() as conn:
        return claim_captured_instagram_code(
            conn, state=state, user=user, tenant_id=tenant_id,
            bearer_token=token or _jwt(user),
            jwt_secret=SECRET, jwt_algorithm="HS256",
            encryption_key=key, now_epoch=now,
        )


def test_full_synthetic_flow_claims_code_once_and_redacts_repr(engine):
    state = _start(engine)
    _capture(engine, state)
    with engine.connect() as conn:
        record = conn.execute(text("""
            SELECT encrypted_authorization_code FROM public.sendro_instagram_oauth_challenges
        """)).scalar_one()
    assert isinstance(record, bytes) and CODE.encode() not in record
    claimed = _claim(engine, state)
    assert claimed.authorization_code == CODE
    assert claimed.tenant_id == 10 and claimed.user_id == 7
    assert CODE not in repr(claimed) and CODE not in str(claimed)
    with engine.connect() as conn:
        assert conn.execute(text("""
            SELECT COUNT(*) FROM public.sendro_instagram_oauth_challenges
        """)).scalar_one() == 0
    with pytest.raises(InstagramOAuthDenied):
        _claim(engine, state)


def test_not_yet_callback_received_cannot_be_consumed(engine):
    state = _start(engine)
    with pytest.raises(InstagramOAuthDenied):
        _claim(engine, state)
    _capture(engine, state)
    assert _claim(engine, state).authorization_code == CODE


def test_cross_tenant_user_and_viewer_fail_without_destroying_code(engine):
    state = _start(engine)
    _capture(engine, state)
    with pytest.raises(InstagramOAuthDenied):
        _claim(engine, state, user=_user(8, "other-admin"), tenant_id=20)
    with pytest.raises(InstagramOAuthDenied):
        _claim(engine, state, user=_user(9, "viewer", role="viewer"))
    with pytest.raises(InstagramOAuthDenied):
        _claim(engine, state, tenant_id=20)
    assert _claim(engine, state).authorization_code == CODE


def test_revoked_membership_and_rotated_auth_version_fail_closed(engine):
    state = _start(engine)
    _capture(engine, state)
    owner = _user()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE public.sendro_tenant_users SET is_active=0
            WHERE tenant_id=10 AND user_id=7
        """))
    with pytest.raises(InstagramOAuthDenied):
        _claim(engine, state)
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE public.sendro_tenant_users SET is_active=1
            WHERE tenant_id=10 AND user_id=7
        """))
    rotated = _user(version=2)
    with pytest.raises(InstagramOAuthDenied):
        _claim(engine, state, user=rotated, token=_jwt(owner))
    assert _claim(engine, state).authorization_code == CODE


def test_stale_mfa_and_expiry_fail_closed(engine):
    state = _start(engine)
    _capture(engine, state)
    owner = _user()
    with pytest.raises(InstagramOAuthDenied):
        _claim(engine, state, token=_jwt(owner, fresh=False))
    with pytest.raises(InstagramOAuthDenied):
        _claim(engine, state, now=NOW + 301)


def test_wrong_encryption_key_fails_without_exposing_code(engine):
    state = _start(engine)
    _capture(engine, state)
    with pytest.raises(InstagramOAuthDenied) as exc:
        _claim(engine, state, key=Fernet.generate_key().decode("ascii"))
    assert CODE not in str(exc.value)


def test_module_remains_unmounted_from_sendro_main():
    from pathlib import Path
    root = Path(__file__).parents[1] / "app"
    main_source = (root / "main.py").read_text(encoding="utf-8")
    assert "instagram_oauth_completion" not in main_source
    assert "instagram_oauth_callback_inbox" not in main_source
