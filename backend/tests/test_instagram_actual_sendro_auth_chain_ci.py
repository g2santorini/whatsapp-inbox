"""Real Sendro auth-function regression proof, isolated from main startup.

Test the EXACT get_current_user/get_current_active_user function bodies
extracted with Python AST from backend/app/main.py. Importing main directly
would execute startup/database initialization; this safe test NEVER does.
Mock only their surrounding dependencies and keep the users in a disposable
in-memory SQLite DB. The Incident Center and incident records still live
ONLY in the separately gated GitHub Actions ephemeral PostgreSQL fixture.

No production tokens, users, Render DB, Meta API or live notifications.
"""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.testclient import TestClient
from jose import JWTError, jwt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.instagram_incident_center_ci_api import (
    create_ci_instagram_incident_center_router,
)
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


TEST_SECRET = "synthetic-ci-auth-chain-key-no-live-Sendro-secret"
TEST_ALGORITHM = "HS256"
SOURCE = Path(__file__).parents[1] / "app" / "main.py"


def load_real_sendro_auth_functions(user_lookup):
    """Compile ONLY two original async function definitions; no main import.

    This is an executable regression check of source behavior, not an
    independently authenticated new production endpoint. Real integration
    must inject the already-created production dependencies directly.
    """
    parsed = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    original = [
        n for n in parsed.body
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name in ("get_current_user", "get_current_active_user")
    ]
    if {n.name for n in original} != {
        "get_current_user", "get_current_active_user",
    }:
        raise AssertionError("Actual Sendro auth functions moved or changed shape")

    # Use only selected function bodies, never app initialization or a real
    # DATABASE_URL from this module.
    isolated = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[
                ast.alias(name="annotations")
            ], level=0),
            *original,
        ], type_ignores=[],
    )
    namespace = {
        "jwt": jwt, "JWTError": JWTError, "HTTPException": HTTPException,
        "status": status, "SECRET_KEY": TEST_SECRET,
        "ALGORITHM": TEST_ALGORITHM, "get_user": user_lookup,
        "TokenData": SimpleNamespace,
    }
    exec(compile(ast.fix_missing_locations(isolated), str(SOURCE), "exec"),
         namespace)
    return namespace["get_current_user"], namespace["get_current_active_user"]


def _make_token(username="ci-admin", *, version=1, mfa=True,
                mfa_age=0, claim_role=None):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": username,
        "ver": version,
        "exp": int((now + timedelta(minutes=20)).timestamp()),
    }
    if claim_role is not None:
        claims["role"] = claim_role  # untrusted; DB role must win.
    if mfa:
        claims = add_recent_mfa_claim(
            claims, now - timedelta(seconds=mfa_age),
        )
    return {"Authorization": "Bearer " + jwt.encode(
        claims, TEST_SECRET, algorithm=TEST_ALGORITHM,
    )}


