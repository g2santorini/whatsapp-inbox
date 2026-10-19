"""GDPR read-only preview never mounts on production and never writes.

All HTTP/tenant tests use synthetic records in in-memory SQLite. This test
does not require or connect to Render's shared PostgreSQL database.
"""
from datetime import datetime, timedelta, timezone
import time
import logging
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
from backend.app.privacy_preview_guards import PrivacyRequestLimiter
from backend.app.privacy_access_log import (
    PrivacyAccessLogFilter, install_privacy_access_log_filter,
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
        con.exec_driver_sql("""CREATE TABLE public.sendro_tenants(
            id INTEGER PRIMARY KEY, display_name TEXT NOT NULL)""")
        con.exec_driver_sql("""INSERT INTO public.sendro_tenants VALUES
            (101,'Company A'),(202,'Company B'),(303,'No membership')""")
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
    assert len(privacy_routes) == 3
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


def test_privacy_limiter_budget_and_window_are_bounded():
    limiter = PrivacyRequestLimiter(max_calls=2, window_seconds=60, max_users=1)
    limiter.check(101, now=1000)
    limiter.check(101, now=1001)
    with pytest.raises(HTTPException) as exc:
        limiter.check(101, now=1002)
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"] == "58"
    with pytest.raises(HTTPException) as exc:
        limiter.check(202, now=1002)
    assert exc.value.status_code == 429
    limiter.check(202, now=1061)  # stale user budget expires and is evicted
    with pytest.raises(HTTPException) as exc:
        limiter.check(0, now=1061)
    assert exc.value.status_code == 403


def test_privacy_http_guards_noncacheable_for_denials_and_throttling(fake_database):
    db, ref = fake_database
    app = FastAPI()
    assert mount_privacy_readonly_preview(
        app, user_from_token, db, settings=_enabled_settings(),
    ) is True

    with TestClient(app) as client:
        for url, headers in (
            ("/privacy/requests?tenant_id=101", {}),
            ("/privacy/requests?tenant_id=101", auth("operator-a")),
            ("/privacy/requests?tenant_id=-1", auth()),
            (f"/privacy/requests/{ref}?tenant_id=202", auth()),
        ):
            result = client.get(url, headers=headers)
            assert result.status_code in (401, 403, 404, 422)
            assert result.headers["cache-control"] == "no-store, private"
            assert result.headers["pragma"] == "no-cache"
            assert result.headers["x-robots-tag"] == "noindex, nofollow"

        # The earlier authorized cross-tenant 404 also consumes one budget slot.
        for _ in range(29):
            response = client.get("/privacy/requests?tenant_id=101", headers=auth())
            assert response.status_code == 200
        result = client.get(
            f"/privacy/requests/{ref}?tenant_id=101", headers=auth())
        assert result.status_code == 429
        assert int(result.headers["Retry-After"]) >= 1
        assert result.headers["cache-control"] == "no-store, private"
        assert result.headers["x-robots-tag"] == "noindex, nofollow"


def test_http_guards_are_staging_flag_gated(fake_database):
    db, _ = fake_database
    app = FastAPI()
    assert mount_privacy_readonly_preview(
        app, user_from_token, db, settings={},
    ) is False
    assert not any(
        entry.cls.__name__ == "PrivacyNoStoreMiddleware"
        for entry in app.user_middleware
    )
    with TestClient(app) as client:
        assert client.get("/privacy/requests?tenant_id=101").status_code == 404


def test_privacy_log_filter_removes_case_ref_and_tenant_query_only():
    path = "/privacy/requests/11111111-2222-3333-4444-555555555555?tenant_id=101"
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "synthetic.py", 1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", path, "1.1", 200), None,
    )
    assert PrivacyAccessLogFilter().filter(record) is True
    rendered = record.getMessage()
    assert '/privacy/requests/[redacted]' in rendered
    assert "tenant_id" not in rendered
    assert "11111111-2222-3333-4444-555555555555" not in rendered
    assert '"GET ' in rendered
    assert "200" in rendered

    other = logging.LogRecord(
        "uvicorn.access", logging.INFO, "synthetic.py", 1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/conversations?limit=50", "1.1", 200), None,
    )
    expected = other.getMessage()
    assert PrivacyAccessLogFilter().filter(other) is True
    assert other.getMessage() == expected

    direct = logging.LogRecord(
        "uvicorn.access", logging.INFO, "synthetic.py", 1,
        '127.0.0.1 - "GET /privacy/requests?tenant_id=202 HTTP/1.1" 403',
        (), None,
    )
    assert PrivacyAccessLogFilter().filter(direct) is True
    assert 'tenant_id' not in direct.getMessage()
    assert '/privacy/requests/[redacted]' in direct.getMessage()


