"""Synthetic HTTP-to-encrypted-vault integration for the UNMOUNTED router.

Uses a disposable in-memory SQLite DB and a fake Meta verifier; there are
no real secrets, Render connections, network calls, or Sendro main imports.
"""
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.security import OAuth2PasswordBearer
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend.app.instagram_oauth_callback_inbox import capture_instagram_authorization_code
from backend.app.instagram_account_link import (
    InstagramAccountLinkDenied, VerifiedInstagramLink,
)
from backend.app.instagram_onboarding_router import create_dormant_instagram_onboarding_router
from backend.app.instagram_oauth_http_security import (
    InstagramOAuthLogAttestations, STAGING_FRONTEND_ORIGIN,
    STAGING_BACKEND_HOST,
)

NOW = int(time.time())
SECRET = "synthetic-signed-sendro-JWT-for-ci-only"
CODE_KEY = Fernet.generate_key().decode()
VAULT_KEY = Fernet.generate_key().decode()
USER_ID = "17841402010000000"
TOKEN = "synthetic-60-day-IG-access-token"
FAKE_CODE = "synthetic_Meta_auth_code_only"
APP_ID = "123456789"
PATH = "/channels/instagram/oauth"


def user(**kw):
    values=dict(id=7, username="ci-owner", role="admin", disabled=False,
                must_change_password=False, mfa_setup_required=False,
                mfa_enabled=True, auth_version=1)
    values.update(kw)
    return SimpleNamespace(**values)


def signed(u, *, mfa_age=0, version=1):
    return jwt.encode({
        "sub":u.username, "ver":version, "mfa_verified_at":NOW-mfa_age,
        "exp":NOW+1800,
    }, SECRET, algorithm="HS256")


@pytest.fixture
def engine():
    engine=create_engine("sqlite://",poolclass=StaticPool,
                         connect_args={"check_same_thread":False})
    with engine.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS public"))
        c.execute(text("""CREATE TABLE public.sendro_tenant_users(
            tenant_id INTEGER, user_id INTEGER, member_role TEXT, is_active BOOLEAN,
            PRIMARY KEY(tenant_id,user_id))"""))
        c.execute(text("""CREATE TABLE public.sendro_channel_accounts(
            id INTEGER PRIMARY KEY, tenant_id INTEGER, platform TEXT,
            external_account_id TEXT, status TEXT)"""))
        c.execute(text("""CREATE TABLE public.sendro_instagram_oauth_challenges(
            state_hash TEXT PRIMARY KEY, tenant_id INTEGER, user_id INTEGER,
            created_epoch INTEGER, expires_epoch INTEGER,
            encrypted_authorization_code BLOB, received_epoch INTEGER)"""))
        c.execute(text("""CREATE TABLE public.sendro_instagram_token_vault(
            tenant_id INTEGER, channel_account_id INTEGER, provider_user_id TEXT,
            encrypted_token BLOB, issued_epoch INTEGER, expires_epoch INTEGER,
            revision INTEGER, PRIMARY KEY(tenant_id, channel_account_id))"""))
        c.execute(text("""INSERT INTO public.sendro_tenant_users VALUES
            (10,7,'owner',1),(20,8,'admin',1),(10,9,'viewer',1)"""))
        c.execute(text("""INSERT INTO public.sendro_channel_accounts VALUES
            (31,10,'instagram',:id,'testing')"""),{"id":USER_ID})
    yield engine
    engine.dispose()


def config(**kw):
    values={k:True for k in InstagramOAuthLogAttestations.__dataclass_fields__}
    values.update(kw)
    return InstagramOAuthLogAttestations(**values)


def client_for(engine, *, enabled=True, attestations=None, current=None,
               preparation=None):
    u=current or user()
    state={"calls":0,"vault_exists_at_meta":None,"challenge_exists_at_meta":None}
    def fake_meta(*,claimed_code,instagram_app_id,instagram_app_secret,egress_approval):
        state["calls"]+=1
        assert claimed_code.authorization_code==FAKE_CODE
        assert instagram_app_id==APP_ID
        assert instagram_app_secret=="synthetic-secret"
        assert egress_approval.approved() is True
        with engine.connect() as c:
            state["challenge_exists_at_meta"]=c.execute(
                text("SELECT COUNT(*) FROM public.sendro_instagram_oauth_challenges")
            ).scalar_one()
            state["vault_exists_at_meta"]=c.execute(
                text("SELECT COUNT(*) FROM public.sendro_instagram_token_vault")
            ).scalar_one()
        if preparation is not None:
            return preparation(claimed_code)
        return VerifiedInstagramLink(
            tenant_id=claimed_code.tenant_id,
            requested_by_user_id=claimed_code.user_id,
            instagram_user_id=USER_ID, account_type="BUSINESS",
            username="ci_only",long_lived_access_token=TOKEN,
            expires_in_seconds=60*86400,
        )

    app=FastAPI()
    def fake_current_user():
        # Synthetic injection. Real app must use get_current_active_user.
        return u
    app.include_router(create_dormant_instagram_onboarding_router(
        current_user_dependency=fake_current_user,
        bearer_dependency=OAuth2PasswordBearer(tokenUrl="/token"),
        transaction=engine.begin,log_attestations=attestations or config(),
        jwt_secret=SECRET,jwt_algorithm="HS256",instagram_app_id=APP_ID,
        instagram_app_secret="synthetic-secret",
        authorization_code_key=CODE_KEY,token_vault_key=VAULT_KEY,
        enabled=enabled,prepare_link=fake_meta,
    ))
    return TestClient(app,base_url="https://"+STAGING_BACKEND_HOST),u,state


