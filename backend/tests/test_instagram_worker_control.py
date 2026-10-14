"""Status-only Instagram CLI control; all tests use synthetic in-memory SQLite."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.app import instagram_worker_control
from backend.app.instagram_delivery_worker import InstagramProcessingResult


@pytest.fixture
def engine():
    db = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with db.begin() as cx:
        cx.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        cx.exec_driver_sql("""
            CREATE TABLE public.sendro_channel_webhook_deliveries (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                processing_state TEXT NOT NULL
            )
        """)
        cx.exec_driver_sql("""
            INSERT INTO public.sendro_channel_webhook_deliveries
                (id, provider, processing_state)
            VALUES (1, 'instagram', 'pending'),
                   (2, 'instagram', 'quarantined'),
                   (3, 'whatsapp', 'pending')
        """)
    try:
        yield db
    finally:
        db.dispose()


def test_status_is_read_only_and_aggregated(engine):
    result = instagram_worker_control.execute_control(
        engine, environ={}
    )
    assert result == {
        "mode": "status",
        "queue": {"pending": 1, "quarantined": 1},
    }
    with engine.connect() as cx:
        assert cx.exec_driver_sql(
            "SELECT COUNT(*) FROM public.sendro_channel_webhook_deliveries"
        ).scalar_one() == 3


@pytest.mark.parametrize("env,phrase", [
    ({}, None),
    ({"INSTAGRAM_WORKER_MANUAL_ENABLED": "false"}, instagram_worker_control.CONFIRM_PHRASE),
    ({"INSTAGRAM_WORKER_MANUAL_ENABLED": "true"}, None),
    ({"INSTAGRAM_WORKER_MANUAL_ENABLED": "true"}, "wrong"),
])
def test_manual_worker_cannot_run_without_two_independent_gates(
    engine, monkeypatch, env, phrase
):
    called = []
    monkeypatch.setattr(
        instagram_worker_control, "process_one_pending_instagram_delivery",
        lambda *args: called.append(args),
    )
    with pytest.raises(PermissionError):
        instagram_worker_control.execute_control(
            engine, run_one=True, confirmation=phrase, environ=env
        )
    assert called == []


def test_manual_worker_requires_key_even_if_unlocked(engine, monkeypatch):
    called = []
    monkeypatch.setattr(
        instagram_worker_control, "process_one_pending_instagram_delivery",
        lambda *args: called.append(args),
    )
    with pytest.raises(ValueError):
        instagram_worker_control.execute_control(
            engine, run_one=True,
            confirmation=instagram_worker_control.CONFIRM_PHRASE,
            environ={"INSTAGRAM_WORKER_MANUAL_ENABLED": "true"},
        )
    assert called == []


def test_explicit_manual_single_delivery_makes_exactly_one_worker_call(engine, monkeypatch):
    called = []
    def fake_process(db, key):
        called.append((db, key))
        return InstagramProcessingResult(delivery_id=99, status="processed", inserted_messages=2)

    monkeypatch.setattr(
        instagram_worker_control, "process_one_pending_instagram_delivery", fake_process
    )
    result = instagram_worker_control.execute_control(
        engine, run_one=True,
        confirmation=instagram_worker_control.CONFIRM_PHRASE,
        environ={
            "INSTAGRAM_WORKER_MANUAL_ENABLED": "true",
            "INSTAGRAM_WEBHOOK_ENCRYPTION_KEY": "test-placeholder-not-shared",
        },
    )
    assert result == {
        "mode": "run-one",
        "status": "processed",
        "inserted_messages": 2,
    }
    assert len(called) == 1
    assert called[0][0] is engine


def test_cli_refuses_manual_operation_before_loading_db(monkeypatch, capsys):
    monkeypatch.delenv("INSTAGRAM_WORKER_MANUAL_ENABLED", raising=False)
    result = instagram_worker_control.main([
        "--run-one", "--confirm", instagram_worker_control.CONFIRM_PHRASE
    ])
    assert result == 2
    assert "LOCKED" in capsys.readouterr().out
