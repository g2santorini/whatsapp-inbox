"""GDPR read-only preview never mounts on production and never writes.

All HTTP/tenant tests use synthetic records in in-memory SQLite. This test
does not require or connect to Render's shared PostgreSQL database.
"""
from datetime import datetime, timedelta, timezone
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from jose import JWTError, jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.privacy_readonly_preview import (
    STAGING_RENDER_SERVICE_ID, FLAG_NAME, APPROVAL_NAME, APPROVAL_VALUE,
    create_privacy_readonly_router, mount_privacy_readonly_preview,
    preview_is_allowed,
)
from backend.app.privacy_mfa_session import (
    add_recent_mfa_claim, create_privacy_verified_user_dependency,
    require_recent_mfa_token,
)


bearer = HTTPBearer()


def user_from_token(token: HTTPAuthorizationCredentials = Depends(bearer)):
    identities = {
        "admin-a": 11, "owner-b": 22, "operator-a": 33,
        "admin-b": 44, "inactive-a": 55, "disabled-a": 66,
        "no-mfa-admin-a": 77,
    }
    if token.credentials not in identities:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return SimpleNamespace(
        id=identities[token.credentials],
        mfa_enabled=token.credentials != "no-mfa-admin-a",
    )


def auth(value="admin-a"):
    return {"Authorization": "Bearer " + value}


