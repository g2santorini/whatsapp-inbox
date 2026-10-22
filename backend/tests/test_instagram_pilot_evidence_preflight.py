"""Pure synthetic tests: offline Instagram attended-pilot Go/No-Go evidence.

No database, Render, Meta, network, real credentials, live users or real
pilot. Even fully populated operator-supplied evidence is NEVER approval.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.app.instagram_live_readiness import inspect_instagram_live_readiness
from backend.app.instagram_pilot_evidence_preflight import (
    EVIDENCE_REQUIREMENTS,
    inspect_instagram_pilot_evidence,
    main,
)
from backend.tests.test_instagram_live_readiness import safe_prepared_env


NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def all_synthetic_evidence(*, when=None):
    instant = when or NOW - timedelta(hours=1)
    return {
        name: {
            "verified": True,
            "source": source,
            "verified_at": instant.isoformat(),
        }
        for name, (source, _hours) in EVIDENCE_REQUIREMENTS.items()
    }


def test_empty_evidence_and_empty_environment_always_hold():
    result = inspect_instagram_pilot_evidence({}, now=NOW)
    assert result["mode"] == "offline_attended_instagram_pilot_evidence_review"
    assert result["decision"] == "HOLD"
    assert result["live_pilot_authorized"] is False
    assert result["independently_verified"] is False
    assert result["next_action"] == "independent_owner_review_required"
    assert not result["evidence_complete_for_manual_review"]
    assert set(result["unmet_evidence"]) == set(EVIDENCE_REQUIREMENTS)
    assert result["supplied_config_secure_standby"] is True
    assert result["supplied_config_prepared"] is False
    assert result["database_writes"] == "none"
    assert result["meta_changes"] == "none"


def test_even_perfect_fabricated_evidence_never_authorizes_live_pilot():
    fake = all_synthetic_evidence()
    result = inspect_instagram_pilot_evidence(
        safe_prepared_env(), fake, now=NOW,
    )
    assert result["evidence_complete_for_manual_review"]
    assert result["unmet_evidence"] == []
    assert all(result["evidence_checks"].values())
    assert result["decision"] == "HOLD"
    assert result["live_pilot_authorized"] is False
    assert result["independently_verified"] is False
    assert "review" in result["next_action"]


@pytest.mark.parametrize("case", [
    "missing", "false_boolean", "int_truth", "wrong_source",
    "missing_field", "extra_field", "invalid_time", "naive_time",
    "future_time", "stale_time",
])
def test_any_unverified_or_stale_milestone_blocks_review(case):
    data = all_synthetic_evidence()
    name = "alert_recipient_receipt_rehearsed"
    item = data[name]
    if case == "missing":
        data.pop(name)
    elif case == "false_boolean":
        item["verified"] = False
    elif case == "int_truth":
        item["verified"] = 1
    elif case == "wrong_source":
        item["source"] = "github_ci"
    elif case == "missing_field":
        item.pop("source")
    elif case == "extra_field":
        item["customer_email"] = "PRIVATE-TEST-EMAIL"
    elif case == "invalid_time":
        item["verified_at"] = "invalid"
    elif case == "naive_time":
        item["verified_at"] = "2026-10-22T10:00:00"
    elif case == "future_time":
        item["verified_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif case == "stale_time":
        item["verified_at"] = (NOW - timedelta(hours=49)).isoformat()
    else:
        pytest.fail("Unknown synthetic case")
    result = inspect_instagram_pilot_evidence(
        safe_prepared_env(), data, now=NOW,
    )
    assert name in result["unmet_evidence"]
    assert result["evidence_checks"][name] is False
    assert not result["evidence_complete_for_manual_review"]
    assert not result["live_pilot_authorized"]
    assert "PRIVATE-TEST-EMAIL" not in json.dumps(result)


def test_exact_provenance_and_per_gate_age_are_enforced():
    data = all_synthetic_evidence()
    # Restore drill evidence may be within 72h, but effective Render flags
    # require a much fresher read-only staging review (24h).
    data["shared_database_backup_restore_verified"]["verified_at"] = (
        NOW - timedelta(hours=70)
    ).isoformat()
    data["staging_effective_flags_reviewed"]["verified_at"] = (
        NOW - timedelta(hours=26)
    ).isoformat()
    result = inspect_instagram_pilot_evidence(
        safe_prepared_env(), data, now=NOW,
    )
    assert result["evidence_checks"]["shared_database_backup_restore_verified"]
    assert not result["evidence_checks"]["staging_effective_flags_reviewed"]
    assert result["unmet_evidence"] == ["staging_effective_flags_reviewed"]
    assert result["decision"] == "HOLD"


def test_unknown_or_malformed_evidence_fails_closed_without_echoing_content():
    data = all_synthetic_evidence()
    data["SERIOUS_UNTRUSTED_URL_https://private.invalid/secret"] = {
        "verified": True, "source": "security_review",
        "verified_at": NOW.isoformat(), "meta_secret": "DO-NOT-LEAK",
    }
    result = inspect_instagram_pilot_evidence(
        safe_prepared_env(), data, now=NOW,
    )
    assert result["unrecognized_evidence_present"]
    assert not result["evidence_complete_for_manual_review"]
    dumped = json.dumps(result)
    assert "private.invalid" not in dumped
    assert "DO-NOT-LEAK" not in dumped
    assert "SERIOUS_UNTRUSTED_URL" not in dumped

    for malformed in (None, True, [], "all done", 42):
        report = inspect_instagram_pilot_evidence(
            safe_prepared_env(), malformed, now=NOW,
        )
        assert not report["evidence_complete_for_manual_review"]
        assert len(report["unmet_evidence"]) == len(EVIDENCE_REQUIREMENTS)


def test_flag_enabled_or_secrets_missing_prevents_manual_review_completeness():
    good = all_synthetic_evidence()
    env = safe_prepared_env()
    env["INSTAGRAM_WEBHOOK_INGESTION_ENABLED"] = "true"
    result = inspect_instagram_pilot_evidence(env, good, now=NOW)
    assert not result["supplied_config_secure_standby"]
    assert "INSTAGRAM_WEBHOOK_INGESTION_ENABLED_off" in result["standby_blockers"]
    assert not result["evidence_complete_for_manual_review"]
    assert result["decision"] == "HOLD"

    env2 = safe_prepared_env()
    del env2["INSTAGRAM_WEBHOOK_ENCRYPTION_KEY"]
    other = inspect_instagram_pilot_evidence(env2, good, now=NOW)
    assert other["supplied_config_secure_standby"]
    assert not other["supplied_config_prepared"]
    assert not other["evidence_complete_for_manual_review"]


def test_full_report_is_redacted_and_does_not_reflect_arbitrary_env():
    env = safe_prepared_env()
    env.update({
        "DATABASE_URL": "postgresql://private-user:password123@render.invalid/db",
        "INSTAGRAM_APP_SECRET": "SECRET-IN-ENV",
        "INSTAGRAM_WEBHOOK_VERIFY_TOKEN": "PRIVATE-TOKEN-IN-ENV",
        "EMAIL_FROM": "private-operator@example.invalid",
    })
    evidence = all_synthetic_evidence()
    # This arbitrary field would fail its evidence gate and must NEVER
    # appear in output or in any JSON-serializable report.
    evidence["meta_subscription_confirmed_off"]["value"] = "PRIVATE-ACCOUNT-ID"
    result = inspect_instagram_pilot_evidence(env, evidence, now=NOW)
    dumped = json.dumps(result)
    for secret in ("render.invalid", "password123", "SECRET-IN-ENV",
                   "PRIVATE-TOKEN-IN-ENV", "PRIVATE-ACCOUNT-ID",
                   "private-operator@example.invalid"):
        assert secret not in dumped
    assert result["unmet_evidence"] == ["meta_subscription_confirmed_off"]
    assert result["live_pilot_authorized"] is False


def test_operator_cli_always_exits_nonzero_and_never_dumps_secrets(monkeypatch, capsys):
    for name, value in safe_prepared_env().items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DATABASE_URL", "postgresql://bad:SUPER-SECRET@private.invalid")
    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report["decision"] == "HOLD"
    assert report["live_pilot_authorized"] is False
    assert len(report["unmet_evidence"]) == len(EVIDENCE_REQUIREMENTS)
    assert "SUPER-SECRET" not in json.dumps(report)


def test_module_never_contains_runtime_db_network_auth_or_mutation_hooks():
    source = (Path(__file__).parents[1] / "app" /
              "instagram_pilot_evidence_preflight.py").read_text()
    for unsafe in (
        "create_engine", "SessionLocal", "get_db(", "requests.",
        "httpx.", "FastAPI(", "APIRouter(", "subprocess.",
        "execute_control(", "execute_attended_one_dm_pilot(",
        "process_one_pending_instagram_delivery(", "os.environ[",
        "os.environ.update(", "setenv(", "DATABASE_URL", "INSTAGRAM_APP_SECRET",
    ):
        assert unsafe not in source
