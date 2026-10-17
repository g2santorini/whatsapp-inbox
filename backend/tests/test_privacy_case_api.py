"""Synthetic GDPR case API and storage tests; SQLite in-memory only."""
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.privacy_case_api import create_privacy_case_router

bearer = HTTPBearer()


def fake_user(token: HTTPAuthorizationCredentials = Depends(bearer)):
    people = {"admin": 1, "owner-b": 2, "operator": 3,
              "admin-b": 4, "disabled": 5, "revoked": 6}
    if token.credentials not in people:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return SimpleNamespace(id=people[token.credentials])


@pytest.fixture
def service():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    with engine.begin() as db:
        db.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        db.exec_driver_sql("CREATE TABLE public.users(id INTEGER PRIMARY KEY, disabled BOOLEAN)")
        db.exec_driver_sql("""CREATE TABLE public.sendro_tenant_users(
            tenant_id INTEGER, user_id INTEGER, member_role TEXT, is_active BOOLEAN,
            PRIMARY KEY(tenant_id, user_id))""")
        db.exec_driver_sql("""CREATE TABLE public.sendro_privacy_cases(
            case_ref TEXT PRIMARY KEY, tenant_id INTEGER, channel TEXT, status TEXT,
            scope_blockers TEXT, response_recorded BOOLEAN, version INTEGER,
            received_at TEXT, updated_at TEXT)""")
        db.exec_driver_sql("""CREATE TABLE public.sendro_privacy_case_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, case_ref TEXT, tenant_id INTEGER,
            seq INTEGER, actor_user_id INTEGER, action TEXT, recorded_at TEXT,
            UNIQUE(case_ref, seq))""")
        db.exec_driver_sql("""INSERT INTO public.users VALUES
            (1,0),(2,0),(3,0),(4,0),(5,1),(6,0)""")
        db.exec_driver_sql("""INSERT INTO public.sendro_tenant_users VALUES
            (101,1,'admin',1), (202,2,'owner',1),
            (101,3,'operator',1), (202,4,'admin',1),
            (101,5,'admin',1), (101,6,'admin',0)""")
    factory = sessionmaker(bind=engine)

    def test_db():
        with factory() as db:
            yield db

    app = FastAPI()
    app.include_router(create_privacy_case_router(fake_user, test_db))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, factory, engine
    engine.dispose()


def auth(user="admin"):
    return {"Authorization": "Bearer " + user}


def create(client, tenant=101, user="admin", extra=None):
    return client.post("/privacy/requests", headers=auth(user),
                       json={"tenant_id": tenant, "channel": "whatsapp",
                             **(extra or {})})


def action(client, ref, action_name, data, tenant=101, user="admin"):
    return client.post(
        f"/privacy/requests/{ref}/{action_name}?tenant_id={tenant}",
        headers=auth(user), json=data)


def complete_evidence():
    fields = ("controller_authority_confirmed", "identity_authority_verified",
              "tenant_scope_checked", "whatsapp_records_checked",
              "instagram_records_checked", "template_batches_checked",
              "unlinked_batch_items_checked", "media_checked",
              "provider_copies_checked", "application_logs_checked",
              "backup_restore_plan_checked", "retention_exceptions_checked")
    return {**{name: True for name in fields}, "legal_hold": False}


def test_case_persisted_with_opaque_reference_and_list_scope(service):
    client, factory, _ = service
    response = create(client)
    assert response.status_code == 201, response.text
    summary = response.json()
    ref = summary["case_ref"]
    assert UUID(ref).version == 4
    assert summary["status"] == "received"
    assert summary["audit_events"] == 1
    assert summary["erasure_enabled"] is False
    assert summary["erasure_performed"] is False
    assert summary["identity_verified_by_system"] is False
    assert client.get(f"/privacy/requests/{ref}?tenant_id=101",
                      headers=auth()).json() == summary
    assert client.get("/privacy/requests?tenant_id=101",
                      headers=auth()).json() == [summary]
    with factory() as db:
        assert db.execute(text("SELECT count(*) FROM public.sendro_privacy_case_events")).scalar_one() == 1
        assert db.execute(text("SELECT version FROM public.sendro_privacy_cases")).scalar_one() == 1


