"""Authenticated WhatsApp preview used by the Projects companion panel."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./sendro_live_panel_test_unused.sqlite3")
os.environ.setdefault("SECRET_KEY", "test-only-ci-secret-for-live-panel")

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base, get_db
from backend.app import models, project_models, task_models
from backend.app.main import app, get_current_user


def test_whatsapp_live_panel_requires_messaging_role_and_returns_real_preview():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)

    with SessionFactory() as db:
        db.add_all([
            models.User(
                id=1, username="manager", email="manager@example.test",
                hashed_password="test", role="admin", disabled=False, mfa_enabled=True
            ),
            models.User(
                id=2, username="developer", email="developer@example.test",
                hashed_password="test", role="developer", disabled=False
            ),
            models.User(
                id=3, username="viewer", email="viewer@example.test",
                hashed_password="test", role="project_viewer", disabled=False
            ),
        ])
        db.flush()
        db.add_all([
            models.Conversation(
                id=101, contact_name="Test Guest", contact_phone="+306900000001",
                status="open", unread_count=2, user_id=1
            ),
            models.Conversation(
                id=102, contact_name="Archived Guest", contact_phone="+306900000002",
                status="archived", unread_count=8, user_id=1
            ),
        ])
        db.flush()
        db.add_all([
            models.Message(
                conversation_id=101, user_id=1, direction="inbound",
                content="Earlier question", is_read=False
            ),
            models.Message(
                conversation_id=101, user_id=1, direction="inbound",
                content="Could you confirm the pickup time?", is_read=False
            ),
            models.Message(
                conversation_id=102, user_id=1, direction="inbound",
                content="Archived message", is_read=False
            ),
        ])
        db.commit()

    current = {"user_id": 1}

    def testing_db():
        with SessionFactory() as db:
            yield db

    def testing_user():
        with SessionFactory() as db:
            user = db.get(models.User, current["user_id"])
            db.expunge(user)
            return user

    original = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = testing_db
    app.dependency_overrides[get_current_user] = testing_user
    try:
        with TestClient(app) as client:
            response = client.get("/conversations/live-panel/")
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["summary"]["inbox_unread_conversations"] == 1
            assert data["summary"]["unread_messages"] == 2
            assert len(data["unread"]) == 1
            assert data["unread"][0]["contact_name"] == "Test Guest"
            assert data["unread"][0]["last_message_preview"] == "Could you confirm the pickup time?"
            assert data["unread"][0]["contact_phone"] == "+306900000001"
            assert all(x["id"] != 102 for x in data["recent"])
            for role_user_id in (2, 3):
                current["user_id"] = role_user_id
                forbidden = client.get("/conversations/live-panel/")
                assert forbidden.status_code == 403
    finally:
        app.dependency_overrides = original
        engine.dispose()
