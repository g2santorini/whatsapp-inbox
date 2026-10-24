"""Synthetic read-only Instagram account status tests: disposable SQLite only."""
import time
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import OAuth2PasswordBearer
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.instagram_account_status import (
    create_dormant_instagram_account_status_router,
)

SECRET = "ONLY-a-synthetic-GitHub-CI-JWT-SECRET"
NOW = int(time.time())
TOKEN_TO_NEVER_SHOW = "never-leak-this-synthetic-IG-access-token"
PROVIDER_TO_NEVER_SHOW = "1784140201222000"
HOST = "sendro-backend-staging.onrender.com"


def make_user(uid=7, name="tenant-owner", **kwargs):
    props = dict(id=uid, username=name, role="admin", disabled=False,
                 mfa_enabled=True, must_change_password=False,
                 mfa_setup_required=False, auth_version=1)
    props.update(kwargs)
    return SimpleNamespace(**props)


def signed(u, *, age=0, auth_version=None):
    return jwt.encode({
        "sub": u.username, "ver": u.auth_version if auth_version is None else auth_version,
        "mfa_verified_at": NOW - age, "exp": NOW + 1200,
    }, SECRET, algorithm="HS256")


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    with engine.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS public"))
        c.execute(text("""CREATE TABLE public.sendro_tenant_users (
            tenant_id INTEGER, user_id INTEGER, member_role TEXT,
            is_active BOOLEAN, PRIMARY KEY(tenant_id,user_id))"""))
        c.execute(text("""CREATE TABLE public.sendro_channel_accounts (
            id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL,
            platform TEXT, external_account_id TEXT, display_name TEXT,
            status TEXT)"""))
        c.execute(text("""CREATE TABLE public.sendro_instagram_token_vault (
            tenant_id INTEGER, channel_account_id INTEGER,
            provider_user_id TEXT, encrypted_token BLOB,
            issued_epoch INTEGER, expires_epoch INTEGER,
            revision INTEGER, PRIMARY KEY(tenant_id,channel_account_id))"""))
        c.execute(text("""INSERT INTO public.sendro_tenant_users VALUES
            (10,7,'owner',1),(20,8,'admin',1),
            (10,9,'viewer',1),(10,11,'admin',0)"""))
        c.execute(text("""INSERT INTO public.sendro_channel_accounts VALUES
            (31,10,'instagram',:provider,'@sunsetoiasailing','testing'),
            (32,10,'instagram','178414020100032','@second_ig','active'),
            (33,10,'instagram','178414020100033','@expired_ig','active'),
            (34,20,'instagram','178414020100034','@other-company','testing'),
            (35,10,'whatsapp','abc123','WhatsApp','active'),
            (36,10,'instagram','178414020100036','@disabled_ig','disabled'),
            (37,10,'instagram','178414020100037','@wrong-binding','testing')
        """), {"provider": PROVIDER_TO_NEVER_SHOW})
        c.execute(text("""INSERT INTO public.sendro_instagram_token_vault VALUES
            (10,31,:provider,:secret,:now,:future,1),
            (10,33,'178414020100033',:secret,:now,:past,1),
            (20,34,'178414020100034',:secret,:now,:future,1),
            (10,35,'abc123',:secret,:now,:future,1),
            (10,37,'other-wrong-identity',:secret,:now,:future,1)
        """), {"provider":PROVIDER_TO_NEVER_SHOW,
                "secret": TOKEN_TO_NEVER_SHOW.encode(),
                "now":NOW-100, "future":NOW+100000, "past":NOW-1})
    yield engine
    engine.dispose()


def make_client(engine, *, u=None, enabled=True):
    selected = u or make_user()
    factory = sessionmaker(bind=engine)

    def db_session():
        with factory() as session:
            yield session

    def current_user():
        # A synthetic stub only. The production route MUST inject the
        # real get_current_active_user dependency.
        return selected

    app = FastAPI()
    app.include_router(create_dormant_instagram_account_status_router(
        current_user_dependency=current_user,
        bearer_dependency=OAuth2PasswordBearer(tokenUrl="/token"),
        db_dependency=db_session,
        enabled=enabled,
        jwt_secret=SECRET, jwt_algorithm="HS256",
    ))
    return TestClient(app, base_url="https://" + HOST), selected


def fetch(client, user, tenant=10, *, age=0, ver=None, path=None, extra_headers=None):
    head = {"Authorization":"Bearer " + signed(user, age=age, auth_version=ver)}
    if extra_headers:
        head.update(extra_headers)
    return client.get(path or f"/channels/instagram/account-status?tenant_id={tenant}",
                      headers=head)