@pytest.fixture
def real_auth_center(episode_db):
    incident_engine, key = episode_db
    now = datetime.now(timezone.utc) + timedelta(seconds=5)
    quarantine(incident_engine, key, "ci-real-sendro-auth-chain")
    assert observation(incident_engine, now)["new_episodes"] == 1
    grant(incident_engine, 11, now, role="incident_admin")
    grant(incident_engine, 12, now, role="incident_responder")

    # This is a standalone local MEMORY database, not Sendro public.users.
    auth_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with auth_engine.begin() as db:
        db.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                role TEXT NOT NULL, disabled BOOLEAN NOT NULL,
                mfa_enabled BOOLEAN NOT NULL,
                auth_version INTEGER NOT NULL,
                must_change_password BOOLEAN NOT NULL
            )
        """))
        for uid, username, role, disabled, mfa_enabled, version, must_change in (
            (11, "ci-admin", "admin", False, True, 1, False),
            (12, "ci-operator", "operator", False, True, 1, False),
            (13, "ci-unlisted-admin", "admin", False, True, 1, False),
            (14, "ci-disabled", "admin", True, True, 1, False),
            (15, "ci-mfa-off", "admin", False, False, 1, False),
            (16, "ci-reset", "admin", False, True, 1, True),
            (17, "ci-developer", "developer", False, True, 1, False),
        ):
            db.execute(text("""
                INSERT INTO users (
                    id, username, role, disabled, mfa_enabled,
                    auth_version, must_change_password
                ) VALUES (
                    :id, :username, :role, :disabled, :mfa,
                    :version, :must_change
                )
            """), dict(id=uid, username=username, role=role,
                       disabled=disabled, mfa=mfa_enabled,
                       version=version, must_change=must_change))
    factory = sessionmaker(bind=auth_engine)

    def lookup(db, *, username):
        row = db.execute(text("""
            SELECT id, username, role, disabled, mfa_enabled,
                   auth_version, must_change_password
            FROM users WHERE username = :username
        """), {"username": username}).mappings().one_or_none()
        if row is None:
            return None
        record = dict(row)
        record["disabled"] = bool(record["disabled"])
        record["mfa_enabled"] = bool(record["mfa_enabled"])
        record["must_change_password"] = bool(record["must_change_password"])
        record["mfa_setup_required"] = (
            record["role"] == "admin" and not record["mfa_enabled"]
        )
        return SimpleNamespace(**record)

    source_get_user, source_active_user = load_real_sendro_auth_functions(
        lookup
    )
    bearer = OAuth2PasswordBearer(tokenUrl="/token")

    def local_db():
        with factory() as session:
            yield session

    async def verified_admin(
        request: Request,
        token: str = Depends(bearer),
        db=Depends(local_db),
    ):
        # EXACT original main.py token-version + DB principal evaluation.
        principal = await source_get_user(token, db)
        # EXACT original main.py disabled/password/MFA setup /project-role
        # restrictions, then actual signed recent MFA helper.
        principal = await source_active_user(request, principal)
        return require_recent_mfa_token(
            principal, token=token, secret_key=TEST_SECRET,
            algorithm=TEST_ALGORITHM,
        )

    def ci_incident_db():
        return incident_engine

    test_app = FastAPI()
    test_app.include_router(create_ci_instagram_incident_center_router(
        verified_admin, ci_incident_db, environ=flags(),
    ))
    with TestClient(test_app, raise_server_exceptions=False) as client:
        yield client, auth_engine, incident_engine, now
    auth_engine.dispose()


def incident_url():
    return "/ci/instagram/incidents"


def test_real_sendro_source_auth_and_recent_mfa_allow_only_delegated_admin(
    real_auth_center,
):
    client, auth_engine, incident_engine, now = real_auth_center
    res = client.get(incident_url(), headers=_make_token())
    assert res.status_code == 200, res.text
    assert res.json() == [{
        "code": "quarantined_deliveries",
        "episode": 1,
        "is_active": True,
        "observations": 1,
        "dispatch_status": "pending",
    }]
    # The database role beats any forged/synthetic JWT role claim.
    denied = client.get(incident_url(), headers=_make_token(
        username="ci-operator", claim_role="admin",
    ))
    assert denied.status_code == 403
    # A legitimately signed admin still needs the EXTRA global grant.
    assert client.get(
        incident_url(), headers=_make_token(username="ci-unlisted-admin"),
    ).status_code == 403


def test_revoking_sendro_auth_version_invalidates_signed_incident_session(
    real_auth_center,
):
    client, auth_engine, incident_engine, now = real_auth_center
    old_token = _make_token(version=1)
    assert client.get(incident_url(), headers=old_token).status_code == 200
    with auth_engine.begin() as db:
        db.execute(text("""
            UPDATE users SET auth_version = 2 WHERE username = 'ci-admin'
        """))
    assert client.get(incident_url(), headers=old_token).status_code == 401
    assert client.post(
        incident_url() + "/quarantined_deliveries/acknowledge",
        headers=old_token,
        json={"episode": 1,
              "confirmation": "I_REVIEWED_THIS_SYNTHETIC_INSTAGRAM_ALERT"},
    ).status_code == 401
    assert client.get(
        incident_url(), headers=_make_token(version=2),
    ).status_code == 200
    assert audit_rows(incident_engine) == []


def test_role_demoted_or_disabled_after_login_immediately_denied(
    real_auth_center,
):
    client, auth_engine, incident_engine, now = real_auth_center
    cached_token = _make_token()
    with auth_engine.begin() as db:
        db.execute(text("""
            UPDATE users SET role = 'operator'
            WHERE username = 'ci-admin'
        """))
    assert client.get(incident_url(), headers=cached_token).status_code == 403
    with auth_engine.begin() as db:
        db.execute(text("""
            UPDATE users SET role = 'admin', disabled = TRUE
            WHERE username = 'ci-admin'
        """))
    assert client.get(incident_url(), headers=cached_token).status_code == 400
    assert audit_rows(incident_engine) == []


@pytest.mark.parametrize("username,expected", [
    ("ci-disabled", 400),
    ("ci-mfa-off", 403),
    ("ci-reset", 403),
    ("ci-developer", 403),
])
def test_original_active_user_rules_block_ineligible_staff(
    real_auth_center, username, expected,
):
    client, auth_engine, incident_engine, now = real_auth_center
    assert client.get(
        incident_url(), headers=_make_token(username=username),
    ).status_code == expected
    assert audit_rows(incident_engine) == []


def test_missing_stale_and_bogus_mfa_cannot_read_or_confirm(
    real_auth_center,
):
    client, auth_engine, incident_engine, now = real_auth_center
    for invalid in (
        _make_token(mfa=False),
        _make_token(mfa_age=900),
        {"Authorization": "Bearer invalid-token"},
    ):
        assert client.get(
            incident_url(), headers=invalid,
        ).status_code in (401, 403)
        assert client.post(
            incident_url() + "/quarantined_deliveries/acknowledge",
            headers=invalid,
            json={"episode": 1,
                  "confirmation": "I_REVIEWED_THIS_SYNTHETIC_INSTAGRAM_ALERT"},
        ).status_code in (401, 403)
    assert audit_rows(incident_engine) == []


def test_real_auth_chain_audits_exact_approved_incident_after_acceptance(
    real_auth_center,
):
    client, auth_engine, incident_engine, now = real_auth_center
    assert client.post(
        incident_url() + "/quarantined_deliveries/acknowledge",
        headers=_make_token(),
        json={"episode": 1,
              "confirmation": "I_REVIEWED_THIS_SYNTHETIC_INSTAGRAM_ALERT"},
    ).status_code == 409
    assert attempt_ci_alert_delivery(
        incident_engine, lambda _: True,
        environ=flags(), now=now + timedelta(seconds=1),
    ) == "accepted"
    confirmed = client.post(
        incident_url() + "/quarantined_deliveries/acknowledge",
        headers=_make_token(),
        json={"episode": 1,
              "confirmation": "I_REVIEWED_THIS_SYNTHETIC_INSTAGRAM_ALERT"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert len(audit_rows(incident_engine)) == 1
    assert audit_rows(incident_engine)[0]["actor_user_id"] == 11
    assert client.post(
        incident_url() + "/quarantined_deliveries/acknowledge",
        headers=_make_token(),
        json={"episode": 1,
              "confirmation": "I_REVIEWED_THIS_SYNTHETIC_INSTAGRAM_ALERT"},
    ).status_code == 409


def test_tests_do_not_import_production_main_or_mount_live_router():
    code = SOURCE.read_text(encoding="utf-8")
    # Fail the review if somebody registers test Incident Center in the
    # production app. The source test deliberately extracts ONLY auth funcs.
    assert "instagram_incident_center_ci_api" not in code
    assert "create_ci_instagram_incident_center_router" not in code
    functions = ast.parse(code)
    actual = {node.name for node in functions.body
              if isinstance(node, ast.AsyncFunctionDef)}
    assert "get_current_user" in actual
    assert "get_current_active_user" in actual
