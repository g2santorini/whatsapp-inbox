"""Task Hub regression tests: open-pool claiming, visibility, assignment and project manager delegation."""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./sendro_task_hub_test_unused.db")

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base, get_db
from backend.app import models, project_models, task_models
from backend.app.project_api import create_project_router
from backend.app.tasks_api import create_tasks_router


@pytest.fixture
def system():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for uid, role in enumerate(("admin", "developer", "developer", "project_viewer", "user", "power_user"), start=1):
            db.add(models.User(
                id=uid, username=f"tester{uid}", email=f"tester{uid}@example.test",
                hashed_password="not_a_password", role=role, disabled=False,
            ))
        db.commit()

    session = {"id": 1}
    def get_test_db():
        with factory() as db:
            yield db
    def get_user(db: Session = Depends(get_test_db)):
        return db.get(models.User, session["id"])

    app = FastAPI()
    app.dependency_overrides[get_db] = get_test_db
    app.include_router(create_project_router(get_user))
    app.include_router(create_tasks_router(get_user))

    with TestClient(app) as client:
        yield client, session
    engine.dispose()


def test_standalone_assignment_open_pool_and_role_isolation(system):
    client, session = system
    created = client.post("/tasks/standalone", json={
        "title": "Fix mobile notifications", "priority": "high", "description": "Test on mobile",
    })
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    session["id"] = 4  # Viewer cannot see or take unassigned tasks.
    assert client.get("/tasks/").json() == []
    assert client.post(f"/tasks/standalone/{task_id}/claim").status_code == 403

    session["id"] = 5  # Ordinary Inbox staff not granted project access.
    assert client.get("/tasks/").json() == []
    assert client.post(f"/tasks/standalone/{task_id}/claim").status_code == 403

    session["id"] = 2  # Developer gets an eligible Open Pool.
    listed = client.get("/tasks/").json()
    assert len(listed) == 1 and listed[0]["can_claim"]
    assert client.get("/tasks/overview").json()["open_pool"] == 1
    taken = client.post(f"/tasks/standalone/{task_id}/claim")
    assert taken.status_code == 200, taken.text

    session["id"] = 3  # Another developer must not see another person's claimed task.
    assert client.get("/tasks/").json() == []
    assert client.post(f"/tasks/standalone/{task_id}/claim").status_code == 404

    session["id"] = 2
    assert client.get("/tasks/overview").json()["mine"] == 1
    assert client.patch(f"/tasks/standalone/{task_id}", json={"assigned_to_id": 3}).status_code == 403
    assert client.patch(f"/tasks/standalone/{task_id}", json={"status": "in_progress"}).status_code == 200
    assert client.post(f"/tasks/standalone/{task_id}/comments", json={"body": "Ready for QA"}).status_code == 201
    info = client.get(f"/tasks/standalone/{task_id}").json()
    assert len(info["comments"]) == 1
    assert client.post(f"/tasks/standalone/{task_id}/release").status_code == 200

    session["id"] = 3
    assert client.post(f"/tasks/standalone/{task_id}/claim").status_code == 200
    assert client.patch(f"/tasks/standalone/{task_id}", json={"status": "done"}).status_code == 200
    assert client.post(f"/tasks/standalone/{task_id}/release").status_code == 409

    session["id"] = 1
    assert client.get("/tasks/overview").json()["done"] == 1
    assert len(client.get("/tasks/team").json()) == 6
    assert client.post("/tasks/standalone", json={
        "title": "Do not assign Viewer", "assigned_to_id": 4,
    }).status_code == 400


def test_assigned_standalone_task_visible_to_ordinary_user(system):
    client, session = system
    created = client.post("/tasks/standalone", json={
        "title": "Prepare signed forms", "assigned_to_id": 5,
    })
    assert created.status_code == 201
    session["id"] = 5
    assert client.get("/tasks/").json()[0]["title"] == "Prepare signed forms"
    assert client.get("/tasks/overview").json()["mine"] == 1
    assert client.patch(f"/tasks/standalone/{created.json()['id']}", json={"status": "done"}).status_code == 200


def test_project_pool_access_and_scoped_manager(system):
    client, session = system
    alpha = client.post("/projects/", json={"name": "Alpha"}).json()["id"]
    beta = client.post("/projects/", json={"name": "Private Beta"}).json()["id"]
    assert client.post(f"/projects/{alpha}/members", json={"user_id": 2, "permission": "editor"}).status_code == 201
    assert client.post(f"/projects/{alpha}/members", json={"user_id": 3, "permission": "manager"}).status_code == 201
    assert client.post(f"/projects/{alpha}/members", json={"user_id": 4, "permission": "viewer"}).status_code == 201

    new_task = client.post(f"/projects/{alpha}/tasks", json={"title": "Open project task"})
    assert new_task.status_code == 201, new_task.text
    task_id = new_task.json()["id"]

    session["id"] = 2
    items = client.get("/tasks/").json()
    assert len(items) == 1 and items[0]["can_claim"]
    assert client.post(f"/tasks/project/{task_id}/claim").status_code == 200
    assert client.patch(f"/projects/{alpha}/tasks/{task_id}", json={"status": "done"}).status_code == 200

    session["id"] = 4
    assert client.get("/projects/").json()[0]["name"] == "Alpha"
    assert client.get("/tasks/").json()[0]["can_claim"] is False
    assert client.post(f"/tasks/project/{task_id}/claim").status_code == 403

    session["id"] = 3
    assert client.get(f"/projects/{beta}").status_code == 404
    detail = client.get(f"/projects/{alpha}")
    assert detail.json()["can_manage"] is True
    assert client.post(f"/projects/{alpha}/tasks", json={"title": "Manager created task"}).status_code == 201
    assert client.post(f"/projects/{beta}/tasks", json={"title": "Forbidden task"}).status_code == 404
    assert client.post("/projects/", json={"name": "Forbidden project"}).status_code == 403
    assert client.get("/tasks/team").status_code == 403
