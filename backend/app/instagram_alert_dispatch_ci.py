"""CI-only PostgreSQL notification dispatch / transport-acceptance / human-ack rehearsal.

No network transport, scheduler, automatic startup, service, real recipient
or Render database writes. The caller provides a *synthetic* acceptance
callback. All operations fail BEFORE connecting unless they target the exact
GitHub Actions disposable PostgreSQL test identity with dedicated opt-in.
The test fixture alone creates the needed CI-only dispatch table.
"""
from datetime import timedelta
import os
from uuid import uuid4

from sqlalchemy import text

from .instagram_alert_outbox_ci import (
    APPROVED_CODES, InstagramAlertOutboxInvalid, _require_disposable_ci,
)
from .instagram_queue_reliability import _utc_now


class InstagramDispatchDisabled(PermissionError):
    """Dispatch is enabled only by an explicitly approved synthetic CI test."""


class InstagramDispatchFailure(RuntimeError):
    """A sanitized failure of test outbox storage / claim / completion."""


def _gate(engine, environ):
    flags = dict(os.environ if environ is None else environ)
    _require_disposable_ci(engine, flags)
    if flags.get("INSTAGRAM_ALERT_DISPATCH_CI_ENABLED") != "true":
        raise InstagramDispatchDisabled("Instagram dispatch is test-only")
    return flags


def _valid_code(code):
    if not isinstance(code, str) or code not in APPROVED_CODES:
        raise InstagramAlertOutboxInvalid("Unrecognized redacted incident code")


def stage_ci_alert_dispatch(engine, *, environ=None):
    """Durably stage the last observed alert-version; never alter the DM queue.

    A new observation of an already-accepted alert is a NEW version.
    Existing in-flight leases remain intact so a completion cannot
    accidentally acknowledge a newly observed version.
    """
    _gate(engine, environ)
    try:
        with engine.begin() as db:
            result = db.execute(text("""
                INSERT INTO public.sendro_ci_instagram_alert_dispatch
                    (alert_code, target_observations, status, available_at)
                SELECT alert_code, observation_count, 'pending', CURRENT_TIMESTAMP
                FROM public.sendro_ci_instagram_alert_outbox
                WHERE alert_code IN (
                    'failed_deliveries', 'quarantined_deliveries',
                    'unresolved_processing_delivery', 'pending_backlog',
                    'stale_pending_delivery'
                )
                ON CONFLICT (alert_code) DO UPDATE
                SET target_observations = EXCLUDED.target_observations,
                    status = CASE
                        WHEN public.sendro_ci_instagram_alert_dispatch.status = 'leased'
                        THEN 'leased'
                        ELSE 'pending' END,
                    available_at = CASE
                        WHEN public.sendro_ci_instagram_alert_dispatch.status = 'leased'
                        THEN public.sendro_ci_instagram_alert_dispatch.available_at
                        ELSE CURRENT_TIMESTAMP END,
                    attempts = CASE
                        WHEN public.sendro_ci_instagram_alert_dispatch.status = 'leased'
                        THEN public.sendro_ci_instagram_alert_dispatch.attempts
                        ELSE 0 END
                WHERE public.sendro_ci_instagram_alert_dispatch.target_observations
                      < EXCLUDED.target_observations
            """))
            return result.rowcount
    except Exception:
        raise InstagramDispatchFailure("Instagram CI staging unavailable") from None


def claim_ci_alert_dispatch(engine, *, environ=None, now=None):
    """Lease one eligible redacted incident for at most 60s, transactionally.

    PostgreSQL SKIP LOCKED ensures concurrent test dispatchers cannot claim
    the same currently available record. Crash expiry allows future retry,
    with at-least-once (not exactly-once) callback semantics.
    """
    _gate(engine, environ)
    current = _utc_now(now)
    token = uuid4().hex
    try:
        with engine.begin() as db:
            claim = db.execute(text("""
                WITH candidate AS (
                    SELECT alert_code
                    FROM public.sendro_ci_instagram_alert_dispatch
                    WHERE target_observations > accepted_observations
                      AND (
                        (status = 'pending' AND available_at <= :now)
                        OR (status = 'leased' AND lease_until <= :now)
                      )
                    ORDER BY alert_code
                    LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE public.sendro_ci_instagram_alert_dispatch d
                SET status = 'leased', lease_token = :token,
                    lease_until = :expires, available_at = :now
                FROM candidate c
                WHERE d.alert_code = c.alert_code
                RETURNING d.alert_code, d.target_observations
            """), {
                "now": current, "expires": current + timedelta(seconds=60),
                "token": token,
            }).one_or_none()
    except Exception:
        raise InstagramDispatchFailure("Instagram CI alert claim unavailable") from None
    if claim is None:
        return None
    return {
        "code": claim.alert_code,
        "observations": int(claim.target_observations),
        "lease": token,  # Internal ephemeral claim token, NOT a Meta secret.
    }