def test_role_gate_reads_database_not_client_claim(service):
    client, factory, _ = service
    ref = create(client).json()["case_ref"]
    for user, tenant in (
        ("operator", 101), ("disabled", 101), ("revoked", 101),
        ("admin-b", 101), ("owner-b", 101), ("admin", 202)
    ):
        assert create(client, tenant=tenant, user=user).status_code == 403
        assert client.get(f"/privacy/requests/{ref}?tenant_id={tenant}",
                          headers=auth(user)).status_code == 403
    assert client.get(f"/privacy/requests/{ref}?tenant_id=202",
                      headers=auth("admin-b")).status_code == 404
    assert client.get("/privacy/requests?tenant_id=202",
                      headers=auth("admin-b")).json() == []
    with factory() as db:
        db.execute(text("""UPDATE public.sendro_tenant_users SET is_active=0
                        WHERE tenant_id=101 AND user_id=1"""))
        db.commit()
    assert client.get("/privacy/requests?tenant_id=101",
                      headers=auth()).status_code == 403


def test_complete_review_never_approves_erasure(service):
    client, factory, _ = service
    ref = create(client).json()["case_ref"]
    assert action(client, ref, "scope-review", complete_evidence()).status_code == 422
    assert action(client, ref, "identity-check",
                  {"externally_confirmed": False}).status_code == 422
    assert action(client, ref, "identity-check",
                  {"externally_confirmed": True}).json()["status"] == "identity_checked"
    missing = action(client, ref, "scope-review", {}).json()
    assert missing["status"] == "needs_evidence"
    assert "unlinked_batch_items_checked" in missing["blockers"]
    hold = action(client, ref, "scope-review",
                  {**complete_evidence(), "legal_hold": True}).json()
    assert hold["status"] == "on_hold"
    ready = action(client, ref, "scope-review", complete_evidence()).json()
    assert ready["status"] == "ready_for_manual_decision"
    assert ready["safe_to_delete_count"] == 0
    assert ready["erasure_enabled"] is False
    answered = action(client, ref, "response",
                      {"externally_confirmed": True}).json()
    assert answered["response_recorded"] is True
    assert answered["erasure_performed"] is False
    assert action(client, ref, "response",
                  {"externally_confirmed": True}).status_code == 422
    with factory() as db:
        rows = db.execute(text("""SELECT seq, action, actor_user_id
           FROM public.sendro_privacy_case_events ORDER BY seq""")).mappings().all()
        assert [(r["seq"], r["action"], r["actor_user_id"]) for r in rows] == [
            (1, "received", 1), (2, "identity_checked", 1),
            (3, "scope_reviewed", 1), (4, "scope_reviewed", 1),
            (5, "scope_reviewed", 1), (6, "response_recorded", 1)]
        assert db.execute(text("SELECT version FROM public.sendro_privacy_cases")).scalar_one() == 6


@pytest.mark.parametrize("invalid", [
    {"phone": "+306900000000"}, {"message": "guest contents"},
    {"channel": "tiktok"}, {"tenant_id": -1},
])
def test_rejects_unwanted_pii_and_invalid_fields(service, invalid):
    client, _, _ = service
    assert create(client, extra=invalid).status_code == 422
    ref = create(client).json()["case_ref"]
    assert action(client, ref, "identity-check",
                  {"externally_confirmed": True, "note": "free text"}).status_code == 422
    assert action(client, ref, "identity-check",
                  {"externally_confirmed": "true"}).status_code == 422


def test_atomic_rollback_when_audit_insert_fails(service):
    client, factory, engine = service
    ref = create(client).json()["case_ref"]
    with engine.begin() as conn:
        conn.exec_driver_sql("""CREATE TRIGGER public.synthetic_failure
            BEFORE INSERT ON sendro_privacy_case_events
            BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END""")
    result = action(client, ref, "identity-check", {"externally_confirmed": True})
    assert result.status_code >= 500
    with factory() as db:
        assert db.execute(text("SELECT version FROM public.sendro_privacy_cases")).scalar_one() == 1
        assert db.execute(text("SELECT count(*) FROM public.sendro_privacy_case_events")).scalar_one() == 1


def test_no_production_import_or_erasure_action():
    from pathlib import Path
    main = (Path(__file__).parents[1] / "app" / "main.py").read_text()
    assert "create_privacy_case_router" not in main
    store = (Path(__file__).parents[1] / "app" / "privacy_case_store.py").read_text()
    assert "DELETE FROM" not in store
    assert "CREATE TABLE" not in store
    assert "DATABASE_URL" not in store
