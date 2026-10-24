"""Disposable SQLite token vault tests. No customer, Meta or Render data."""
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend.app import instagram_token_vault as vault

SECRET = "synthetic-jwt-signing-key-NOT-a-production-secret"
KEY = Fernet.generate_key().decode("ascii")
TOKEN1 = "synthetic-long-IG-token-aaa"
TOKEN2 = "synthetic-long-IG-token-bbb"
PROVIDER_ID = "17841402010000000"
NOW = int(time.time())
LIFETIME = 60 * 86400


def user(uid=7, username="tenant-owner", **kw):
    defaults = dict(id=uid, username=username, role="admin", disabled=False,
                    must_change_password=False, mfa_setup_required=False,
                    mfa_enabled=True, auth_version=1)
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def auth(user_obj, *, stale=False, auth_version=None, has_mfa=True, at=None):
    issued = NOW if at is None else at
    claims = {"sub": user_obj.username,
              "ver": user_obj.auth_version if auth_version is None else auth_version,
              "exp": issued + 3600}
    if has_mfa:
        claims["mfa_verified_at"] = issued - (700 if stale else 0)
    return jwt.encode(claims, SECRET, algorithm="HS256")


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with engine.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS public"))
        c.execute(text("""CREATE TABLE public.sendro_tenant_users (
            tenant_id INTEGER, user_id INTEGER, member_role TEXT, is_active BOOLEAN,
            PRIMARY KEY (tenant_id,user_id))"""))
        c.execute(text("""CREATE TABLE public.sendro_channel_accounts (
            id INTEGER PRIMARY KEY, tenant_id INTEGER, platform TEXT,
            external_account_id TEXT, status TEXT)"""))
        c.execute(text("""CREATE TABLE public.sendro_instagram_token_vault (
            tenant_id INTEGER NOT NULL, channel_account_id INTEGER NOT NULL,
            provider_user_id TEXT NOT NULL, encrypted_token BLOB NOT NULL,
            issued_epoch INTEGER NOT NULL, expires_epoch INTEGER NOT NULL,
            revision INTEGER NOT NULL, PRIMARY KEY(tenant_id,channel_account_id))"""))
        for t,u,role,active in [(10,7,"owner",1),(20,8,"admin",1),
                                (10,9,"viewer",1)]:
            c.execute(text("""INSERT INTO public.sendro_tenant_users VALUES
                (:t,:u,:r,:a)"""),dict(t=t,u=u,r=role,a=active))
        for a,t,p,x,s in [(31,10,"instagram",PROVIDER_ID,"testing"),
                          (32,20,"instagram","987654321","active"),
                          (33,10,"whatsapp","123456789","active")]:
            c.execute(text("INSERT INTO public.sendro_channel_accounts VALUES (:a,:t,:p,:x,:s)"),
                      dict(a=a,t=t,p=p,x=x,s=s))
    yield engine
    engine.dispose()


def args(u=None, *, tenant=10, account=31, provider=PROVIDER_ID, key=KEY, now=NOW, **kw):
    u = u or user()
    return dict(user=u, tenant_id=tenant, channel_account_id=account,
                provider_user_id=provider, bearer_token=auth(u, at=now),
                jwt_secret=SECRET, jwt_algorithm="HS256",
                encryption_key=key, now_epoch=now, **kw)


def enroll(engine, u=None, **kw):
    with engine.begin() as c:
        return vault.enroll_new_long_lived_token(
            c, **args(u, **kw), long_lived_token=TOKEN1,
            expires_in_seconds=LIFETIME)


def load(engine, u=None, **kw):
    with engine.begin() as c:
        return vault.load_long_lived_token_for_admin(c, **args(u, **kw))


def rotate(engine, *, revision=1, now=NOW + 86401, token=TOKEN2, **kw):
    with engine.begin() as c:
        return vault.rotate_refreshed_long_lived_token(
            c, **args(now=now, **kw), old_revision=revision,
            new_long_lived_token=token, new_expires_in_seconds=LIFETIME)


def test_initial_credential_is_encrypted_bound_and_redacted(engine):
    assert enroll(engine) == {"connected": True, "expires_at_epoch": NOW + LIFETIME, "revision": 1}
    with engine.connect() as c:
        ciphertext = c.execute(text("SELECT encrypted_token FROM public.sendro_instagram_token_vault")).scalar_one()
    assert TOKEN1.encode() not in ciphertext
    held = load(engine)
    assert held.access_token == TOKEN1
    assert held.instagram_user_id == PROVIDER_ID
    assert TOKEN1 not in repr(held) and TOKEN1 not in str(held)


