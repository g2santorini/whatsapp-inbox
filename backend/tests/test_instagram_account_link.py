"""Synthetic Instagram claim -> Meta subject verification -> encrypted vault.

No external calls, Render credentials, real customer IDs, or production DB.
"""
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend.app.instagram_oauth_completion import ClaimedInstagramCode
from backend.app.instagram_account_link import (
    InstagramAccountLinkDenied, VerifiedInstagramLink,
    prepare_verified_instagram_link, save_verified_instagram_link,
)

USER_ID = "17841402010000000"
OTHER_ID = "17841402019999999"
APP_ID = "123456789"
APP_SECRET = "fake-server-secret-not-real"
SHORT_TOKEN = "fake-short-access-token-value"
LONG_TOKEN = "fake-long-access-token-value"
CODE = "fake-one-time-auth-code-value"
KEY = Fernet.generate_key().decode("ascii")
NOW = int(time.time())
JWT_SECRET = "fake-signature-only-for-isolated-tests"


class FakeResult:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class FakeMeta:
    def __init__(self, *, short_id=USER_ID, short_profile_id=USER_ID,
                 long_profile_id=USER_ID, account_type="BUSINESS",
                 long_account_type=None, long_status=200):
        self.short_id = short_id
        self.short_profile_id = short_profile_id
        self.long_profile_id = long_profile_id
        self.account_type = account_type
        self.long_account_type = (account_type if long_account_type is None else long_account_type)
        self.long_status = long_status
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        assert url == "https://api.instagram.com/oauth/access_token"
        assert kwargs["allow_redirects"] is False
        assert kwargs["data"]["client_secret"] == APP_SECRET
        return FakeResult({"access_token": SHORT_TOKEN, "user_id": self.short_id})

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        assert kwargs["allow_redirects"] is False
        if url == "https://graph.instagram.com/access_token":
            assert kwargs["params"]["grant_type"] == "ig_exchange_token"
            assert kwargs["params"]["client_secret"] == APP_SECRET
            assert kwargs["params"]["access_token"] == SHORT_TOKEN
            return FakeResult({"access_token": LONG_TOKEN, "token_type": "bearer",
                               "expires_in": 60 * 86400}, self.long_status)
        assert url == "https://graph.instagram.com/me"
        profile_number = sum(1 for c in self.calls if c[1] == "https://graph.instagram.com/me")
        profile_id = self.short_profile_id if profile_number == 1 else self.long_profile_id
        profile_type = self.account_type if profile_number == 1 else self.long_account_type
        assert kwargs["headers"]["Authorization"] == (
            "Bearer " + (SHORT_TOKEN if profile_number == 1 else LONG_TOKEN))
        return FakeResult({"user_id": profile_id, "username": "fake_sailing",
                           "account_type": profile_type})


def _claim(tenant_id=10, user_id=7):
    return ClaimedInstagramCode(tenant_id=tenant_id,
                                user_id=user_id, authorization_code=CODE)


def _prepared(fake=None, claim=None):
    return prepare_verified_instagram_link(
        claimed_code=claim or _claim(), instagram_app_id=APP_ID,
        instagram_app_secret=APP_SECRET, session=fake or FakeMeta())


def _user(user_id=7, username="synthetic-owner", **overrides):
    props=dict(id=user_id, username=username, role="admin", disabled=False,
               auth_version=1, mfa_enabled=True, must_change_password=False,
               mfa_setup_required=False)
    props.update(overrides)
    return SimpleNamespace(**props)


