"""Webflow - Ai backlog import: exact counts, correct hierarchy, atomic one-time admin action."""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./unused_webflow_import_test.db")

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base, get_db
from backend.app import models, project_models, task_models
from backend.app.project_api import create_project_router

@pytest.fixture()
def app_context():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for uid, role in ((1, "admin"), (2, "developer")):
            db.add(models.User(
                id=uid, username=f"tester_{uid}", email=f"user{uid}@test.invalid",
                hashed_password="test", role=role, disabled=False
            ))
        db.commit()
    current = {"id": 1}
    app = FastAPI()
    def test_db():
        with factory() as db:
            yield db
    def test_user(db: Session = Depends(test_db)):
        return db.get(models.User, current["id"])
    app.dependency_overrides[get_db] = test_db
    app.include_router(create_project_router(test_user))
    with TestClient(app) as client:
        yield client, current
    engine.dispose()

def test_complete_backlog_and_idempotence(app_context):
    client, current = app_context
    project_resp = client.post("/projects/", json={"name": "Webflow - Ai"})
    assert project_resp.status_code == 201
    project_id = project_resp.json()["id"]

    current["id"] = 2
    assert client.post(f"/projects/{project_id}/import-webflow-ai-backlog").status_code == 403

    current["id"] = 1
    imported = client.post(f"/projects/{project_id}/import-webflow-ai-backlog")
    assert imported.status_code == 200, imported.text
    assert imported.json() == {
        "status": "imported", "sections": 12, "milestones": 28,
        "tasks": 134, "specifications": 10,
    }
    project = client.get(f"/projects/{project_id}").json()
    assert len(project["milestones"]) == 13
    assert len(project["tasks"]) == 172
    assert project["total_tasks"] == 144
    assert project["progress"] == 0
    assert any(task["title"].startswith("P01-01 — ") for task in project["tasks"])
    assert any(task["title"].startswith("P12-07 — ") for task in project["tasks"])
    assert any(task["title"].startswith("SPEC-10 — ") for task in project["tasks"])
    assert sum(t["parent_task_id"] is not None for t in project["tasks"]) == 134

    retry = client.post(f"/projects/{project_id}/import-webflow-ai-backlog")
    assert retry.status_code == 409

    another = client.post("/projects/", json={"name": "Unrelated"}).json()["id"]
    wrong = client.post(f"/projects/{another}/import-webflow-ai-backlog")
    assert wrong.status_code == 400