def test_duplicate_connect_is_denied_without_overwrite(engine):
    enroll(engine)
    with pytest.raises(vault.InstagramTokenVaultDenied, match="already has"):
        enroll(engine)
    assert load(engine).access_token == TOKEN1


@pytest.mark.parametrize("account,provider,tenant", [
    (33, "123456789", 10),
    (31, "wrong", 10), (32, "987654321", 10),
    (31, PROVIDER_ID, 20),
])
def test_platform_account_or_tenant_mismatch_denied(engine, account, provider, tenant):
    with pytest.raises(vault.InstagramTokenVaultDenied):
        enroll(engine, account=account, provider=provider, tenant=tenant)


def test_viewer_inactive_member_and_unauthorized_user_denied(engine):
    for u in [user(9, "viewer"), user(100, "stranger"), user(disabled=True),
              user(role="developer"), user(mfa_enabled=False)]:
        with pytest.raises(vault.InstagramTokenVaultDenied):
            enroll(engine, u)
    with engine.begin() as c:
        c.execute(text("UPDATE public.sendro_tenant_users SET is_active=0 WHERE tenant_id=10 AND user_id=7"))
    with pytest.raises(vault.InstagramTokenVaultDenied):
        enroll(engine)


def test_mfa_stale_missing_and_auth_version_rotation_denied(engine):
    u = user()
    for tok in [auth(u, stale=True), auth(u, has_mfa=False), auth(u, auth_version=2)]:
        with pytest.raises(vault.InstagramTokenVaultDenied):
            with engine.begin() as c:
                vault.enroll_new_long_lived_token(c,
                    **{**args(), "bearer_token": tok},
                    long_lived_token=TOKEN1, expires_in_seconds=LIFETIME)


def test_wrong_key_and_swapped_ciphertext_fail_closed(engine):
    enroll(engine)
    with pytest.raises(vault.InstagramTokenVaultDenied, match="decryption failed"):
        load(engine, key=Fernet.generate_key().decode("ascii"))
    fake = vault._encrypt(Fernet(KEY.encode()), tenant_id=20,
                          account_id=32, provider_id="987654321", token=TOKEN2)
    with engine.begin() as c:
        c.execute(text("UPDATE public.sendro_instagram_token_vault SET encrypted_token=:v"), {"v":fake})
    with pytest.raises(vault.InstagramTokenVaultDenied, match="decryption failed"):
        load(engine)


def test_lifetime_validation_and_bool_rejection(engine):
    for ttl in [True, 30, -1, 0, 63 * 86400]:
        with pytest.raises(vault.InstagramTokenVaultDenied):
            with engine.begin() as c:
                vault.enroll_new_long_lived_token(c, **args(),
                      long_lived_token=TOKEN1, expires_in_seconds=ttl)
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM public.sendro_instagram_token_vault")).scalar_one() == 0


def test_early_refresh_denied_and_valid_cas_rotation(engine):
    enroll(engine)
    with pytest.raises(vault.InstagramTokenVaultDenied, match="not eligible"):
        rotate(engine, now=NOW + 100)
    assert rotate(engine)["revision"] == 2
    assert load(engine, now=NOW + 86401).access_token == TOKEN2
    with pytest.raises(vault.InstagramTokenVaultDenied, match="superseded"):
        rotate(engine, revision=1, now=NOW + 2 * 86400)


def test_expired_token_not_available_for_refresh(engine):
    enroll(engine)
    with pytest.raises(vault.InstagramTokenVaultDenied, match="expired"):
        load(engine, now=NOW + LIFETIME + 1)
    with pytest.raises(vault.InstagramTokenVaultDenied):
        rotate(engine, now=NOW + LIFETIME + 1)


def test_disconnect_clears_local_token_without_claiming_meta_revocation(engine):
    enroll(engine)
    with engine.begin() as c:
        assert vault.disconnect_instagram_credential(c,
            **{k:v for k,v in args().items() if k!="encryption_key"}) == {
                "locally_disconnected": True,"meta_authorization_revoked":False}
    with pytest.raises(vault.InstagramTokenVaultDenied):
        load(engine)
    assert enroll(engine)["connected"]


def test_dormant_code_not_wired_into_sendro_main():
    source = (Path(__file__).parents[1]/"app"/"main.py").read_text(encoding="utf-8")
    assert "instagram_token_vault" not in source