def _token(u, *, stale_mfa=False):
    return jwt.encode({"sub":u.username, "ver":u.auth_version,
                       "mfa_verified_at": NOW - (700 if stale_mfa else 0),
                       "exp": NOW + 1800}, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def db():
    engine=create_engine("sqlite://", poolclass=StaticPool,
                         connect_args={"check_same_thread":False})
    with engine.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS public"))
        c.execute(text("""CREATE TABLE public.sendro_tenant_users(
          tenant_id INTEGER, user_id INTEGER, member_role TEXT, is_active BOOLEAN,
          PRIMARY KEY(tenant_id,user_id))"""))
        c.execute(text("""CREATE TABLE public.sendro_channel_accounts(
          id INTEGER PRIMARY KEY, tenant_id INTEGER, platform TEXT,
          external_account_id TEXT, status TEXT)"""))
        c.execute(text("""CREATE TABLE public.sendro_instagram_token_vault(
          tenant_id INTEGER NOT NULL, channel_account_id INTEGER NOT NULL,
          provider_user_id TEXT NOT NULL, encrypted_token BLOB NOT NULL,
          issued_epoch INTEGER NOT NULL, expires_epoch INTEGER NOT NULL,
          revision INTEGER NOT NULL, PRIMARY KEY(tenant_id,channel_account_id))"""))
        c.execute(text("""INSERT INTO public.sendro_tenant_users VALUES
                      (10,7,'owner',1),(20,8,'admin',1),(10,9,'viewer',1)"""))
        c.execute(text("""INSERT INTO public.sendro_channel_accounts VALUES
                     (31,10,'instagram',:id,'testing'),
                     (32,20,'instagram',:other,'testing'),
                     (33,10,'whatsapp','12345','active')"""),
                  {"id":USER_ID,"other":OTHER_ID})
    yield engine
    engine.dispose()


def _save(engine, prepared, *, user=None, tenant=10, account=31, stale_mfa=False):
    u=user or _user()
    with engine.begin() as c:
        return save_verified_instagram_link(
            c, prepared=prepared, user=u,
            tenant_id=tenant, channel_account_id=account,
            bearer_token=_token(u, stale_mfa=stale_mfa),
            jwt_secret=JWT_SECRET, jwt_algorithm="HS256",
            encryption_key=KEY, now_epoch=NOW)


def _vault_row(engine):
    with engine.connect() as c:
        return c.execute(text("""
          SELECT tenant_id, channel_account_id, provider_user_id,
                 encrypted_token FROM public.sendro_instagram_token_vault
        """)).mappings().all()


def test_complete_verified_professional_account_link(db):
    meta=FakeMeta()
    prepared=_prepared(meta)
    assert prepared.instagram_user_id==USER_ID
    assert prepared.account_type=="BUSINESS"
    assert len(meta.calls)==4
    assert CODE not in repr(prepared) and LONG_TOKEN not in str(prepared)
    result=_save(db,prepared)
    assert result=={"connected":True,"expires_at_epoch":NOW+60*86400}
    assert CODE not in str(result) and LONG_TOKEN not in str(result)
    rows=_vault_row(db)
    assert len(rows)==1 and rows[0]["provider_user_id"]==USER_ID
    assert rows[0]["tenant_id"]==10 and rows[0]["channel_account_id"]==31
    assert LONG_TOKEN.encode() not in rows[0]["encrypted_token"]


def test_creator_professional_supported(db):
    prepared=_prepared(FakeMeta(account_type="CREATOR"))
    assert _save(db,prepared)["connected"]


@pytest.mark.parametrize("bad",[
    {"short_id":OTHER_ID},
    {"short_profile_id":OTHER_ID},
    {"long_profile_id":OTHER_ID},
    {"account_type":None},
    {"account_type":"PERSONAL"},
    {"account_type":"BUSINESS","long_account_type":"CREATOR"},
    {"long_status":400},
])
def test_wrong_subject_nonprofessional_or_token_exchange_error_no_persistence(db,bad):
    meta=FakeMeta(**bad)
    with pytest.raises(InstagramAccountLinkDenied) as err:
        _prepared(meta)
    assert LONG_TOKEN not in str(err.value) and APP_SECRET not in str(err.value)
    assert _vault_row(db)==[]


def test_no_network_when_claim_invalid():
    meta=FakeMeta()
    for invalid_claim in [None,object(),ClaimedInstagramCode(0,7,CODE),
                          ClaimedInstagramCode(10,0,CODE)]:
        with pytest.raises(InstagramAccountLinkDenied):
            prepare_verified_instagram_link(
                claimed_code=invalid_claim, instagram_app_id=APP_ID,
                instagram_app_secret=APP_SECRET, session=meta)
    assert meta.calls==[]


def test_cross_tenant_and_mismatched_user_or_account_prevent_link(db):
    prepared=_prepared()
    for args in [
        {"tenant":20,"user":_user(8,"second-admin"),"account":32},
        {"tenant":10,"account":33},
        {"tenant":20},
        {"user":_user(9,"viewer")},
        {"user":_user(8,"other")},
    ]:
        with pytest.raises(InstagramAccountLinkDenied):
            _save(db,prepared,**args)
    assert _vault_row(db)==[]
    assert _save(db,prepared)["connected"]


def test_stale_mfa_or_revoked_membership_prevent_token_storage(db):
    prepared=_prepared()
    with pytest.raises(InstagramAccountLinkDenied):
        _save(db,prepared,stale_mfa=True)
    with db.begin() as c:
        c.execute(text("UPDATE public.sendro_tenant_users SET is_active=0 WHERE tenant_id=10 AND user_id=7"))
    with pytest.raises(InstagramAccountLinkDenied):
        _save(db,prepared)
    assert _vault_row(db)==[]


def test_duplicate_link_does_not_overwrite_existing_token(db):
    prepared=_prepared()
    _save(db,prepared)
    before=bytes(_vault_row(db)[0]["encrypted_token"])
    with pytest.raises(InstagramAccountLinkDenied):
        _save(db,prepared)
    assert bytes(_vault_row(db)[0]["encrypted_token"])==before


def test_unmounted_and_no_graph_request_at_import():
    source=(Path(__file__).parents[1]/"app"/"main.py").read_text(encoding="utf-8")
    assert "instagram_account_link" not in source

def test_short_lived_token_object_does_not_leak_when_repr_called():
    from backend.app.instagram_login_oauth import InstagramShortToken
    short=InstagramShortToken(access_token=SHORT_TOKEN, instagram_user_id=USER_ID)
    assert SHORT_TOKEN not in repr(short)
    assert SHORT_TOKEN not in str(short)
