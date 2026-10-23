"""Synthetic, disposable SQLite checks; never access Render, Meta or real users."""
import hashlib
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend.app import instagram_oauth_state as flow

SECRET = "synthetic-ig-state-ci-key-NEVER-a-real-token"
ALGORITHM = "HS256"
APP_ID = "123456789012345"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with engine.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS public"))
        c.execute(text("""
            CREATE TABLE public.sendro_tenant_users (
                tenant_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                member_role TEXT NOT NULL, is_active BOOLEAN NOT NULL,
                PRIMARY KEY (tenant_id, user_id)
            )
        """))
        c.execute(text("""
            CREATE TABLE public.sendro_instagram_oauth_challenges (
                state_hash TEXT PRIMARY KEY, tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL, created_epoch INTEGER NOT NULL,
                expires_epoch INTEGER NOT NULL
            )
        """))
        for tenant_id, user_id, role, active in [
            (10, 7, "owner", 1), (20, 8, "admin", 1),
            (10, 9, "viewer", 1), (20, 7, "owner", 0),
        ]:
            c.execute(text("""
                INSERT INTO public.sendro_tenant_users
                  (tenant_id, user_id, member_role, is_active)
                VALUES (:t, :u, :r, :a)
            """), {"t": tenant_id, "u": user_id, "r": role, "a": active})
    yield engine
    engine.dispose()


def make_user(user_id=7, **overrides):
    fields = dict(id=user_id, username="testowner", role="admin",
                  disabled=False, must_change_password=False,
                  mfa_setup_required=False, mfa_enabled=True, auth_version=1)
    fields.update(overrides)
    return SimpleNamespace(**fields)


def make_jwt(user, *, epoch=None, mfa_age=0, version=None, mfa=True):
    now = int(time.time()) if epoch is None else epoch
    payload = {"sub": user.username, "ver": user.auth_version if version is None else version,
               "exp": now + 1200}
    if mfa:
        payload["mfa_verified_at"] = now - mfa_age
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def begin(engine, user, tenant_id=10, *, epoch=None, token=None):
    with engine.begin() as conn:
        return flow.issue_instagram_oauth(
            conn, user=user, tenant_id=tenant_id,
            bearer_token=token or make_jwt(user, epoch=epoch),
            jwt_secret=SECRET, jwt_algorithm=ALGORITHM,
            instagram_app_id=APP_ID, now_epoch=epoch,
        )


def consume(engine, state, user, tenant_id=10, *, epoch=None, token=None):
    with engine.begin() as conn:
        return flow.consume_instagram_oauth(
            conn, state=state, user=user, tenant_id=tenant_id,
            bearer_token=token or make_jwt(user, epoch=epoch),
            jwt_secret=SECRET, jwt_algorithm=ALGORITHM, now_epoch=epoch,
        )


def get_state(out):
    return parse_qs(urlsplit(out.authorization_url).query)["state"][0]


def test_valid_admin_start_and_single_use_redeem(db):
    owner = make_user()
    created = begin(db, owner)
    nonce = get_state(created)
    assert len(nonce) >= 32
    assert "instagram_business_basic" in created.authorization_url
    with db.connect() as c:
        row = c.execute(text("""
            SELECT state_hash, tenant_id, user_id
              FROM public.sendro_instagram_oauth_challenges
        """)).mappings().one()
    assert row["tenant_id"] == 10 and row["user_id"] == 7
    assert nonce not in row["state_hash"]
    assert len(row["state_hash"]) == 64
    consumed = consume(db, nonce, owner)
    assert consumed.tenant_id == 10 and consumed.user_id == 7
    with pytest.raises(flow.InstagramOAuthDenied, match="already used"):
        consume(db, nonce, owner)


def test_cross_tenant_and_cross_user_do_not_consume(db):
    owner = make_user()
    nonce = get_state(begin(db, owner))
    with pytest.raises(flow.InstagramOAuthDenied):
        consume(db, nonce, make_user(user_id=8, username="other"), tenant_id=20)
    with pytest.raises(flow.InstagramOAuthDenied):
        consume(db, nonce, owner, tenant_id=20)
    assert consume(db, nonce, owner).tenant_id == 10


@pytest.mark.parametrize("role", ["viewer", "operator", "random", ""])
def test_non_admin_membership_rejected_before_insert(db, role):
    with db.begin() as conn:
        conn.execute(text("""
            UPDATE public.sendro_tenant_users SET member_role = :r
             WHERE tenant_id = 10 AND user_id = 7
        """), {"r": role})
    with pytest.raises(flow.InstagramOAuthDenied):
        begin(db, make_user())
    with db.connect() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM public.sendro_instagram_oauth_challenges"
        )).scalar_one() == 0


def test_inactive_membership_and_revocation_fail_closed(db):
    owner = make_user()
    nonce = get_state(begin(db, owner))
    with db.begin() as c:
        c.execute(text("""
            UPDATE public.sendro_tenant_users SET is_active = 0
             WHERE tenant_id = 10 AND user_id = 7
        """))
    with pytest.raises(flow.InstagramOAuthDenied):
        consume(db, nonce, owner)
    with pytest.raises(flow.InstagramOAuthDenied):
        begin(db, owner)


def test_missing_or_old_mfa_is_rejected(db):
    user = make_user()
    with pytest.raises(flow.InstagramOAuthDenied, match="Fresh authenticator"):
        begin(db, user, token=make_jwt(user, mfa=False))
    with pytest.raises(flow.InstagramOAuthDenied, match="Fresh authenticator"):
        begin(db, user, token=make_jwt(user, mfa_age=601))


@pytest.mark.parametrize("mutate", [
    {"disabled": True}, {"must_change_password": True},
    {"mfa_setup_required": True}, {"role": "developer"},
    {"role": "project_viewer"}, {"mfa_enabled": False},
])
def test_ineligible_sendro_identity_is_denied(db, mutate):
    user = make_user(**mutate)
    with pytest.raises(flow.InstagramOAuthDenied):
        begin(db, user)


def test_auth_version_rotated_invalidates_old_session(db):
    user = make_user()
    old_token = make_jwt(user)
    user.auth_version = 2
    with pytest.raises(flow.InstagramOAuthDenied):
        begin(db, user, token=old_token)


def test_bad_state_does_not_consume_real_state(db):
    user = make_user()
    nonce = get_state(begin(db, user))
    with pytest.raises(flow.InstagramOAuthDenied):
        consume(db, nonce + "x", user)
    with pytest.raises(flow.InstagramOAuthDenied):
        consume(db, "not-valid-$", user)
    assert consume(db, nonce, user).user_id == 7


def test_expired_nonce_fails_even_with_new_mfa(db):
    user = make_user()
    t = int(time.time())
    nonce = get_state(begin(db, user, epoch=t))
    with pytest.raises(flow.InstagramOAuthDenied, match="expired"):
        consume(db, nonce, user, epoch=t + 301)


def test_state_module_is_not_routed_or_imported_by_main(db):
    from pathlib import Path
    source = (Path(__file__).parents[1] / "app" / "main.py").read_text()
    assert "instagram_oauth_state" not in source
    assert "include_router(instagram_oauth" not in source
