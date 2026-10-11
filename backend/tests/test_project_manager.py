"""Access-control and workflow regression tests for the Project Manager.

Run from repo root:
  DATABASE_URL=sqlite:///./unused.db python -m pytest backend/tests/test_project_manager.py
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./sendro_project_test_unused.db")

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base, get_db
from backend.app import models, project_models
from backend.app.project_api import create_project_router


@pytest.fixture()
def workspace():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        for i, role in enumerate(("admin", "developer", "project_viewer", "user", "power_user"), 1):
            db.add(models.User(
                id=i, username=f"user_{i}", email=f"staff{i}@example.test",
                role=role, hashed_password="test", disabled=False,
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


def test_project_isolation_and_read_only_access(workspace):
    client, current = workspace

    created = client.post("/projects/", json={"name": "Sendro Development"})
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    milestone = client.post(
        f"/projects/{project_id}/milestones", json={"title": "Security"}
    )
    assert milestone.status_code == 201, milestone.text

    first_task = client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Restrict private endpoints", "milestone_id": milestone.json()["id"]},
    )
    assert first_task.status_code == 201, first_task.text
    task_id = first_task.json()["id"]

    for user_id, permission in ((2, "editor"), (3, "viewer")):
        response = client.post(
            f"/projects/{project_id}/members",
            json={"user_id": user_id, "permission": permission},
        )
        assert response.status_code == 201, response.text

    current["id"] = 4  # unrelated employee: no project membership
    assert client.get("/projects/").json() == []
    assert client.get(f"/projects/{project_id}").status_code == 404

    current["id"] = 5  # existing elevated Inbox role isn't a project manager
    assert client.get("/projects/").json() == []
    assert client.get(f"/projects/{project_id}").status_code == 404
    assert client.post("/projects/", json={"name": "Unauthorized"}).status_code == 403

    current["id"] = 2  # developer: only assigned project
    assert len(client.get("/projects/").json()) == 1
    assert client.get(f"/projects/{project_id}").status_code == 200
    assert client.post("/projects/", json={"name": "Unauthorized"}).status_code == 403
    assert client.post(
        f"/projects/{project_id}/tasks", json={"title": "Unapproved scope"}
    ).status_code == 403
    assert client.patch(
        f"/projects/{project_id}/tasks/{task_id}", json={"title": "Rewrite the scope"}
    ).status_code == 403
    assert client.patch(
        f"/projects/{project_id}/tasks/{task_id}", json={"status": "done"}
    ).status_code == 200
    comment = client.post(
        f"/projects/{project_id}/tasks/{task_id}/comments",
        json={"body": "The security fix is ready for review."},
    )
    assert comment.status_code == 201, comment.text

    current["id"] = 3  # executive viewer: cannot modify tasks/comments
    detail = client.get(f"/projects/{project_id}")
    assert detail.status_code == 200
    assert detail.json()["progress"] == 100
    assert detail.json()["can_edit"] is False
    assert len(detail.json()["comments"]) == 1
    assert client.patch(
        f"/projects/{project_id}/tasks/{task_id}", json={"status": "todo"}
    ).status_code == 403
    assert client.post(
        f"/projects/{project_id}/tasks/{task_id}/comments",
        json={"body": "Unauthorized comment"},
    ).status_code == 403

    current["id"] = 1
    assert client.delete(f"/projects/{project_id}/members/2").status_code == 200

    current["id"] = 2
    assert client.get(f"/projects/{project_id}").status_code == 404


def test_invalid_links_and_cycles_are_rejected(workspace):
    client, _ = workspace
    p1 = client.post("/projects/", json={"name": "P1"}).json()["id"]
    p2 = client.post("/projects/", json={"name": "P2"}).json()["id"]
    foreign_task = client.post(
        f"/projects/{p2}/tasks", json={"title": "Other project task"}
    ).json()["id"]
    invalid = client.post(
        f"/projects/{p1}/tasks",
        json={"title": "Invalid child", "parent_task_id": foreign_task},
    )
    assert invalid.status_code == 404

    parent = client.post(
        f"/projects/{p1}/tasks", json={"title": "Parent"}
    ).json()["id"]
    child = client.post(
        f"/projects/{p1}/tasks", json={"title": "Child", "parent_task_id": parent}
    ).json()["id"]
    circular = client.patch(
        f"/projects/{p1}/tasks/{parent}", json={"parent_task_id": child}
    )
    assert circular.status_code == 400
    bad_status = client.patch(
        f"/projects/{p1}/tasks/{parent}", json={"status": "oops"}
    )
    assert bad_status.status_code == 400
