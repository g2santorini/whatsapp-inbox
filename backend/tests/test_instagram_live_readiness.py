"""Phase 2Q: no-database, no-network checks of safe Instagram preflight.

Entire test is pure Python and uses fabricated secret values.
"""
import json
from pathlib import Path

from cryptography.fernet import Fernet

from backend.app.instagram_live_readiness import (
    inspect_instagram_live_readiness,
    main,
)


FAKE_APP_SECRET = "synthetic-meta-app-secret-ci-only"
FAKE_VERIFY_TOKEN = "synthetic-instagram-verify-token-ci-only"
FAKE_KEY = Fernet.generate_key().decode("ascii")


def safe_prepared_env():
    return {
        "INSTAGRAM_WEBHOOK_INGESTION_ENABLED": "false",
        "INSTAGRAM_WORKER_MANUAL_ENABLED": "false",
        "INSTAGRAM_SUPERVISOR_TEST_ENABLED": "false",
        "INSTAGRAM_ISOLATED_DB_APPROVED": "false",
        "INSTAGRAM_APP_SECRET": FAKE_APP_SECRET,
        "INSTAGRAM_WEBHOOK_VERIFY_TOKEN": FAKE_VERIFY_TOKEN,
        "WHATSAPP_WEBHOOK_VERIFY_TOKEN": "separate-fabricated-whatsapp-token",
        "INSTAGRAM_WEBHOOK_ENCRYPTION_KEY": FAKE_KEY,
    }


def test_default_missing_environment_is_inert_but_not_pilot_ready():
    report = inspect_instagram_live_readiness({})
    assert report["secure_standby"]
    assert not report["secrets_configured"]
    assert not report["pilot_ready"]
    assert report["meta_webhook_subscription"] == "not_verified"
    assert report["live_database_writes"] == "not_performed"
    assert "instagram_fernet_key_valid" in report["unmet_checks"]


def test_valid_configuration_is_standby_safe_not_live_permission():
    report = inspect_instagram_live_readiness(safe_prepared_env())
    assert report["secure_standby"]
    assert report["secrets_configured"]
    assert report["checks"]["instagram_fernet_key_valid"]
    assert report["unmet_checks"] == []
    # Passing a local preflight NEVER authorizes the real Meta subscription.
    assert not report["pilot_ready"]


def test_enabled_ingress_and_worker_are_reported_as_blockers():
    for variable in ("INSTAGRAM_WEBHOOK_INGESTION_ENABLED",
                     "INSTAGRAM_WORKER_MANUAL_ENABLED",
                     "INSTAGRAM_SUPERVISOR_TEST_ENABLED",
                     "INSTAGRAM_ISOLATED_DB_APPROVED"):
        env = safe_prepared_env()
        env[variable] = "true"
        result = inspect_instagram_live_readiness(env)
        assert not result["secure_standby"]
        assert variable + "_off" in result["unmet_checks"]


def test_unknown_values_fail_closed_instead_of_looking_off():
    for value in ("enable", "truee", "perhaps", "1", " true", "disabled-but-not-a-gate"):
        env = safe_prepared_env()
        env["INSTAGRAM_WEBHOOK_INGESTION_ENABLED"] = value
        assert not inspect_instagram_live_readiness(env)["secure_standby"]
    for value in ("false", "FALSE", "  off ", "no", "0", ""):
        env = safe_prepared_env()
        env["INSTAGRAM_WEBHOOK_INGESTION_ENABLED"] = value
        assert inspect_instagram_live_readiness(env)["secure_standby"]


def test_malformed_fernet_key_fails_without_disclosing_value():
    env = safe_prepared_env()
    env["INSTAGRAM_WEBHOOK_ENCRYPTION_KEY"] = "fabricated-invalid-encryption-key-value"
    report = inspect_instagram_live_readiness(env)
    assert not report["secrets_configured"]
    assert report["secure_standby"]
    assert "instagram_fernet_key_valid" in report["unmet_checks"]
    assert "fabricated-invalid-encryption-key-value" not in json.dumps(report)


def test_instagram_verify_token_must_be_separate_from_whatsapp():
    env = safe_prepared_env()
    env["WHATSAPP_WEBHOOK_VERIFY_TOKEN"] = FAKE_VERIFY_TOKEN
    report = inspect_instagram_live_readiness(env)
    assert not report["secrets_configured"]
    assert not report["checks"]["instagram_verify_token_distinct_from_whatsapp"]


def test_pure_preflight_never_echoes_secret_values_or_urls():
    env = safe_prepared_env()
    env["DATABASE_URL"] = "postgresql://fake:super-secret-password@fake.invalid/db"
    report = inspect_instagram_live_readiness(env)
    dumped = json.dumps(report, sort_keys=True)
    for secret in (FAKE_APP_SECRET, FAKE_VERIFY_TOKEN, FAKE_KEY,
                   "super-secret-password", "fake.invalid"):
        assert secret not in dumped
    assert "postgresql://" not in dumped


def test_module_has_no_database_or_meta_io_and_no_api_route():
    source = (Path(__file__).parents[1] / "app" /
              "instagram_live_readiness.py").read_text()
    for dangerous in (
        "create_engine", "get_db(", "SessionLocal", "requests.",
        "httpx.", "router.", "FastAPI(", "instagram_delivery_worker",
        "persist_instagram_webhook", "DATABASE_URL", "setenv(", "subprocess.",
    ):
        assert dangerous not in source


def test_manual_command_prints_redacted_status_and_never_changes_environment(
        monkeypatch, capsys):
    env = safe_prepared_env()
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    before = dict(env)
    assert main() == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["secure_standby"]
    assert not report["pilot_ready"]
    for secret in (FAKE_KEY, FAKE_APP_SECRET, FAKE_VERIFY_TOKEN):
        assert secret not in out
    import os
    assert all(os.environ.get(k) == v for k, v in before.items())


def test_manual_command_returns_nonzero_if_any_gate_is_open(monkeypatch, capsys):
    monkeypatch.setenv("INSTAGRAM_WEBHOOK_INGESTION_ENABLED", "true")
    assert main() == 2
    result = json.loads(capsys.readouterr().out)
    assert "INSTAGRAM_WEBHOOK_INGESTION_ENABLED_off" in result["unmet_checks"]
