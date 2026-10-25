"""No-network assertions for the dedicated Meta-only transport.

No Render, Meta, proxy or staging request is performed. Env proxy and
NETRC values are synthetic. Mock the base Requests send mechanism to test
the real Session subclass without permitting actual socket activity.
"""
from pathlib import Path

import pytest
import requests

from backend.app.instagram_meta_transport import (
    InstagramMetaTransportDenied,
    instagram_meta_session,
)
from backend.app.instagram_oauth_http_security import InstagramOAuthLogAttestations
from backend.app.instagram_token_lifecycle import exchange_instagram_long_lived
from backend.app.instagram_login_oauth import (
    STAGING_CALLBACK, exchange_short_lived_token,
)

URL = "https://graph.instagram.com/access_token"
TOKEN = "SYNTHETIC_META_TOKEN_USED_IN_TESTS"
SECRET = "SYNTHETIC_META_SECRET_USED_IN_TESTS"


def approved_only_in_ci():
    """Not a real operational attestation; all transport requests are mocked."""
    return InstagramOAuthLogAttestations(**{
        key: True for key in InstagramOAuthLogAttestations.__dataclass_fields__
    })


def test_real_session_ignores_env_proxy_netrc_and_closes(monkeypatch, tmp_path):
    netrc = tmp_path / "test_only.netrc"
    netrc.write_text("machine graph.instagram.com login stolen password fake\n")
    monkeypatch.setenv("HTTPS_PROXY", "http://synthetic-proxy.invalid:8888")
    monkeypatch.setenv("ALL_PROXY", "http://synthetic-other-proxy.invalid:7777")
    monkeypatch.setenv("NETRC", str(netrc))
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/tmp/unsafe-synthetic-ca.pem")
    with instagram_meta_session() as transport:
        assert isinstance(transport, requests.Session)
        assert transport.trust_env is False
        assert transport.proxies == {}
        assert transport.auth is None
        assert transport.verify is True
        assert transport.max_redirects == 0
        assert transport.hooks == {"response": []}
        assert transport.cookies.get_dict() == {}
        assert "http://" not in transport.adapters
        with pytest.raises(requests.exceptions.InvalidSchema):
            transport.get_adapter("http://graph.instagram.com")
        settings = transport.merge_environment_settings(
            URL, {}, None, None, None)
        assert settings["proxies"] == {}
        assert settings["verify"] is True
        assert transport.prepare_request(
            requests.Request("GET", URL)).headers.get("Authorization") is None


@pytest.mark.parametrize("method,url,kwargs", [
    ("GET", "http://graph.instagram.com/access_token", {}),
    ("GET", "https://evil.example/access_token", {}),
    ("GET", URL + "?access_token=secrets", {}),
    ("GET", "https://graph.instagram.com/access_token#fragment", {}),
    ("POST", URL, {}),
    ("GET", "https://graph.instagram.com/me/", {}),
    ("DELETE", "https://graph.instagram.com/me", {}),
    ("GET", "https://api.instagram.com/oauth/access_token", {}),
    ("GET", URL, {"allow_redirects": True}),
    ("GET", URL, {"allow_redirects": None}),
    ("GET", URL, {"timeout": 0}),
    ("GET", URL, {"timeout": 99}),
    ("GET", URL, {"timeout": True}),
    ("GET", URL, {"proxies": {"https":"http://bad.invalid"}}),
    ("GET", URL, {"verify": False}),
    ("GET", URL, {"hooks": {"response": [print]}}),
    ("GET", URL, {"auth": ("synthetic","synthetic")}),
])
def test_unauthorized_urls_options_methods_never_reach_network(
    monkeypatch, method, url, kwargs,
):
    reached = []
    def fail_if_called(*args, **more):
        reached.append(True)
        raise AssertionError("Should fail before any Requests network call")
    monkeypatch.setattr(requests.Session, "request", fail_if_called)
    opts = {"timeout":8, "allow_redirects":False}
    opts.update(kwargs)
    with instagram_meta_session() as transport:
        with pytest.raises(InstagramMetaTransportDenied):
            transport.request(method, url, **opts)
    assert reached == []


def test_pinned_graph_exchange_runs_with_safe_session_and_no_network(monkeypatch):
    captured = []
    class FakeReply:
        status_code = 200
        def json(self):
            return {"access_token": "SYNTHETIC_VALID_LONG_IG_TOKEN",
                    "expires_in": 60 * 86400, "token_type": "bearer"}

    def fake_base_request(self, method, url, **kwargs):
        captured.append({
            "method":method, "url":url, "trust_env":self.trust_env,
            "proxies":dict(self.proxies), "auth":self.auth,
            "verify":self.verify, "redirects":kwargs["allow_redirects"],
            "timeout":kwargs["timeout"],
        })
        return FakeReply()

    monkeypatch.setattr(requests.Session, "request", fake_base_request)
    reply=exchange_instagram_long_lived(
        short_lived_token=TOKEN, instagram_app_secret=SECRET,
        egress_approval=approved_only_in_ci(),
    )
    assert reply.expires_in_seconds == 60*86400
    assert len(captured)==1
    assert captured[0]=={
        "method":"GET","url":URL,"trust_env":False,"proxies":{},
        "auth":None,"verify":True,"redirects":False,"timeout":8,
    }
    assert TOKEN not in str(captured) and SECRET not in str(captured)


def test_pinned_code_exchange_uses_private_post_session_without_network(monkeypatch):
    captured=[]
    class FakeReply:
        status_code=200
        def json(self):
            return {"access_token":"SYNTHETIC_SHORT_IG_TOKEN","user_id":"123456789"}
    def fake_base_request(self,method,url,**kwargs):
        captured.append((method,url,self.trust_env,kwargs["allow_redirects"]))
        return FakeReply()
    monkeypatch.setattr(requests.Session,"request",fake_base_request)
    result=exchange_short_lived_token(
        app_id="123456789",app_secret=SECRET,code="SYNTHETIC_CODE",
        redirect_uri=STAGING_CALLBACK,
        egress_approval=approved_only_in_ci(),
    )
    assert result.instagram_user_id=="123456789"
    assert captured==[
        ("POST","https://api.instagram.com/oauth/access_token",False,False),
    ]


def test_test_fake_session_can_be_supplied_without_real_http():
    fake=object()
    with instagram_meta_session(fake) as transport:
        assert transport is fake


def test_pinned_transport_not_used_by_production_startup():
    source=(Path(__file__).parents[1]/"app"/"main.py").read_text(encoding="utf-8")
    assert "instagram_meta_transport" not in source
