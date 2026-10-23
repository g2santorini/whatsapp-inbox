"""End-to-end offline callback tests; no Meta, credentials or customer data."""
import hashlib
from urllib.parse import urlencode

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend.app.instagram_oauth_callback_inbox import (
    InstagramCallbackDenied, _state_digest,
    capture_instagram_authorization_code, create_dormant_callback_router,
)

STATE = "n" * 43
CODE = "synthetic_code_123#_"
NOW = 1792752000


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with engine.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS public"))
        c.execute(text("""
            CREATE TABLE public.sendro_instagram_oauth_challenges (
                state_hash TEXT PRIMARY KEY, tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL, created_epoch INTEGER NOT NULL,
                expires_epoch INTEGER NOT NULL,
                encrypted_authorization_code BLOB NULL,
                received_epoch INTEGER NULL
            )
        """))
        c.execute(text("""
            INSERT INTO public.sendro_instagram_oauth_challenges
                (state_hash, tenant_id, user_id, created_epoch, expires_epoch)
            VALUES (:h, 10, 7, :n, :e)
        """), {"h": _state_digest(STATE), "n": NOW - 5, "e": NOW + 180})
    yield engine
    engine.dispose()


def test_state_hash_identical_to_prior_pr_design():
    assert _state_digest(STATE) == hashlib.sha256(
        ("sendro:instagram:oauth:v1:" + STATE).encode("ascii")
    ).hexdigest()


def test_code_encrypted_and_single_write(db):
    key = Fernet.generate_key().decode("ascii")
    with db.begin() as c:
        capture_instagram_authorization_code(
            c, state=STATE, code=CODE, encryption_key=key, now_epoch=NOW,
        )
    with db.connect() as c:
        row = c.execute(text("""
            SELECT encrypted_authorization_code, received_epoch
            FROM public.sendro_instagram_oauth_challenges
        """)).mappings().one()
    assert row["received_epoch"] == NOW
    assert CODE.encode() not in row["encrypted_authorization_code"]
    assert Fernet(key.encode()).decrypt(row["encrypted_authorization_code"]) == CODE.encode()
    with pytest.raises(InstagramCallbackDenied, match="already received"):
        with db.begin() as c:
            capture_instagram_authorization_code(
                c, state=STATE, code="second_code", encryption_key=key, now_epoch=NOW,
            )


def test_unknown_or_expired_state_no_write(db):
    key = Fernet.generate_key().decode("ascii")
    for state, now in [("z" * 43, NOW), (STATE, NOW + 181)]:
        with pytest.raises(InstagramCallbackDenied):
            with db.begin() as c:
                capture_instagram_authorization_code(
                    c, state=state, code=CODE, encryption_key=key, now_epoch=now,
                )
    with db.connect() as c:
        assert c.execute(text("""
            SELECT encrypted_authorization_code FROM public.sendro_instagram_oauth_challenges
        """)).scalar_one() is None


@pytest.mark.parametrize("bad_code", ["", " ", "foo\nbar", "ä", "x" * 2049])
def test_bad_code_rejected(db, bad_code):
    with pytest.raises(InstagramCallbackDenied):
        with db.begin() as c:
            capture_instagram_authorization_code(
                c, state=STATE, code=bad_code,
                encryption_key=Fernet.generate_key().decode(), now_epoch=NOW,
            )


def client_with_capture(capture):
    app = FastAPI()
    app.include_router(create_dormant_callback_router(capture))
    return TestClient(app)


def test_http_response_redacts_secret_state_and_never_redirects(db):
    secret = "synthetic-secret-do-not-display"
    key = Fernet.generate_key().decode()
    def callback(state, code):
        with db.begin() as c:
            capture_instagram_authorization_code(c, state=state, code=code,
                                                  encryption_key=key, now_epoch=NOW)
    client = client_with_capture(callback)
    response = client.get("/channels/instagram/oauth/callback", params={"state": STATE, "code": CODE})
    assert response.status_code == 200
    assert CODE not in response.text and STATE not in response.text and secret not in response.text
    assert "Location" not in response.headers
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert "<script" not in response.text
    replay = client.get("/channels/instagram/oauth/callback", params={"state": STATE, "code": CODE})
    assert replay.status_code == 400 and CODE not in replay.text


def test_provider_errors_duplicates_and_unexpected_server_error_are_private():
    client = client_with_capture(lambda state, code: (_ for _ in ()).throw(RuntimeError(f"leak {code}")))
    for params, status in [({"state": STATE, "code": CODE}, 503),
                           ({"state": STATE, "error": "access_denied"}, 400),
                           ({"state": STATE, "code": CODE, "error": "access_denied"}, 400),
                           ({"state": STATE, "code": "abc", "error": "x"}, 400)]:
        response = client.get("/channels/instagram/oauth/callback", params=params)
        assert response.status_code == status
        assert "leak" not in response.text and STATE not in response.text and CODE not in response.text
    query = "/channels/instagram/oauth/callback?" + urlencode([("state", STATE), ("code", CODE), ("code", CODE)])
    assert client.get(query).status_code == 400
