"""No-network tests for strict fixed-host staging HTTPS sentinel."""
from io import BytesIO
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.app import instagram_staging_http_sentinel as sentinel


def flags(**changes):
    return {sentinel.APPROVAL_KEY: sentinel.EXACT_APPROVAL, **changes}


def test_missing_gate_never_calls_any_transport():
    calls = []
    result = sentinel.inspect_staging_http_sentinel(
        environ={}, fetch_status=lambda: calls.append("called") or True,
    )
    assert calls == []
    assert result == {
        "mode": "staging_public_http_only",
        "backend_http": "disabled",
        "instagram_pipeline": "not_checked",
        "operator_notification": "not_configured",
        "live_pilot_authorized": False,
        "database_access": "none",
        "meta_access": "none",
    }


@pytest.mark.parametrize("invalid", [
    "true", "1", "on", "I_APPROVE_STAGING_STATUS",
    "", None, False, " I_APPROVE_STAGING_PUBLIC_STATUS_GET_ONLY ",
])
def test_any_nonexact_approval_is_disabled(invalid):
    assert sentinel.inspect_staging_http_sentinel(
        environ={sentinel.APPROVAL_KEY: invalid},
        fetch_status=lambda: pytest.fail("network must remain disabled"),
    )["backend_http"] == "disabled"


def test_explicit_gate_accepts_only_literal_true_result():
    for value, expected in (
        (True, "reachable"), (False, "unavailable"),
        (1, "unavailable"), ("ok", "unavailable"), (None, "unavailable"),
    ):
        result = sentinel.inspect_staging_http_sentinel(
            environ=flags(), fetch_status=lambda: value,
        )
        assert result["backend_http"] == expected
        assert result["instagram_pipeline"] == "not_checked"
        assert not result["live_pilot_authorized"]


def test_transport_exception_never_leaks_urls_or_tokens():
    def failed_transport():
        raise RuntimeError(
            "Token abc123 secret; private=https://internal.invalid/user/guest"
        )

    report = sentinel.inspect_staging_http_sentinel(
        environ=flags(), fetch_status=failed_transport,
    )
    assert report["backend_http"] == "unavailable"
    dumped = json.dumps(report)
    for secret in ("abc123", "internal.invalid", "/user/guest"):
        assert secret not in dumped


class FakeReply:
    def __init__(self, status=200, body=b'{"status":"ok","version":"v1"}',
                 content_type="application/json"):
        self.status = status
        self._data = BytesIO(body)
        self.headers = {"Content-Type": content_type}

    def read(self, amount):
        return self._data.read(amount)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.request = None
        self.timeout = None

    def open(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return self.response


def fake_network(monkeypatch, response):
    opener = FakeOpener(response)
    monkeypatch.setattr(sentinel.urllib.request, "build_opener",
                        lambda *handlers: opener)
    return opener


def test_live_urllib_adapter_can_only_use_fixed_https_public_root(monkeypatch):
    opener = fake_network(monkeypatch, FakeReply())
    assert sentinel._fetch_public_staging_status() is True
    assert opener.request.full_url == (
        "https://sendro-backend-staging.onrender.com/"
    )
    assert opener.request.get_method() == "GET"
    assert opener.request.get_header("Accept") == "application/json"
    assert opener.request.get_header("User-agent") == (
        "Sendro-staging-status-sentinel/1.0"
    )
    assert "Authorization" not in opener.request.headers
    assert "Cookie" not in opener.request.headers
    assert opener.timeout == 5
    assert sentinel.STAGING_STATUS_URL.endswith(".onrender.com/")


@pytest.mark.parametrize("reply", [
    FakeReply(status=500),
    FakeReply(status=404),
    FakeReply(status=301),
    FakeReply(content_type="text/html"),
    FakeReply(body=b"not json"),
    FakeReply(body=b'{"status":"oops","version":"v1"}'),
    FakeReply(body=b'{"status":"ok"}'),
    FakeReply(body=b'{"status":"ok","version":200}'),
    FakeReply(body=b'{"status":"ok","version":""}'),
    FakeReply(body=b"X" * 2000),
])
def test_unexpected_http_responses_fail_closed(monkeypatch, reply):
    fake_network(monkeypatch, reply)
    assert sentinel._fetch_public_staging_status() is False


def test_network_exception_is_translated_without_exposing_server(monkeypatch):
    class BrokenOpener:
        def open(self, *_args, **_kwargs):
            raise OSError("internal connection failure: secret")

    monkeypatch.setattr(sentinel.urllib.request, "build_opener",
                        lambda *_handlers: BrokenOpener())
    assert sentinel._fetch_public_staging_status() is False


def test_no_redirect_handler_can_follow_arbitrary_url():
    handler = sentinel._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Moved", {},
                                    "https://attacker.invalid") is None


def test_cli_disabled_is_nonzero_and_redacted(monkeypatch, capsys):
    monkeypatch.delenv(sentinel.APPROVAL_KEY, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://private:password@render.invalid/")
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", "dont-print-synthetic-secret")
    monkeypatch.setattr(sentinel, "_fetch_public_staging_status",
                        lambda: pytest.fail("No outbound request"))
    assert sentinel.main() == 2
    output = capsys.readouterr().out
    assert json.loads(output)["backend_http"] == "disabled"
    for secret in ("render.invalid", "password", "dont-print-synthetic-secret"):
        assert secret not in output


def test_cli_only_succeeds_after_approval_and_public_status_reply(monkeypatch, capsys):
    monkeypatch.setenv(sentinel.APPROVAL_KEY, sentinel.EXACT_APPROVAL)
    monkeypatch.setattr(sentinel, "_fetch_public_staging_status",
                        lambda: True)
    assert sentinel.main() == 0
    assert json.loads(capsys.readouterr().out)["backend_http"] == "reachable"
    monkeypatch.setattr(sentinel, "_fetch_public_staging_status",
                        lambda: False)
    assert sentinel.main() == 2
    assert json.loads(capsys.readouterr().out)["backend_http"] == "unavailable"


def test_source_is_not_wired_to_runtime_or_database():
    root = Path(__file__).parents[1]
    code = (root / "app" / "instagram_staging_http_sentinel.py").read_text()
    main = (root / "app" / "main.py").read_text()
    for forbidden in (
        "create_engine", "SessionLocal", "get_db(", "DATABASE_URL",
        "INSTAGRAM_APP_SECRET", "INSTAGRAM_WEBHOOK_INGESTION_ENABLED",
        "process_one_pending_instagram_delivery", "send_email",
        "send_message", "FastAPI(", "APIRouter(", "subprocess.",
    ):
        assert forbidden not in code
    assert "instagram_staging_http_sentinel" not in main
    assert "instagram_staging_http_sentinel" not in (
        root.parent / "frontend" / "src" / "App.jsx"
    ).read_text()