def headers(u=None, *,origin=STAGING_FRONTEND_ORIGIN,**kw):
    u=u or user()
    return {"Origin":origin,"Authorization":"Bearer "+signed(u),
            "Content-Type":"application/json",**kw}


def started(client, u=None):
    response=client.post(PATH+"/start",json={"tenant_id":10},headers=headers(u))
    assert response.status_code==200,response.text
    assert response.headers.get("cache-control")=="no-store, private"
    url=response.json()["authorization_url"]
    return parse_qs(urlsplit(url).query)["state"][0]


def captured(engine, state):
    with engine.begin() as c:
        capture_instagram_authorization_code(
            c,state=state,code=FAKE_CODE,encryption_key=CODE_KEY,
        )


def completed(client,state,u=None,**body):
    return client.post(PATH+"/complete",json={
        "tenant_id":10,"channel_account_id":31,"state":state,**body,
    },headers=headers(u))


def test_complete_uses_committed_single_use_claim_then_encrypts_vault(engine):
    client,u,trace=client_for(engine)
    nonce=started(client,u)
    captured(engine,nonce)
    result=completed(client,nonce,u)
    assert result.status_code==200,result.text
    assert result.json()["connected"] is True
    assert "authorization" not in str(result.json())
    assert TOKEN not in result.text and FAKE_CODE not in result.text
    assert trace["calls"]==1
    assert trace["challenge_exists_at_meta"]==0
    assert trace["vault_exists_at_meta"]==0
    with engine.connect() as c:
        secret=c.execute(text(
            "SELECT encrypted_token FROM public.sendro_instagram_token_vault"
        )).scalar_one()
    assert TOKEN.encode() not in secret
    replay=completed(client,nonce,u)
    assert replay.status_code==403
    assert trace["calls"]==1


def test_missing_operator_flags_fails_closed_before_state_or_meta(engine):
    for att in (config(reviewed_release_authorized=False),None):
        client,u,trace=client_for(
            engine,enabled=False if att is None else True,attestations=att)
        assert client.post(PATH+"/start",json={"tenant_id":10},
                           headers=headers(u)).status_code==503
        assert trace["calls"]==0
    with engine.connect() as c:
        assert c.execute(text(
            "SELECT COUNT(*) FROM public.sendro_instagram_oauth_challenges"
        )).scalar_one()==0


def test_cross_origin_or_missing_bearer_fails_before_db(engine):
    client,u,trace=client_for(engine)
    response=client.post(PATH+"/start",json={"tenant_id":10},
                         headers=headers(u,origin="https://evil.example"))
    assert response.status_code==503
    response=client.post(PATH+"/start",json={"tenant_id":10},
                         headers={"Origin":STAGING_FRONTEND_ORIGIN})
    assert response.status_code==401
    assert trace["calls"]==0


def test_cross_tenant_and_wrong_state_never_reach_meta(engine):
    client,u,trace=client_for(engine)
    nonce=started(client,u)
    captured(engine,nonce)
    assert completed(client,"z"*43,u).status_code==403
    assert completed(client,nonce,u,tenant_id=20).status_code==403
    assert trace["calls"]==0
    assert completed(client,nonce,u).status_code==200


def test_incorrect_jwt_or_stale_mfa_denied(engine):
    client,u,trace=client_for(engine)
    bad={"Origin":STAGING_FRONTEND_ORIGIN,
         "Authorization":"Bearer badinvalidsignedJWT",
         "Content-Type":"application/json"}
    assert client.post(PATH+"/start",json={"tenant_id":10},headers=bad).status_code==403
    old={**headers(u),"Authorization":"Bearer "+signed(u,mfa_age=700)}
    assert client.post(PATH+"/start",json={"tenant_id":10},headers=old).status_code==403
    assert trace["calls"]==0


@pytest.mark.parametrize("payload",[
    {"tenant_id":True},{"tenant_id":0},{"tenant_id":10,"url":"sensitive"},
    {"tenant_id":"10"},{},["unexpected"],
])
def test_strict_start_body_rejected_without_detail_echo(engine,payload):
    client,u,trace=client_for(engine)
    r=client.post(PATH+"/start",json=payload,headers=headers(u))
    assert r.status_code==400
    assert "sensitive" not in r.text
    assert trace["calls"]==0


def test_body_query_mixed_rejected(engine):
    client,u,trace=client_for(engine)
    r=client.post(PATH+"/start?code="+FAKE_CODE,
                  json={"tenant_id":10},headers=headers(u))
    assert r.status_code==400 and FAKE_CODE not in r.text


def test_failed_meta_verification_burns_code_and_requires_new_start(engine):
    def reject(_):
        raise InstagramAccountLinkDenied("Instagram authorization could not be verified")
    client,u,trace=client_for(engine,preparation=reject)
    nonce=started(client,u)
    captured(engine,nonce)
    result=completed(client,nonce,u)
    assert result.status_code==409
    assert "authorization" not in result.text
    assert completed(client,nonce,u).status_code==403
    assert trace["calls"]==1


def test_user_tenant_membership_revocation_blocks_complete(engine):
    client,u,trace=client_for(engine)
    nonce=started(client,u)
    captured(engine,nonce)
    with engine.begin() as c:
        c.execute(text("""UPDATE public.sendro_tenant_users
            SET is_active=0 WHERE user_id=7 AND tenant_id=10"""))
    assert completed(client,nonce,u).status_code==403
    assert trace["calls"]==0


def test_dormant_factory_is_not_in_main_or_frontend_routes():
    source=(__import__("pathlib").Path(__file__).parents[1]/
            "app"/"main.py").read_text(encoding="utf8")
    assert "instagram_onboarding_router" not in source