@pytest.fixture
def fake_database():
    engine = create_engine("sqlite://",
        connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as con:
        con.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        con.exec_driver_sql("CREATE TABLE public.users(id INTEGER PRIMARY KEY, disabled BOOLEAN)")
        con.exec_driver_sql("""CREATE TABLE public.sendro_tenant_users(
            tenant_id INTEGER, user_id INTEGER, member_role TEXT, is_active BOOLEAN,
            PRIMARY KEY (tenant_id, user_id))""")
        con.exec_driver_sql("""CREATE TABLE public.sendro_privacy_cases(
            case_ref TEXT PRIMARY KEY, tenant_id INTEGER, channel TEXT, status TEXT,
            scope_blockers TEXT, response_recorded BOOLEAN, version INTEGER,
            received_at TEXT, updated_at TEXT)""")
        con.exec_driver_sql("""CREATE TABLE public.sendro_privacy_case_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, case_ref TEXT, tenant_id INTEGER,
            seq INTEGER, actor_user_id INTEGER, action TEXT, recorded_at TEXT,
            UNIQUE(case_ref, seq))""")
        con.exec_driver_sql("""INSERT INTO public.users VALUES
            (11,0),(22,0),(33,0),(44,0),(55,0),(66,1),(77,0)""")
        con.exec_driver_sql("""INSERT INTO public.sendro_tenant_users VALUES
            (101,11,'admin',1),(202,22,'owner',1),(101,33,'operator',1),
            (202,44,'admin',1),(101,55,'admin',0),(101,66,'admin',1),
            (101,77,'admin',1)""")
        ref = str(uuid4())
        when = datetime.now(timezone.utc).isoformat()
        con.execute(text("""INSERT INTO public.sendro_privacy_cases
            VALUES (:ref,101,'whatsapp','received','[]',0,1,:now,:now)"""),
            {"ref":ref,"now":when})
        con.execute(text("""INSERT INTO public.sendro_privacy_case_events
            (case_ref,tenant_id,seq,actor_user_id,action,recorded_at)
            VALUES (:ref,101,1,11,'received',:now)"""),
            {"ref":ref,"now":when})
    factory = sessionmaker(bind=engine)
    def get_db():
        with factory() as db:
            yield db
    yield get_db, ref
    engine.dispose()


def _enabled_settings():
    return {
        FLAG_NAME: "enabled",
        APPROVAL_NAME: APPROVAL_VALUE,
        "RENDER_SERVICE_ID": STAGING_RENDER_SERVICE_ID,
    }


def test_flag_requires_staging_service_and_explicit_review():
    assert preview_is_allowed({}) is False
    assert preview_is_allowed({FLAG_NAME:"enabled"}) is False
    allowed = _enabled_settings()
    assert preview_is_allowed(allowed) is True
    for altered in (
        {**allowed, "RENDER_SERVICE_ID": "srv-production-sendro"},
        {**allowed, "RENDER_SERVICE_ID": ""},
        {**allowed, APPROVAL_NAME: "yes"},
        {**allowed, FLAG_NAME: "true"},
    ):
        assert preview_is_allowed(altered) is False


def test_misconfigured_flag_does_not_take_down_app(fake_database):
    db, _ = fake_database
    for settings in ({}, {**_enabled_settings(), "RENDER_SERVICE_ID": "production"}):
        app = FastAPI()
        assert mount_privacy_readonly_preview(
            app, user_from_token, db, settings=settings) is False
        with TestClient(app) as client:
            assert client.get("/privacy/requests?tenant_id=101",
                headers=auth()).status_code == 404
            assert client.post("/privacy/requests",
                headers=auth(), json={}).status_code == 404


def test_enabled_preview_get_only_tenant_scoped_and_non_cacheable(fake_database):
    db, ref = fake_database
    app = FastAPI()
    assert mount_privacy_readonly_preview(
        app, user_from_token, db, settings=_enabled_settings()) is True

    privacy_routes = [
        route for route in app.routes if isinstance(route, APIRoute)
        and route.path.startswith("/privacy/requests")
    ]
    assert len(privacy_routes) == 2
    assert set.union(*(route.methods for route in privacy_routes)) == {"GET"}
    for route in privacy_routes:
        assert user_from_token in {
            dependency.call for dependency in route.dependant.dependencies}

    with TestClient(app) as client:
        listing = client.get("/privacy/requests?tenant_id=101", headers=auth())
        assert listing.status_code == 200, listing.text
        assert listing.headers["cache-control"] == "no-store, private"
        assert listing.headers["x-robots-tag"] == "noindex, nofollow"
        assert len(listing.json()) == 1
        assert listing.json()[0]["case_ref"] == ref
        assert listing.json()[0]["erasure_enabled"] is False
        assert listing.json()[0]["safe_to_delete_count"] == 0
        assert client.get(f"/privacy/requests/{ref}?tenant_id=101",
            headers=auth()).json() == listing.json()[0]

        for token in ("operator-a", "inactive-a", "disabled-a", "owner-b",
                      "no-mfa-admin-a"):
            assert client.get("/privacy/requests?tenant_id=101",
                headers=auth(token)).status_code == 403
        assert client.get(f"/privacy/requests/{ref}?tenant_id=101",
            headers=auth("no-mfa-admin-a")).status_code == 403
        assert client.get("/privacy/requests?tenant_id=202",
            headers=auth("owner-b")).json() == []
        assert client.get(f"/privacy/requests/{ref}?tenant_id=202",
            headers=auth("owner-b")).status_code == 404
        assert client.get("/privacy/requests?tenant_id=101").status_code in (401, 403)
        assert client.get("/privacy/requests?tenant_id=-1",
            headers=auth()).status_code == 422

        for path in (
            "/privacy/requests",
            f"/privacy/requests/{ref}/identity-check?tenant_id=101",
            f"/privacy/requests/{ref}/scope-review?tenant_id=101",
            f"/privacy/requests/{ref}/response?tenant_id=101",
        ):
            assert client.post(path, headers=auth(), json={
                "tenant_id":101,"channel":"instagram",
            }).status_code in (404,405)


def test_readonly_module_does_not_import_mutating_case_router():
    from pathlib import Path
    source = (Path(__file__).parents[1] / "app" /
              "privacy_readonly_preview.py").read_text()
    assert "privacy_case_api" not in source
    assert "create_privacy_case_router" not in source
    assert "create_request(" not in source
    assert "update_request(" not in source
    assert "DELETE FROM" not in source
    assert "INSERT INTO" not in source
    assert "UPDATE public" not in source


def test_privacy_step_up_requires_signed_recent_mfa_and_enrollment():
    secret = "synthetic-privacy-step-up-test-secret"
    now = int(time.time())
    user = SimpleNamespace(username="admin-a", mfa_enabled=True)
    base = {"sub": "admin-a", "exp": now + 3600, "ver": 1}
    verified = add_recent_mfa_claim(
        base, datetime.fromtimestamp(now - 30, tz=timezone.utc),
    )
    assert base.get("mfa_verified_at") is None  # non-mutating
    token = jwt.encode(verified, secret, algorithm="HS256")
    assert require_recent_mfa_token(
        user, token=token, secret_key=secret, algorithm="HS256", now_epoch=now,
    ) is user

    with pytest.raises(ValueError):
        add_recent_mfa_claim(base, datetime.utcnow())

    variants = [
        base,  # password-only or trusted-device token
        {**verified, "mfa_verified_at": now - 601},  # stale
        {**verified, "mfa_verified_at": now + 1},  # future time
        {**verified, "mfa_verified_at": True},  # bool is not a timestamp
        {**verified, "mfa_verified_at": "recent"},  # untrusted type
        {**verified, "sub": "someone-else"},  # wrong principal
        {**verified, "exp": now - 1},  # expired JWT
    ]
    for payload in variants:
        candidate = jwt.encode(payload, secret, algorithm="HS256")
        with pytest.raises(HTTPException) as exc:
            require_recent_mfa_token(
                user, token=candidate, secret_key=secret,
                algorithm="HS256", now_epoch=now,
            )
        assert exc.value.status_code in (401, 403)

    forged = jwt.encode(verified, "different-secret", algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        require_recent_mfa_token(
            user, token=forged, secret_key=secret, algorithm="HS256",
            now_epoch=now,
        )
    assert exc.value.status_code == 401

    user_without_mfa = SimpleNamespace(username="admin-a", mfa_enabled=False)
    with pytest.raises(HTTPException) as exc:
        require_recent_mfa_token(
            user_without_mfa, token=token, secret_key=secret,
            algorithm="HS256", now_epoch=now,
        )
    assert exc.value.status_code == 403


def test_step_up_dependency_in_real_http_flow():
    """Use synthetic signed JWTs, never live Sendro users or the shared database."""
    secret = "synthetic-private-route-signing-secret"
    scheme = OAuth2PasswordBearer(tokenUrl="token")

    def synthetic_active_user(token: str = Depends(scheme)):
        try:
            claims = jwt.decode(token, secret, algorithms=["HS256"])
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid token")
        return SimpleNamespace(username=claims["sub"], mfa_enabled=True)

    guarded = create_privacy_verified_user_dependency(
        synthetic_active_user, scheme, secret_key=secret, algorithm="HS256",
    )
    app = FastAPI()

    @app.get("/synthetic-privacy-probe")
    def probe(user=Depends(guarded)):
        return {"username": user.username}

    now = int(time.time())

    def headers(proof):
        payload = {"sub": "synthetic-admin", "exp": now + 3600, "ver": 1}
        if proof is not None:
            payload["mfa_verified_at"] = proof
        return {"Authorization": "Bearer " + jwt.encode(
            payload, secret, algorithm="HS256",
        )}

    with TestClient(app) as client:
        good = client.get("/synthetic-privacy-probe", headers=headers(now - 10))
        assert good.status_code == 200
        assert good.json()["username"] == "synthetic-admin"
        assert client.get("/synthetic-privacy-probe", headers=headers(None)).status_code == 403
        assert client.get("/synthetic-privacy-probe", headers=headers(now - 900)).status_code == 403
        assert client.get("/synthetic-privacy-probe").status_code in (401, 403)


def test_real_app_only_attests_completed_mfa_and_mounts_protected_dependency():
    from pathlib import Path
    source = (Path(__file__).parents[1] / "app" / "main.py").read_text()
    normal_login = source.split('@app.post("/token",', 1)[1].split(
        '@app.post("/token/mfa",', 1,
    )[0]
    completed_mfa = source.split('@app.post("/token/mfa",', 1)[1].split(
        '@app.get("/users/me/",', 1,
    )[0]
    assert "mfa_verified_at=" not in normal_login
    assert "mfa_verified_at=now.replace(tzinfo=timezone.utc)" in completed_mfa
    assert "privacy_mfa_session.create_privacy_verified_user_dependency(" in source
