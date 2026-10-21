"""Explicitly mounted *test-only* Incident Center HTTP contract.

Uses the actual Sendro recent-MFA JWT validator with a generated synthetic
test signing key. The route factory is deliberately absent from main.py.
Database operations only in ephemeral GitHub Actions PostgreSQL, guarded
by the upstream fixture and runtime engine allowlist. No real staff tokens.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import time

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from jose import JWTError, jwt
from sqlalchemy import create_engine

from backend.app.instagram_incident_center_ci_api import (
    create_ci_instagram_incident_center_router,
)
from backend.app.instagram_alert_outbox_ci import InstagramAlertOutboxDisabled
from backend.app.privacy_mfa_session import (
    add_recent_mfa_claim, require_recent_mfa_token,
)
from backend.tests.test_instagram_alert_episodes_ack_ci import (
    episode_db, flags, grant, observation, quarantine, audit_rows,
)
from backend.tests.test_instagram_alert_dispatch_ci import (
    ci_dispatch, attempt_ci_alert_delivery,
)
from backend.tests.test_instagram_alert_outbox_ci import ci_alerts
from backend.tests.test_instagram_postgres_supervision_ci import ci_supervisor
from backend.tests.test_instagram_manual_migrations_postgres import replay_engine


SIGNING_KEY = "CI-only-Instagram-incident-center-JWT-never-a-Render-secret"
ALGORITHM = "HS256"
bearer = HTTPBearer()


def actor(uid, role, *, disabled=False, mfa=True):
    return SimpleNamespace(
        id=uid, username=f"ci-actor-{uid}", role=role,
        disabled=disabled, mfa_enabled=mfa,
    )


ACTORS = {
    101: actor(101, "admin"),
    102: actor(102, "admin"),
    103: actor(103, "operator"),
    104: actor(104, "viewer"),
    105: actor(105, "admin", disabled=True),
    106: actor(106, "admin", mfa=False),
    107: actor(107, "admin"),
    108: actor(108, "developer"),
    109: actor(109, "admin"),
}


def verified_ci_user(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    try:
        claims = jwt.decode(
            creds.credentials, SIGNING_KEY, algorithms=[ALGORITHM],
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid CI session") from None
    username = claims.get("sub")
    user = next((u for u in ACTORS.values() if u.username == username), None)
    if user is None or user.disabled:
        raise HTTPException(status_code=403, detail="User inactive")
    # REAL Sendro 10-minute recent signed-MFA guard, with fake CI JWTs.
    return require_recent_mfa_token(
        user, token=creds.credentials,
        secret_key=SIGNING_KEY, algorithm=ALGORITHM,
    )


def token(uid=101, *, verified=True, age_seconds=0):
    now = datetime.now(timezone.utc)
    data = {
        "sub": ACTORS[uid].username,
        "exp": int((now + timedelta(minutes=20)).timestamp()),
    }
    if verified:
        data = add_recent_mfa_claim(
            data, now - timedelta(seconds=age_seconds),
        )
    return {"Authorization": "Bearer " + jwt.encode(
        data, SIGNING_KEY, algorithm=ALGORITHM,
    )}


@pytest.fixture
def center(episode_db):
    engine, key = episode_db
    now = datetime.now(timezone.utc) + timedelta(seconds=5)
    quarantine(engine, key, "ci-inapp-alert-1")
    assert observation(engine, now)["new_episodes"] == 1
    # Only 101 has explicit global, active, nonexpired responder grant.
    grant(engine, 101, now, role="incident_admin")
    grant(engine, 103, now, role="incident_responder")
    grant(engine, 104, now, role="incident_responder")
    grant(engine, 105, now, role="incident_admin")
    grant(engine, 106, now, role="incident_admin")
    grant(engine, 107, now, role="incident_admin", expiration=-20)
    grant(engine, 108, now, role="incident_admin")
    grant(engine, 109, now, role="incident_admin", scope="tenant")

    app = FastAPI()
    def test_ci_engine():
        return engine

    app.include_router(create_ci_instagram_incident_center_router(
        verified_ci_user, test_ci_engine, environ=flags(),
    ))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, engine, now


def ack(client, uid=101, *, episode=1, phrase="I_REVIEWED_THIS_SYNTHETIC_INSTAGRAM_ALERT"):
    return client.post(
        "/ci/instagram/incidents/quarantined_deliveries/acknowledge",
        headers=token(uid), json={"episode": episode, "confirmation": phrase},
    )


def test_global_incident_list_is_redacted_and_not_visible_to_every_inbox_user(center):
    client, engine, now = center
    r = client.get("/ci/instagram/incidents", headers=token())
    assert r.status_code == 200, r.text
    assert r.json() == [{
        "code": "quarantined_deliveries",
        "episode": 1,
        "is_active": True,
        "observations": 1,
        "dispatch_status": "pending",
    }]
    response = r.text
    for forbidden in (
        "ci-inapp-alert-1", "nonexistent-ci-business",
        "customer_id", "raw_body_sha256", "payload_ciphertext",
        "actor_user_id", "lease_token",
    ):
        assert forbidden not in response


@pytest.mark.parametrize("uid", [102, 103, 104, 105, 106, 107, 108, 109])
def test_global_incidents_denied_even_with_wrong_user_role_or_grant(center, uid):
    client, engine, now = center
    view = client.get("/ci/instagram/incidents", headers=token(uid))
    assert view.status_code == 403
    mutate = ack(client, uid)
    assert mutate.status_code == 403
    assert audit_rows(engine) == []


def test_recent_signed_mfa_required_for_incident_read_and_ack(center):
    client, engine, now = center
    for bad in (
        token(101, verified=False),
        token(101, age_seconds=700),
        {"Authorization": "Bearer fabricated-invalid-jwt"},
    ):
        assert client.get(
            "/ci/instagram/incidents", headers=bad,
        ).status_code in (401, 403)
        assert client.post(
            "/ci/instagram/incidents/quarantined_deliveries/acknowledge",
            headers=bad, json={
                "episode": 1,
                "confirmation": "I_REVIEWED_THIS_SYNTHETIC_INSTAGRAM_ALERT",
            },
        ).status_code in (401, 403)
    assert client.get("/ci/instagram/incidents").status_code in (401, 403)
    assert audit_rows(engine) == []


def test_authenticated_ack_requires_transport_acceptance_exact_episode_and_audit(center):
    client, engine, now = center
    assert ack(client).status_code == 409  # notification not accepted
    assert audit_rows(engine) == []
    events = []
    assert attempt_ci_alert_delivery(
        engine, lambda event: (events.append(event), True)[-1],
        environ=flags(), now=now + timedelta(seconds=1),
    ) == "accepted"
    assert events == [{"code": "quarantined_deliveries", "observations": 1}]
    assert ack(client, episode=2).status_code == 409
    assert ack(client, phrase="CLICK").status_code == 422
    assert client.post(
        "/ci/instagram/incidents/quarantined_deliveries/acknowledge",
        headers=token(), json={
            "episode": 1,
            "confirmation": "I_REVIEWED_THIS_SYNTHETIC_INSTAGRAM_ALERT",
            "customer_id": "forbidden",
        },
    ).status_code == 422
    success = ack(client)
    assert success.status_code == 200, success.text
    assert success.json() == {"acknowledged": True}
    assert ack(client).status_code == 409
    audit = audit_rows(engine)
    assert len(audit) == 1
    assert audit[0]["actor_user_id"] == 101
    after = client.get("/ci/instagram/incidents", headers=token())
    assert after.json()[0]["dispatch_status"] == "acknowledged"


def test_injected_wrong_db_is_rejected_before_query_and_router_not_live(center):
    client, engine, now = center
    invalid = create_engine(
        "postgresql+psycopg://fake:fake@render.invalid:5432/sendro"
    )  # constructing a SQLAlchemy engine does NOT open a network connection
    try:
        def invalid_db():
            return invalid
        api = FastAPI()
        api.include_router(create_ci_instagram_incident_center_router(
            verified_ci_user, invalid_db, environ=flags(),
        ))
        with TestClient(api, raise_server_exceptions=False) as bogus:
            r = bogus.get("/ci/instagram/incidents", headers=token())
            assert r.status_code == 500  # fail-closed, no actual DB query
            assert "customer" not in r.text.lower()
    finally:
        invalid.dispose()

    main_file = Path(__file__).parents[1] / "app" / "main.py"
    main_code = main_file.read_text(encoding="utf-8")
    assert "instagram_incident_center_ci_api" not in main_code
    assert "create_ci_instagram_incident_center_router" not in main_code
