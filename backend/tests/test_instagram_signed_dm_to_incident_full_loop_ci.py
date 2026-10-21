"""CI-only full signed Instagram DM -> failure -> Incident Center rehearsal.

One TestClient POSTs a correctly HMAC-signed synthetic Instagram webhook
into an isolated database. The test explicitly invokes the inert manual
worker, redacted alert recording, incident episode observation and fake
notification transport. A second TestClient exercises the *unmounted*
Incident Center with a signed recent-MFA synthetic admin. NO production
service, real Meta account, Render database, recipient or guest is used.

This is **NOT** an automatic, continuously supervised production pipeline:
the separate steps are deliberately called by this test.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.instagram_alert_outbox_ci import (
    persist_ci_instagram_alerts, read_ci_instagram_alerts,
)
from backend.app.instagram_alert_episode_ci import (
    observe_ci_instagram_episodes, read_ci_episode_status,
)
from backend.app.instagram_alert_dispatch_ci import (
    attempt_ci_alert_delivery, read_ci_dispatch_status,
)
from backend.app.instagram_incident_center_ci_api import (
    create_ci_instagram_incident_center_router,
)
from backend.app.instagram_queue_reliability import read_instagram_queue_health
from backend.tests.test_instagram_alert_episodes_ack_ci import (
    episode_db, flags, grant, audit_rows,
)
from backend.tests.test_instagram_alert_dispatch_ci import ci_dispatch
from backend.tests.test_instagram_alert_outbox_ci import ci_alerts
from backend.tests.test_instagram_incident_center_ci_api import (
    verified_ci_user, token,
)
from backend.tests.test_instagram_postgres_supervision_ci import ci_supervisor
from backend.tests.test_instagram_manual_migrations_postgres import replay_engine
from backend.tests.test_instagram_signed_http_postgres_e2e import (
    ci_http, allow_ci_ingestion, manual_once,
    signed_payload, synthetic_dm,
)

FICTITIOUS_BUSINESS = "ci-full-loop-not-enrolled"
SYNTHETIC_DM = "ci-full-loop-guest-dm"
ALERT_CODE = "quarantined_deliveries"
ACK_TEXT = "I_REVIEWED_THIS_SYNTHETIC_INSTAGRAM_ALERT"
STATES = ("pending", "processing", "processed", "quarantined", "failed")


@pytest.fixture
def full_loop(episode_db, ci_http):
    # Fixture dependency ORDER matters. episode_db installs and clears ONLY
    # the GitHub CI incident/outbox/dispatch tables. ci_http then resets the
    # six test-only Instagram schema tables and mounts an isolated signed HTTP
    # webhook app. Both use the SAME strictly allowlisted ephemeral database.
    engine, _worker_key = episode_db
    webhook_client, http_engine, http_key, monkeypatch = ci_http
    assert engine is http_engine
    assert engine.url.database == "sendro_ig_ci"
    assert engine.url.host == "127.0.0.1" and engine.url.port == 55439
    assert engine.url.username == "sendro_ci"

    def incident_engine():
        return engine

    incident_app = FastAPI()
    # Not mounted in main.py or any Render service.
    incident_app.include_router(create_ci_instagram_incident_center_router(
        verified_ci_user, incident_engine, environ=flags(),
    ))
    with TestClient(incident_app, raise_server_exceptions=False) as incidents:
        yield webhook_client, incidents, engine, http_key, ci_http


def queue_row(engine):
    with engine.connect() as db:
        return db.execute(text("""
            SELECT id, processing_state, last_error_code,
                   attempts, payload_ciphertext
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram'
        """)).mappings().one()


def counts(engine):
    with engine.connect() as db:
        return {
            "deliveries": db.execute(text(
                "SELECT COUNT(*) FROM public.sendro_channel_webhook_deliveries"
            )).scalar_one(),
            "conversations": db.execute(text(
                "SELECT COUNT(*) FROM public.sendro_channel_conversations"
            )).scalar_one(),
            "messages": db.execute(text(
                "SELECT COUNT(*) FROM public.sendro_channel_messages"
            )).scalar_one(),
            "tenant_accounts": db.execute(text(
                "SELECT COUNT(*) FROM public.sendro_channel_accounts"
            )).scalar_one(),
        }


def persist_sanitized_health(engine, now):
    health = read_instagram_queue_health(engine, now=now)
    assert tuple(health["alert_codes"]) == (ALERT_CODE,)
    incident = {
        "codes": tuple(health["alert_codes"]),
        "states": {state: health["states"].get(state, 0) for state in STATES},
        "due": health["due"],
        "deferred": health["deferred"],
    }
    assert persist_ci_instagram_alerts(
        engine, incident, environ=flags(),
    ) == 1


def incident_url():
    return "/ci/instagram/incidents"


def confirm(client, headers, *, episode=1):
    return client.post(
        incident_url() + "/" + ALERT_CODE + "/acknowledge",
        headers=headers, json={"episode": episode, "confirmation": ACK_TEXT},
    )


def test_signed_dm_to_quarantine_durable_alert_retry_and_authorized_ack(full_loop):
    webhook, incidents, engine, key, ci_http_fixture = full_loop
    now = datetime.now(timezone.utc) + timedelta(seconds=5)

    # Real HTTP signature verification logic and the default OFF gate.
    envelope = synthetic_dm(SYNTHETIC_DM, business=FICTITIOUS_BUSINESS,
                            sender="fictional-ci-guest",
                            content="Entirely fictional Instagram DM content")
    body, headers = signed_payload(envelope)
    assert webhook.post(
        "/webhook/instagram", content=body, headers=headers,
    ).status_code == 503
    assert counts(engine) == {
        "deliveries": 0, "conversations": 0,
        "messages": 0, "tenant_accounts": 2,
    }

    allow_ci_ingestion(ci_http_fixture)
    assert webhook.post(
        "/webhook/instagram", content=body,
        headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
    ).status_code == 403
    assert counts(engine)["deliveries"] == 0

    response = webhook.post(
        "/webhook/instagram", content=body, headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "stored"}
    row_before = queue_row(engine)
    assert row_before["processing_state"] == "pending"
    assert b"Entirely fictional Instagram DM content" not in row_before["payload_ciphertext"]
    assert counts(engine)["messages"] == 0

    # No active worker: explicitly request ONE bounded manual test step.
    result = manual_once(ci_http_fixture)
    assert result["status"] == "quarantined"
    row_after = queue_row(engine)
    assert row_after["id"] == row_before["id"]
    assert row_after["last_error_code"] == "unregistered_business_account"
    assert row_after["payload_ciphertext"] == row_before["payload_ciphertext"]
    assert row_after["attempts"] == 1
    assert counts(engine) == {
        "deliveries": 1, "conversations": 0,
        "messages": 0, "tenant_accounts": 2,
    }

    # Stage ONE persistent incident. Separate manual outbox and episode steps
    # are not transactionally coupled in this synthetic proof.
    persist_sanitized_health(engine, now)
    assert read_ci_instagram_alerts(
        engine, environ=flags(),
    )[0]["code"] == ALERT_CODE
    episode = observe_ci_instagram_episodes(engine, environ=flags(), now=now)
    assert episode == {
        "active_codes": (ALERT_CODE,),
        "new_episodes": 1,
        "resolved": 0,
    }
    assert read_ci_episode_status(engine, environ=flags())[0]["episode_number"] == 1
    assert read_ci_dispatch_status(engine, environ=flags())[0]["status"] == "pending"

    # No tenant operator, outsider or non-MFA user is allowed to view even
    # redacted GLOBAL incidents. Only separately delegated global admin.
    assert incidents.get(incident_url()).status_code in (401, 403)
    assert incidents.get(
        incident_url(), headers=token(103),
    ).status_code == 403
    assert incidents.get(
        incident_url(), headers=token(101, verified=False),
    ).status_code == 403
    assert incidents.get(
        incident_url(), headers=token(101),
    ).status_code == 403  # no responder grant yet
    grant(engine, 101, now, role="incident_admin")
    admin = token(101)
    incident_list = incidents.get(incident_url(), headers=admin)
    assert incident_list.status_code == 200, incident_list.text
    assert incident_list.json() == [{
        "code": ALERT_CODE, "episode": 1, "is_active": True,
        "observations": 1, "dispatch_status": "pending",
    }]
    assert confirm(incidents, admin).status_code == 409

    # A fake transport outage is NOT a delivery, nor a human acknowledgment.
    fake_attempts = []
    def failed_fake_transport(safe_event):
        fake_attempts.append(safe_event)
        raise RuntimeError("fabricated notification transport outage")

    assert attempt_ci_alert_delivery(
        engine, failed_fake_transport, environ=flags(), now=now,
    ) == "deferred"
    assert fake_attempts == [{"code": ALERT_CODE, "observations": 1}]
    assert read_ci_dispatch_status(
        engine, environ=flags(),
    )[0]["status"] == "pending"
    assert confirm(incidents, admin).status_code == 409

    # Repeated health polling of the *same* active issue cannot create a
    # new dispatch version or a storm of fake staff notifications.
    for seconds in (3, 10, 20):
        sample = observe_ci_instagram_episodes(
            engine, environ=flags(), now=now + timedelta(seconds=seconds),
        )
        assert sample["new_episodes"] == 0

    delivered = []
    assert attempt_ci_alert_delivery(
        engine, lambda event: (delivered.append(event), True)[-1],
        environ=flags(), now=now + timedelta(seconds=31),
    ) == "accepted"
    assert delivered == [{"code": ALERT_CODE, "observations": 1}]
    assert read_ci_dispatch_status(
        engine, environ=flags(),
    )[0]["acknowledged_observations"] == 0

    assert confirm(incidents, token(103)).status_code == 403
    assert confirm(incidents, admin, episode=2).status_code == 409
    confirmed = confirm(incidents, admin)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json() == {"acknowledged": True}
    assert confirm(incidents, admin).status_code == 409
    assert read_ci_dispatch_status(
        engine, environ=flags(),
    )[0]["status"] == "acknowledged"
    audit = audit_rows(engine)
    assert len(audit) == 1
    assert audit[0]["actor_user_id"] == 101
    assert audit[0]["episode_number"] == 1

    # Reposting signed identical bytes is idempotent and cannot create a
    # new message, queue delivery, incident episode or second human review.
    assert webhook.post(
        "/webhook/instagram", content=body, headers=headers,
    ).status_code == 200
    assert counts(engine) == {
        "deliveries": 1, "conversations": 0,
        "messages": 0, "tenant_accounts": 2,
    }
    assert manual_once(ci_http_fixture)["status"] == "idle"
    assert observe_ci_instagram_episodes(
        engine, environ=flags(), now=now + timedelta(seconds=40),
    )["new_episodes"] == 0
    assert len(audit_rows(engine)) == 1
    assert read_ci_dispatch_status(engine, environ=flags())[0]["status"] == "acknowledged"

    # Every operator-visible object is redacted. No plaintext, synthetic
    # sender, business account ID, ciphertext or encryption key is emitted.
    exposed = json.dumps([
        incident_list.json(), confirmed.json(), delivered, fake_attempts,
        read_ci_instagram_alerts(engine, environ=flags()),
        read_ci_dispatch_status(engine, environ=flags()),
    ], default=str)
    for secret in (
        "Entirely fictional Instagram DM content", "fictional-ci-guest",
        FICTITIOUS_BUSINESS, SYNTHETIC_DM, key,
        "payload_ciphertext", "external_customer_id", "lease_token",
    ):
        assert secret not in exposed


def test_signed_rejected_ingress_never_generates_alert_or_incident(full_loop):
    webhook, incidents, engine, key, ci_http_fixture = full_loop
    body, signature = signed_payload(synthetic_dm(
        "ci-no-incident-invalid-signature", business=FICTITIOUS_BUSINESS,
    ))
    allow_ci_ingestion(ci_http_fixture)
    bad = webhook.post(
        "/webhook/instagram", content=body,
        headers={"X-Hub-Signature-256": "sha256=" + "f" * 64},
    )
    assert bad.status_code == 403
    assert counts(engine)["deliveries"] == 0
    assert counts(engine)["messages"] == 0
    now = datetime.now(timezone.utc) + timedelta(seconds=5)
    assert observe_ci_instagram_episodes(
        engine, environ=flags(), now=now,
    ) == {"active_codes": (), "new_episodes": 0, "resolved": 0}
    assert read_ci_instagram_alerts(engine, environ=flags()) == ()
    assert read_ci_dispatch_status(engine, environ=flags()) == ()
    grant(engine, 101, now, role="incident_admin")
    response = incidents.get(incident_url(), headers=token(101))
    assert response.status_code == 200
    assert response.json() == []
    assert audit_rows(engine) == []