def test_privacy_log_filter_installation_is_idempotent():
    logger = logging.getLogger("sendro.synthetic.privacy-logging")
    before = list(logger.filters)
    try:
        install_privacy_access_log_filter(logger)
        install_privacy_access_log_filter(logger)
        assert sum(isinstance(f, PrivacyAccessLogFilter)
                   for f in logger.filters) == 1
    finally:
        logger.filters[:] = before


def test_privacy_reviewer_tenant_discovery_is_mfa_guarded_and_scoped(fake_database):
    """Synthetic identities only: no Render database reads or writes."""
    db, _ = fake_database
    app = FastAPI()
    assert mount_privacy_readonly_preview(
        app, user_from_token, db, settings=_enabled_settings(),
    ) is True

    with TestClient(app) as client:
        a = client.get("/privacy/requests/tenants", headers=auth("admin-a"))
        assert a.status_code == 200
        assert a.json() == [{"id": 101, "display_name": "Company A"}]
        assert a.headers["cache-control"] == "no-store, private"

        b = client.get("/privacy/requests/tenants", headers=auth("owner-b"))
        assert b.status_code == 200
        assert b.json() == [{"id": 202, "display_name": "Company B"}]

        op = client.get("/privacy/requests/tenants", headers=auth("operator-a"))
        assert op.status_code == 200
        assert op.json() == []  # Not an owner/admin: no GDPR tab.

        for identity in ("inactive-a", "disabled-a", "no-mfa-admin-a"):
            denied = client.get("/privacy/requests/tenants", headers=auth(identity))
            if identity == "no-mfa-admin-a":
                assert denied.status_code == 403
            else:
                assert denied.status_code == 200
                assert denied.json() == []
            assert denied.headers["cache-control"] == "no-store, private"

        missing = client.get("/privacy/requests/tenants")
        assert missing.status_code in (401, 403)
        assert missing.headers["cache-control"] == "no-store, private"

        assert client.post("/privacy/requests/tenants", headers=auth(), json={}).status_code in (404, 405)

    off = FastAPI()
    assert mount_privacy_readonly_preview(
        off, user_from_token, db, settings={},
    ) is False
    with TestClient(off) as client:
        assert client.get("/privacy/requests/tenants", headers=auth()).status_code == 404


def test_manual_workflow_needs_four_staging_approvals_and_fails_closed(fake_database):
    from backend.app.privacy_workflow_preview import (
        mount_privacy_workflow_preview, workflow_is_allowed,
        WORKFLOW_FLAG, WORKFLOW_VALUE, SCHEMA_FLAG, SCHEMA_VALUE,
    )
    db, _ = fake_database
    base = _enabled_settings()
    approved = {
        **base, WORKFLOW_FLAG: WORKFLOW_VALUE,
        SCHEMA_FLAG: SCHEMA_VALUE,
    }
    assert workflow_is_allowed({}) is False
    assert workflow_is_allowed(base) is False
    assert workflow_is_allowed(approved) is True
    for wrong in (
        {**approved, "RENDER_SERVICE_ID": "srv-production-sendro"},
        {**approved, WORKFLOW_FLAG: "enabled"},
        {**approved, SCHEMA_FLAG: ""},
        {**approved, APPROVAL_NAME: ""},
    ):
        assert workflow_is_allowed(wrong) is False

    for settings in ({}, base, {**approved, "RENDER_SERVICE_ID": "production"}):
        app = FastAPI()
        assert mount_privacy_workflow_preview(
            app, user_from_token, db, settings=settings
        ) is False
        with TestClient(app) as client:
            assert client.post("/privacy/requests", headers=auth(),
                json={"tenant_id": 101, "channel": "email"}).status_code == 404
            assert client.get("/privacy/workflow", headers=auth()).status_code == 404


