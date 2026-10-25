"""No-network Graph token adapter tests with mocked response/transport."""
from pathlib import Path
import pytest
import requests
from backend.app import instagram_token_lifecycle as lifecycle
from backend.app.instagram_oauth_http_security import InstagramOAuthLogAttestations

def approved():
    # FAKE attestation for mocked CI transport ONLY; not a release approval.
    return InstagramOAuthLogAttestations(**{
        field: True for field in InstagramOAuthLogAttestations.__dataclass_fields__
    })

def exchange(**kwargs):
    return lifecycle.exchange_instagram_long_lived(
        **kwargs, egress_approval=approved(),
    )

def refresh(**kwargs):
    return lifecycle.refresh_instagram_long_lived(
        **kwargs, egress_approval=approved(),
    )

TOKEN = "synthetic-short-lived-ig-token"
SECRET = "synthetic-secret-NEVER-real"


class Response:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.body = body if body is not None else {
            "access_token": "synthetic-long-lived-ig-token",
            "token_type": "bearer", "expires_in": 5183999,
        }

    def json(self):
        return self.body


class Session:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or Response()

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.response


def test_exchange_uses_fixed_graph_host_and_exact_scope():
    session = Session()
    token = exchange(
        short_lived_token=TOKEN, instagram_app_secret=SECRET, session=session)
    assert token.expires_in_seconds == 5183999
    assert token.access_token not in repr(token) and token.access_token not in str(token)
    url, kw = session.calls[0]
    assert url == "https://graph.instagram.com/access_token"
    assert kw["params"] == {
        "grant_type": "ig_exchange_token", "client_secret": SECRET,
        "access_token": TOKEN}
    assert kw["allow_redirects"] is False and kw["timeout"] <= 10
    assert SECRET not in url


def test_refresh_does_not_send_app_secret_or_old_facebook_grant_type():
    session = Session()
    refresh(long_lived_token=TOKEN, session=session)
    url, kw = session.calls[0]
    assert url == "https://graph.instagram.com/refresh_access_token"
    assert kw["params"] == {"grant_type": "ig_refresh_token", "access_token": TOKEN}
    assert "client_secret" not in kw["params"]


@pytest.mark.parametrize("bad", [
    {"access_token": "tok", "expires_in": 5184000},
    {"access_token": "synthetic-long-token", "expires_in": True},
    {"access_token": "synthetic-long-token", "expires_in": 0},
    {"access_token": "synthetic-long-token", "expires_in": 63*86400},
    {"access_token": "synthetic-long-token", "expires_in": 5184000,
     "token_type": "non-bearer"},
    ["weird"],
])
def test_provider_malformed_responses_fail_closed(bad):
    with pytest.raises(lifecycle.InstagramTokenLifecycleError):
        exchange(
            short_lived_token=TOKEN, instagram_app_secret=SECRET,
            session=Session(Response(body=bad)))


def test_provider_error_bodies_are_not_reflected():
    response = Response(status=400, body={"error": "BAD " + SECRET + TOKEN})
    with pytest.raises(lifecycle.InstagramTokenLifecycleError) as exc:
        exchange(
            short_lived_token=TOKEN, instagram_app_secret=SECRET,
            session=Session(response))
    assert SECRET not in str(exc.value) and TOKEN not in str(exc.value)


def test_invalid_inputs_fail_before_network():
    session = Session()
    for short in ["", "x", "line\nbreak", "a"*9000]:
        with pytest.raises(lifecycle.InstagramTokenLifecycleError):
            exchange(
                short_lived_token=short, instagram_app_secret=SECRET, session=session)
    assert session.calls == []


def test_transport_error_sanitized():
    class TimeoutSession:
        def get(self,*args,**kwargs):
            raise requests.Timeout("synthetic-secret-should-not-log")
    with pytest.raises(lifecycle.InstagramTokenLifecycleError) as exc:
        refresh(
            long_lived_token=TOKEN, session=TimeoutSession())
    assert "should-not-log" not in str(exc.value)


def test_unmounted_adapter_isnt_used_by_sendro_main():
    source = (Path(__file__).parents[1]/"app"/"main.py").read_text(encoding="utf-8")
    assert "instagram_token_lifecycle" not in source

def test_default_denies_all_graph_requests_before_network():
    session = Session()
    with pytest.raises(Exception, match="network access blocked"):
        lifecycle.exchange_instagram_long_lived(
            short_lived_token=TOKEN, instagram_app_secret=SECRET, session=session)
    with pytest.raises(Exception, match="network access blocked"):
        lifecycle.refresh_instagram_long_lived(
            long_lived_token=TOKEN, session=session)
    assert session.calls == []