def complete_ci_alert_dispatch(
    engine, claim, *, accepted, environ=None, now=None, max_attempts=3,
):
    """CAS-complete a still-owned lease based on synthetic transport response.

    accepted=True means only *transport accepted*, not human read/ack.
    A failed callback releases the lease with capped backoff; after the
    final failure the row stays 'failed' for manual triage, never dropped.
    """
    _gate(engine, environ)
    if (
        not isinstance(claim, dict)
        or set(claim) != {"code", "observations", "lease"}
        or not isinstance(claim["code"], str)
        or claim["code"] not in APPROVED_CODES
        or not isinstance(claim["observations"], int)
        or isinstance(claim["observations"], bool)
        or claim["observations"] < 1
        or not isinstance(claim["lease"], str)
        or len(claim["lease"]) != 32
        or not isinstance(accepted, bool)
        or not isinstance(max_attempts, int)
        or isinstance(max_attempts, bool)
        or not 1 <= max_attempts <= 10
    ):
        raise InstagramDispatchFailure("Invalid CI alert completion")
    current = _utc_now(now)
    try:
        with engine.begin() as db:
            if accepted:
                row = db.execute(text("""
                    UPDATE public.sendro_ci_instagram_alert_dispatch
                    SET accepted_observations = :version,
                        status = CASE WHEN target_observations > :version
                                      THEN 'pending' ELSE 'accepted' END,
                        available_at = :now,
                        attempts = 0,
                        lease_token = NULL, lease_until = NULL,
                        sent_at = :now,
                        last_error_code = NULL
                    WHERE alert_code = :code AND status = 'leased'
                      AND lease_token = :lease AND lease_until > :now
                      AND accepted_observations < :version
                      AND target_observations >= :version
                    RETURNING status
                """), {
                    "code": claim["code"], "lease": claim["lease"],
                    "version": claim["observations"], "now": current,
                }).one_or_none()
                return row is not None
            else:
                row = db.execute(text("""
                    UPDATE public.sendro_ci_instagram_alert_dispatch
                    SET attempts = attempts + 1,
                        status = CASE WHEN attempts + 1 >= :limit
                                      THEN 'failed' ELSE 'pending' END,
                        available_at = :retry_at,
                        lease_token = NULL, lease_until = NULL,
                        last_error_code = 'synthetic_transport_failure'
                    WHERE alert_code = :code AND status = 'leased'
                      AND lease_token = :lease AND lease_until > :now
                      AND target_observations >= :version
                      AND accepted_observations < :version
                    RETURNING status
                """), {
                    "code": claim["code"], "lease": claim["lease"],
                    "version": claim["observations"],
                    "limit": max_attempts, "now": current,
                    "retry_at": current + timedelta(seconds=30),
                }).one_or_none()
                return row is not None
    except Exception:
        raise InstagramDispatchFailure("Instagram CI alert completion unavailable") from None


def attempt_ci_alert_delivery(engine, fake_transport, *, environ=None, now=None):
    """A single explicit fake delivery; never performs external IO on its own.

    The callback gets only {code, observations}, never guest identifiers,
    encryption keys, account IDs, URLs or the lease token. Only the exact
    literal True is treated as transport acceptance.
    """
    _gate(engine, environ)
    if not callable(fake_transport):
        raise InstagramDispatchFailure("Synthetic transport missing")
    claim = claim_ci_alert_dispatch(engine, environ=environ, now=now)
    if claim is None:
        return "idle"
    try:
        accepted = fake_transport({
            "code": claim["code"], "observations": claim["observations"],
        }) is True
    except Exception:
        accepted = False
    if not complete_ci_alert_dispatch(
        engine, claim, accepted=accepted, environ=environ, now=now,
    ):
        raise InstagramDispatchFailure("CI alert lease completion conflict")
    return "accepted" if accepted else "deferred"


def acknowledge_ci_alert(engine, code, expected_observations, *, environ=None, now=None):
    """Simulated explicit human acknowledgment of exactly accepted version.

    Never implicitly acknowledges an alert when transport accepts it; a
    higher/newer observation version requires its own later human review.
    """
    _gate(engine, environ)
    _valid_code(code)
    if (not isinstance(expected_observations, int)
        or isinstance(expected_observations, bool)
        or expected_observations < 1):
        raise InstagramDispatchFailure("Invalid CI acknowledgment version")
    try:
        with engine.begin() as db:
            updated = db.execute(text("""
                UPDATE public.sendro_ci_instagram_alert_dispatch
                SET acknowledged_observations = :version,
                    acknowledged_at = :now, status = 'acknowledged'
                WHERE alert_code = :code AND status = 'accepted'
                  AND accepted_observations = :version
                  AND target_observations = :version
                  AND acknowledged_observations < :version
            """), {
                "code": code, "version": expected_observations,
                "now": _utc_now(now),
            })
            return updated.rowcount == 1
    except Exception:
        raise InstagramDispatchFailure("Instagram CI acknowledgment unavailable") from None


def read_ci_dispatch_status(engine, *, environ=None):
    """Read sanitized statuses (no leases, customer IDs or payloads)."""
    _gate(engine, environ)
    try:
        with engine.connect() as db:
            rows = db.execute(text("""
                SELECT alert_code, target_observations,
                       accepted_observations, acknowledged_observations,
                       status, attempts
                FROM public.sendro_ci_instagram_alert_dispatch
                ORDER BY alert_code
            """)).mappings().all()
    except Exception:
        raise InstagramDispatchFailure("Instagram CI dispatch status unavailable") from None
    return tuple(dict(row) for row in rows)