def test_manual_workflow_complete_email_case_without_unsafe_erasure(fake_database):
    from backend.app.privacy_workflow_preview import (
        mount_privacy_workflow_preview, WORKFLOW_FLAG, WORKFLOW_VALUE,
        SCHEMA_FLAG, SCHEMA_VALUE,
    )
    db, _ = fake_database

    def synthetic_verified_user(user=Depends(user_from_token)):
        if not user.mfa_enabled:
            raise HTTPException(status_code=403, detail="Authenticator required")
        return user

    app = FastAPI()
    assert mount_privacy_readonly_preview(
        app, synthetic_verified_user, db, settings=_enabled_settings()
    ) is True
    assert mount_privacy_workflow_preview(
        app, synthetic_verified_user, db,
        settings={**_enabled_settings(),
            WORKFLOW_FLAG: WORKFLOW_VALUE, SCHEMA_FLAG: SCHEMA_VALUE}
    ) is True

    with TestClient(app) as client:
        cap = client.get("/privacy/workflow", headers=auth())
        assert cap.status_code == 200
        assert cap.json() == {
            "manual_workflow_enabled": True, "erasure_enabled": False,
            "subject_preview_enabled": False,
        }
        assert cap.headers["cache-control"] == "no-store, private"

        for denied in ("operator-a", "owner-b", "inactive-a", "disabled-a",
                       "no-mfa-admin-a"):
            attempt = client.post(
                "/privacy/requests", headers=auth(denied),
                json={"tenant_id": 101, "channel": "email"}
            )
            assert attempt.status_code == 403
            assert attempt.headers["cache-control"] == "no-store, private"
        assert client.post("/privacy/requests",
            json={"tenant_id": 101, "channel": "email"}).status_code in (401, 403)
        assert client.post("/privacy/requests", headers=auth(),
            json={"tenant_id": 101, "channel": "email",
                  "contact_email": "private@example.com"}).status_code == 422

        received = client.post("/privacy/requests", headers=auth(),
            json={"tenant_id": 101, "channel": "email"})
        assert received.status_code == 201, received.text
        ref = received.json()["case_ref"]
        assert received.json()["status"] == "received"
        assert received.json()["received_at"]
        assert received.json()["erasure_enabled"] is False
        assert received.headers["cache-control"] == "no-store, private"

        before = client.post(
            f"/privacy/requests/{ref}/response?tenant_id=101",
            headers=auth(), json={"externally_confirmed": True})
        assert before.status_code == 422
        denied_tenant = client.post(
            f"/privacy/requests/{ref}/identity-check?tenant_id=202",
            headers=auth(), json={"externally_confirmed": True})
        assert denied_tenant.status_code == 403
        not_confirmed = client.post(
            f"/privacy/requests/{ref}/identity-check?tenant_id=101",
            headers=auth(), json={"externally_confirmed": False})
        assert not_confirmed.status_code == 422

        ok_identity = client.post(
            f"/privacy/requests/{ref}/identity-check?tenant_id=101",
            headers=auth(), json={"externally_confirmed": True})
        assert ok_identity.status_code == 200
        assert ok_identity.json()["status"] == "identity_checked"

        scope = client.post(
            f"/privacy/requests/{ref}/scope-review?tenant_id=101",
            headers=auth(), json={})
        assert scope.status_code == 200
        assert scope.json()["status"] == "needs_evidence"
        assert len(scope.json()["blockers"]) > 0

        replied = client.post(
            f"/privacy/requests/{ref}/response?tenant_id=101",
            headers=auth(), json={"externally_confirmed": True})
        assert replied.status_code == 200
        assert replied.json()["response_recorded"] is True
        assert replied.json()["audit_events"] == 4
        assert replied.json()["erasure_performed"] is False

        again = client.post(
            f"/privacy/requests/{ref}/response?tenant_id=101",
            headers=auth(), json={"externally_confirmed": True})
        assert again.status_code == 422
        assert client.delete(
            f"/privacy/requests/{ref}?tenant_id=101",
            headers=auth()).status_code in (404, 405)
        assert client.get(
            f"/privacy/requests/{ref}?tenant_id=101",
            headers=auth()).json()["response_recorded"] is True


