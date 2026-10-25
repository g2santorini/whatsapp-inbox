"""Pure/fully mocked Instagram Business Login protocol tests. No Meta calls."""
import inspect
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app import instagram_login_oauth as ig
from backend.app.instagram_oauth_http_security import InstagramOAuthLogAttestations

def approved():
    # Mock-only test attestation. Production operational checks are NOT done.
    return InstagramOAuthLogAttestations(**{
        field: True for field in InstagramOAuthLogAttestations.__dataclass_fields__
    })

def short(**kw):
    return ig.exchange_short_lived_token(**kw, egress_approval=approved())

def fetch_profile(**kw):
    return ig.fetch_authorized_profile(**kw, egress_approval=approved())


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload or {}

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return self.response

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return self.response


def test_authorize_url_uses_new_instagram_login_scopes_only():
    state = ig.new_state()
    url = ig.build_authorize_url(
        app_id="1234567890", redirect_uri=ig.STAGING_CALLBACK, state=state,
    )
    assert urlsplit(url).hostname == "www.instagram.com"
    query = parse_qs(urlsplit(url).query)
    assert query == {
        "client_id": ["1234567890"], "redirect_uri": [ig.STAGING_CALLBACK],
        "response_type": ["code"], "scope": ["instagram_business_basic,instagram_business_manage_messages"],
        "state": [state],
    }
    assert ig.verify_state(state, state)
    assert not ig.verify_state(state, ig.new_state())
    assert "client_secret" not in url and "access_token" not in url


@pytest.mark.parametrize("bad_uri", [
    "http://sendro-backend-staging.onrender.com/channels/instagram/oauth/callback",
    "https://attacker.example/channels/instagram/oauth/callback",
    ig.STAGING_CALLBACK + "?go=https://evil.example", ig.STAGING_CALLBACK + "/",
])
def test_redirect_rejected_before_network(bad_uri):
    with pytest.raises(ig.InstagramLoginError):
        ig.build_authorize_url(app_id="1234567890", redirect_uri=bad_uri, state=ig.new_state())
    with pytest.raises(ig.InstagramLoginError):
        short(
            app_id="1234567890", app_secret="fake", code="fake",
            redirect_uri=bad_uri, session=FakeSession(FakeResponse()),
        )


def test_token_exchange_is_server_only_and_never_redirects():
    secret = "synthetic-do-not-log"
    token = "synthetic-short-lived-token-only"
    session = FakeSession(FakeResponse(payload={"access_token": token, "user_id": 17841402010000000}))
    result = short(
        app_id="1234567890", app_secret=secret, code="synthetic-code",
        redirect_uri=ig.STAGING_CALLBACK, session=session,
    )
    assert result.access_token == token
    assert result.instagram_user_id == "17841402010000000"
    method, url, args = session.calls[0]
    assert method == "post" and url == ig.INSTAGRAM_TOKEN
    assert args["timeout"] <= 10 and args["allow_redirects"] is False
    assert args["data"]["client_secret"] == secret
    assert secret not in url


def test_failed_exchange_redacts_credential_bearing_meta_response():
    secret = "synthetic-supersecret"
    session = FakeSession(FakeResponse(400, {"error": f"{secret} token rejected"}))
    with pytest.raises(ig.InstagramLoginError) as err:
        short(
            app_id="1234567890", app_secret=secret, code="badcode",
            redirect_uri=ig.STAGING_CALLBACK, session=session,
        )
    assert secret not in str(err.value) and "token rejected" not in str(err.value)


def test_profile_query_is_read_only_and_omits_messages():
    token = "synthetic-profile-token"
    session = FakeSession(FakeResponse(payload={
        "user_id": "17841402010000000", "username": "synthetic_ig",
        "account_type": "BUSINESS", "profile_picture_url": "https://images.example/ig.jpg",
    }))
    profile = fetch_profile(access_token=token, session=session)
    assert profile.username == "synthetic_ig"
    method, url, args = session.calls[0]
    assert method == "get" and url == ig.INSTAGRAM_PROFILE
    assert "messages" not in str(args)
    assert args["headers"]["Authorization"] == "Bearer " + token
    assert args["allow_redirects"] is False


def test_dormant_module_exposes_no_fastapi_route_or_worker():
    source = inspect.getsource(ig)
    for forbidden in ("@router", "FastAPI(", "create_engine", "SessionLocal",
                      "INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "send_whatsapp_",
                      "include_router", "setenv("):
        assert forbidden not in source

def test_meta_short_exchange_and_profile_default_block_before_network():
    session = FakeSession(FakeResponse(payload={
        "access_token": "fake-verified-token", "user_id": "12345678"}))
    with pytest.raises(Exception, match="network access blocked"):
        ig.exchange_short_lived_token(
            app_id="1234567890", app_secret="synthetic-secret",
            code="synthetic-code", redirect_uri=ig.STAGING_CALLBACK,
            session=session)
    with pytest.raises(Exception, match="network access blocked"):
        ig.fetch_authorized_profile(
            access_token="synthetic-access-token", session=session)
    assert session.calls == []
