"""CI-ONLY role-gated, audited human-acknowledgment contract.

WARNING: actor_user_id is supplied by a synthetic test, NOT verified by a
real Sendro login/session. This cannot be exposed as a live API: a production
handler must derive the actor from authenticated MFA/session middleware,
enforce global-incident authorization and keep append-only audit history.
No real notification or guest DM operation occurs here.
"""
import os

from sqlalchemy import text

from .instagram_alert_outbox_ci import APPROVED_CODES
from .instagram_alert_episode_ci import _gate as _episode_gate
from .instagram_queue_reliability import _utc_now

CONFIRM_ACK = "I_REVIEWED_THIS_SYNTHETIC_INSTAGRAM_ALERT"


class InstagramAckDisabled(PermissionError):
    """Synthetic acknowledgment needs its own hard CI-only guard."""


class InstagramAckDenied(PermissionError):
    """Generic denial without exposing staff IDs or customer data."""


def acknowledge_ci_incident_as_responder(
    engine, code, episode_number, *, actor_user_id, confirmation,
    environ=None, now=None,
):
    """Atomic exact-version acknowledgment with explicit global responder ACL.

    Responder table and audit table exist ONLY in the disposable CI fixture.
    A tenant member or arbitrary user ID cannot acknowledge global incidents
    unless the independent incident-responder allowlist permits it.

    Both the audit insertion and the dispatch state transition are one
    PostgreSQL transaction. On any failure neither takes effect.
    """
    flags = _episode_gate(engine, environ)
    if flags.get("INSTAGRAM_ALERT_ACK_CI_ENABLED") != "true":
        raise InstagramAckDisabled("Instagram acknowledgment is CI-only")
    if (
        not isinstance(code, str) or code not in APPROVED_CODES
        or not isinstance(episode_number, int)
        or isinstance(episode_number, bool) or episode_number < 1
        or not isinstance(actor_user_id, int)
        or isinstance(actor_user_id, bool) or actor_user_id <= 0
        or confirmation != CONFIRM_ACK
    ):
        raise InstagramAckDenied("CI alert acknowledgment denied")
    current = _utc_now(now)

    try:
        with engine.begin() as db:
            allowed = db.execute(text("""
                SELECT 1
                FROM public.sendro_ci_instagram_incident_responders
                WHERE user_id = :actor
                  AND is_active = TRUE AND can_acknowledge = TRUE
                  AND scope = 'global'
                  AND responder_role IN ('incident_admin', 'incident_responder')
                  AND approved_until > :now
                FOR SHARE
            """), {"actor": actor_user_id, "now": current}).scalar_one_or_none()
            if allowed != 1:
                raise InstagramAckDenied("CI alert acknowledgment denied")

            dispatch = db.execute(text("""
                SELECT alert_code
                FROM public.sendro_ci_instagram_alert_dispatch
                WHERE alert_code = :code AND status = 'accepted'
                  AND target_observations = :version
                  AND accepted_observations = :version
                  AND acknowledged_observations < :version
                FOR UPDATE
            """), {"code": code, "version": episode_number}).one_or_none()
            if dispatch is None:
                raise InstagramAckDenied("CI alert acknowledgment denied")

            audit = db.execute(text("""
                INSERT INTO public.sendro_ci_instagram_ack_audit (
                    alert_code, episode_number, actor_user_id, reviewed_at
                ) VALUES (:code, :version, :actor, :now)
                ON CONFLICT (alert_code, episode_number) DO NOTHING
                RETURNING alert_code
            """), {
                "code": code, "version": episode_number,
                "actor": actor_user_id, "now": current,
            }).scalar_one_or_none()
            if audit is None:
                raise InstagramAckDenied("CI alert acknowledgment denied")

            updated = db.execute(text("""
                UPDATE public.sendro_ci_instagram_alert_dispatch
                SET acknowledged_observations = :version,
                    acknowledged_at = :now, status = 'acknowledged'
                WHERE alert_code = :code AND status = 'accepted'
                  AND target_observations = :version
                  AND accepted_observations = :version
                  AND acknowledged_observations < :version
            """), {
                "code": code, "version": episode_number, "now": current,
            })
            if updated.rowcount != 1:
                raise InstagramAckDenied("CI alert acknowledgment denied")
    except InstagramAckDenied:
        raise
    except Exception:
        raise InstagramAckDenied("CI alert acknowledgment unavailable") from None
    return True