def test_subject_metadata_preview_is_independent_gated_tenant_scoped_and_non_mutating(fake_database):
    """Synthetic records only; no Render DB, no deletion, no message text returned."""
    from backend.app.privacy_subject_preview import (
        SUBJECT_FLAG, SUBJECT_VALUE, subject_preview_is_allowed,
        mount_subject_preview,
    )
    from backend.app.privacy_workflow_preview import (
        WORKFLOW_FLAG, WORKFLOW_VALUE, SCHEMA_FLAG, SCHEMA_VALUE,
    )

    get_db, ref = fake_database
    flags = {**_enabled_settings(),
        WORKFLOW_FLAG: WORKFLOW_VALUE,
        SCHEMA_FLAG: SCHEMA_VALUE,
        SUBJECT_FLAG: SUBJECT_VALUE}
    assert subject_preview_is_allowed({}) is False
    assert subject_preview_is_allowed(_enabled_settings()) is False
    assert subject_preview_is_allowed(flags) is True
    for denied in (
        {**flags, SUBJECT_FLAG: "enabled"},
        {**flags, "RENDER_SERVICE_ID": "production"},
        {**flags, WORKFLOW_FLAG: ""},
    ):
        assert subject_preview_is_allowed(denied) is False

    connection = get_db()
    session = next(connection)
    try:
        session.execute(text("""CREATE TABLE public.sendro_channel_accounts (
            id INTEGER PRIMARY KEY, tenant_id INTEGER, platform TEXT)"""))
        session.execute(text("""CREATE TABLE public.sendro_channel_conversations (
            id INTEGER PRIMARY KEY, tenant_id INTEGER, channel_account_id INTEGER)"""))
        session.execute(text("""CREATE TABLE public.sendro_channel_messages (
            id INTEGER PRIMARY KEY, tenant_id INTEGER, conversation_id INTEGER,
            media_json TEXT, content TEXT)"""))
        session.execute(text("""INSERT INTO public.sendro_channel_accounts VALUES
            (1,101,'instagram'),(2,202,'instagram'),(3,101,'whatsapp')"""))
        session.execute(text("""INSERT INTO public.sendro_channel_conversations VALUES
            (1011,101,1),(2022,202,2),(3033,101,3)"""))
        session.execute(text("""INSERT INTO public.sendro_channel_messages VALUES
            (1,101,1011,NULL,'synthetic private text'),
            (2,101,1011,'{}','synthetic media text'),
            (3,202,2022,NULL,'other tenant secret')"""))
        session.commit()
    finally:
        connection.close()

    endpoint = f"/privacy/requests/{ref}/subject-preview"
    def request(tenant=101, platform="instagram", cid=1011):
        return {"tenant_id": tenant, "platform":platform, "conversation_id": cid}
    off = FastAPI()
    assert mount_subject_preview(off, user_from_token, get_db, settings={}) is False
    with TestClient(off) as client:
        assert client.post(endpoint, json=request(), headers=auth()).status_code == 404

    app = FastAPI()
    assert mount_privacy_readonly_preview(
        app, user_from_token, get_db, settings=_enabled_settings()) is True
    assert mount_subject_preview(
        app, user_from_token, get_db, settings=flags) is True

    with TestClient(app) as client:
        unverified = client.post(endpoint, headers=auth(), json=request())
        assert unverified.status_code == 409
        assert unverified.headers["cache-control"] == "no-store, private"
        missing_token = client.post(endpoint, json=request())
        assert missing_token.status_code in (401, 403)
        other_tenant = client.post(endpoint, headers=auth("owner-b"),
                                   json=request(202, "instagram", 2022))
        assert other_tenant.status_code == 404

        # Mark a purely synthetic case as reviewed; no real identity data.
        connection = get_db()
        session = next(connection)
        try:
            session.execute(text("""
                UPDATE public.sendro_privacy_cases SET status='identity_checked'
                WHERE case_ref=:ref AND tenant_id=101
            """), {"ref":ref})
            session.commit()
        finally:
            connection.close()

        forbidden = client.post(endpoint, headers=auth("operator-a"), json=request())
        assert forbidden.status_code == 403
        cross = client.post(endpoint, headers=auth(), json=request(cid=2022))
        assert cross.status_code == 404
        wa = client.post(endpoint, headers=auth(), json=request(platform="whatsapp",cid=3033))
        assert wa.status_code == 409
        good = client.post(endpoint, headers=auth(), json=request())
        assert good.status_code == 200, good.text
        assert good.json() == {
            "platform": "instagram",
            "conversation_id": 1011,
            "messages": 2,
            "messages_with_media_metadata": 1,
            "partial_inventory": True,
            "linked_to_case": False,
            "erasure_enabled": False,
            "safe_to_delete_count": 0,
        }
        assert "synthetic private text" not in good.text
        assert "other tenant secret" not in good.text
        assert good.headers["cache-control"] == "no-store, private"
        assert client.delete(endpoint, headers=auth()).status_code == 405