def test_owner_sees_only_own_ig_registry_and_metadata(db_engine):
    client,u=make_client(db_engine)
    resp=fetch(client,u)
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "private, no-store"
    data=resp.json()
    assert data["tenant_id"] == 10
    assert data["messaging_enabled"] is False
    assert data["meta_authorization_verified_now"] is False
    assert [r["channel_account_id"] for r in data["accounts"]] == [31,32,33,37]
    assert [r["credential_status"] for r in data["accounts"]] == [
        "stored_unverified","not_linked","expired","not_linked",
    ]
    assert data["accounts"][0]["display_name"] == "@sunsetoiasailing"
    assert data["accounts"][0]["expires_at_epoch"] > NOW
    assert data["accounts"][1]["expires_at_epoch"] is None
    assert data["accounts"][2]["expires_at_epoch"] < NOW
    assert data["accounts"][3]["expires_at_epoch"] is None
    forbidden = [TOKEN_TO_NEVER_SHOW, PROVIDER_TO_NEVER_SHOW, "encrypted_token",
                 "access_token", "authorization_code", "client_secret"]
    for secret in forbidden:
        assert secret not in resp.text
    assert all(set(item)=={
        "channel_account_id","display_name","registration_status",
        "credential_status","expires_at_epoch",
    } for item in data["accounts"])


def test_other_tenant_admin_cannot_read_sunset_even_by_guessing_id(db_engine):
    client,u=make_client(db_engine,u=make_user(8,"other-admin"))
    assert fetch(client,u,tenant=10).status_code==403
    own=fetch(client,u,tenant=20)
    assert own.status_code==200
    assert [row["channel_account_id"] for row in own.json()["accounts"]]==[34]
    assert "@sunsetoiasailing" not in own.text


def test_member_viewer_inactive_and_nonmember_blocked(db_engine):
    for u in [
        make_user(9,"viewer"),
        make_user(11,"inactive"),
        make_user(100,"unknown"),
        make_user(disabled=True),
        make_user(mfa_enabled=False),
        make_user(must_change_password=True),
        make_user(role="developer"),
    ]:
        client,_=make_client(db_engine,u=u)
        resp=fetch(client,u)
        assert resp.status_code==403 and TOKEN_TO_NEVER_SHOW not in resp.text


def test_recent_mfa_and_rotated_auth_version_enforced(db_engine):
    client,u=make_client(db_engine)
    assert fetch(client,u,age=700).status_code==403
    assert fetch(client,u,ver=2).status_code==403
    assert fetch(client,u).status_code==200


def test_default_disabled_has_no_db_access(db_engine):
    client,u=make_client(db_engine,enabled=False)
    with db_engine.begin() as conn:
        conn.execute(text("DROP TABLE public.sendro_instagram_token_vault"))
    resp=fetch(client,u)
    assert resp.status_code==503
    assert resp.json()["detail"]=="Instagram account status unavailable"


def test_enabled_but_missing_vault_table_fails_without_sql_leak(db_engine):
    client,u=make_client(db_engine,enabled=True)
    with db_engine.begin() as conn:
        conn.execute(text("DROP TABLE public.sendro_instagram_token_vault"))
    resp=fetch(client,u)
    assert resp.status_code==503
    assert "sendro_instagram_token_vault" not in resp.text
    assert PROVIDER_TO_NEVER_SHOW not in resp.text


def test_forged_host_or_unexpected_query_is_rejected(db_engine):
    client,u=make_client(db_engine)
    for path,extra in [
        ("/channels/instagram/account-status?tenant_id=10", {"Host":"evil.example"}),
        ("/channels/instagram/account-status?tenant_id=10&foo=1", None),
        ("/channels/instagram/account-status?tenant_id=10&tenant_id=20", None),
    ]:
        resp=fetch(client,u,path=path,extra_headers=extra)
        assert resp.status_code in {403,422}
        assert TOKEN_TO_NEVER_SHOW not in resp.text


def test_no_bearer_is_denied_by_dependency(db_engine):
    client,_=make_client(db_engine)
    resp=client.get("/channels/instagram/account-status?tenant_id=10")
    assert resp.status_code==401


def test_unmounted_in_sendro_main():
    from pathlib import Path
    main=(Path(__file__).parents[1]/"app"/"main.py").read_text(encoding="utf-8")
    assert "instagram_account_status" not in main
