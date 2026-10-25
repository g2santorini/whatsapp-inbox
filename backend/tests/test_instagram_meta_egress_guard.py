"""Fully synthetic Meta egress safety tests; never contact Instagram/Render."""
import http.client
import logging
from pathlib import Path

import pytest

from backend.app.instagram_meta_egress_guard import (
    InstagramMetaEgressDenied, require_safe_instagram_meta_egress,
)
from backend.app.instagram_oauth_http_security import InstagramOAuthLogAttestations
from backend.app.instagram_token_lifecycle import (
    exchange_instagram_long_lived, refresh_instagram_long_lived,
)
from backend.app.instagram_login_oauth import (
    STAGING_CALLBACK, exchange_short_lived_token, fetch_authorized_profile,
)

TOKEN = "SYNTHETIC_ACCESS_TOKEN_DO_NOT_USE"
SECRET = "SYNTHETIC_META_APP_SECRET_DO_NOT_USE"
CODE = "SYNTHETIC_INSTAGRAM_AUTH_CODE"


def attested(**override):
    values = {name: True for name in InstagramOAuthLogAttestations.__dataclass_fields__}
    values.update(override)
    return InstagramOAuthLogAttestations(**values)


class SpyMeta:
    def __init__(self):
        self.calls = []
    def get(self, *args, **kwargs):
        self.calls.append(("get", args, kwargs))
        raise AssertionError("Network MUST be blocked in this test")
    def post(self, *args, **kwargs):
        self.calls.append(("post", args, kwargs))
        raise AssertionError("Network MUST be blocked in this test")


def blocked_calls(session, approval):
    with pytest.raises(InstagramMetaEgressDenied):
        exchange_instagram_long_lived(
            short_lived_token=TOKEN, instagram_app_secret=SECRET,
            session=session, egress_approval=approval)
    with pytest.raises(InstagramMetaEgressDenied):
        refresh_instagram_long_lived(
            long_lived_token=TOKEN, session=session, egress_approval=approval)
    with pytest.raises(InstagramMetaEgressDenied):
        exchange_short_lived_token(
            app_id="123456789", app_secret=SECRET, code=CODE,
            redirect_uri=STAGING_CALLBACK,
            session=session, egress_approval=approval)
    with pytest.raises(InstagramMetaEgressDenied):
        fetch_authorized_profile(
            access_token=TOKEN, session=session, egress_approval=approval)
    assert session.calls == []


def test_every_meta_protocol_egress_denies_without_operational_attestation():
    blocked_calls(SpyMeta(), None)
    blocked_calls(SpyMeta(), False)
    blocked_calls(SpyMeta(), True)
    blocked_calls(SpyMeta(), "true")
    blocked_calls(SpyMeta(), InstagramOAuthLogAttestations())


@pytest.mark.parametrize("missing", list(InstagramOAuthLogAttestations.__dataclass_fields__))
def test_any_single_missing_operator_attestation_denies_all_meta_calls(missing):
    blocked_calls(SpyMeta(), attested(**{missing: False}))


def test_bool_strings_are_not_approval():
    blocked_calls(SpyMeta(), attested(egress_meta_query_redaction_verified="true"))


@pytest.mark.parametrize("name", ["urllib3", "urllib3.connectionpool", "requests"])
def test_debug_logging_blocks_provider_requests_even_if_attested(name):
    logger = logging.getLogger(name)
    old_level = logger.level
    try:
        logger.setLevel(logging.DEBUG)
        blocked_calls(SpyMeta(), attested())
    finally:
        logger.setLevel(old_level)


def test_http_client_wire_debuglevel_blocks_provider_requests(monkeypatch):
    monkeypatch.setattr(http.client.HTTPConnection, "debuglevel", 1)
    blocked_calls(SpyMeta(), attested())


def test_metadata_only_release_gate_does_not_log_sensitive_values():
    with pytest.raises(InstagramMetaEgressDenied) as error:
        require_safe_instagram_meta_egress(None)
    output = str(error.value)
    assert CODE not in output and TOKEN not in output and SECRET not in output


def test_guard_dormant_and_unmounted_in_sendro_main():
    source = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf8")
    assert "instagram_meta_egress_guard" not in source
