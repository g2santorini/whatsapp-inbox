"""UNMOUNTED CI-only in-app Instagram incident-center API factory.

WARNING: This is NOT a live API. Neither main.py nor any Render startup
registers this router. A test harness must explicitly inject BOTH a
server-verified *recent MFA* user dependency and an exact disposable
GitHub Actions PostgreSQL engine. The functions reject the real Render DB
before connecting. The UI may not infer authorization from client state.

Global aggregate Instagram queue-health incidents are NOT tenant-specific;
therefore per-tenant admin/operator membership is insufficient to see them.
The CI-only separate global incident-responder permission is required.
No guest/customer identities, DMs, payloads, token material or URLs appear.
"""
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from .instagram_alert_episode_ci import _gate as require_ephemeral_ci
from .instagram_alert_staff_ack_ci import (
    CONFIRM_ACK, InstagramAckDenied,
    acknowledge_ci_incident_as_responder,
)
from .instagram_queue_reliability import _utc_now


class IncidentOut(BaseModel):
    code: str
    episode: int
    is_active: bool
    observations: int
    dispatch_status: str


class AckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode: int = Field(gt=0)
    confirmation: Literal["I_REVIEWED_THIS_SYNTHETIC_INSTAGRAM_ALERT"]


class AckResult(BaseModel):
    acknowledged: bool


def _authorized_ci_global_responder(engine, user, flags):
    """Check verified server principal + independent DB responder grant."""
    # Caller MUST inject a dependency that actually validates signed recent
    # MFA. This function is a *second* authorization check, not authentication.
    if (
        getattr(user, "disabled", True) is not False
        or getattr(user, "role", None) != "admin"
        or getattr(user, "mfa_enabled", False) is not True
        or type(getattr(user, "id", None)) is not int
        or user.id < 1
    ):
        raise HTTPException(status_code=403, detail="Incident access denied")
    try:
        with engine.connect() as db:
            grant = db.execute(text("""
                SELECT 1
                FROM public.sendro_ci_instagram_incident_responders
                WHERE user_id = :actor
                  AND scope = 'global'
                  AND responder_role IN ('incident_admin', 'incident_responder')
                  AND is_active = TRUE
                  AND can_acknowledge = TRUE
                  AND approved_until > :now
            """), {"actor": user.id, "now": _utc_now()}).scalar_one_or_none()
    except Exception:
        raise HTTPException(
            status_code=503, detail="Incident center unavailable"
        ) from None
    if grant != 1:
        raise HTTPException(status_code=403, detail="Incident access denied")


def create_ci_instagram_incident_center_router(
    get_recent_mfa_verified_user: Callable,
    get_incident_engine: Callable,
    *,
    environ: dict,
) -> APIRouter:
    """Create an inert router; ONLY isolated GitHub CI may mount it.

    Never call this from main.py. In any future design the injected identity
    MUST be derived from Sendro authentication + signed, RECENT MFA, not a
    user_id supplied in the request. The engine must stay ephemeral here.
    """
    if not callable(get_recent_mfa_verified_user) or not callable(get_incident_engine):
        raise ValueError("Incident center requires explicit auth and DB dependencies")

    router = APIRouter(prefix="/ci/instagram/incidents", tags=["Instagram CI Incidents"])

    @router.get("", response_model=list[IncidentOut])
    def list_incidents(
        user=Depends(get_recent_mfa_verified_user),
        engine=Depends(get_incident_engine),
    ):
        # Hard engine/gate check BEFORE DB connection, even for fake users.
        require_ephemeral_ci(engine, environ)
        _authorized_ci_global_responder(engine, user, environ)
        try:
            with engine.connect() as db:
                rows = db.execute(text("""
                    SELECT e.alert_code AS code, e.episode_number AS episode,
                           e.is_active, e.observation_count AS observations,
                           d.status AS dispatch_status
                    FROM public.sendro_ci_instagram_alert_episodes e
                    JOIN public.sendro_ci_instagram_alert_dispatch d
                      ON d.alert_code = e.alert_code
                    ORDER BY e.is_active DESC, e.alert_code
                    LIMIT 20
                """)).mappings().all()
        except Exception:
            raise HTTPException(
                status_code=503, detail="Incident center unavailable"
            ) from None
        return [dict(row) for row in rows]

    @router.post("/{code}/acknowledge", response_model=AckResult)
    def acknowledge_incident(
        payload: AckRequest,
        code: str = Path(min_length=3, max_length=80),
        user=Depends(get_recent_mfa_verified_user),
        engine=Depends(get_incident_engine),
    ):
        require_ephemeral_ci(engine, environ)
        _authorized_ci_global_responder(engine, user, environ)
        try:
            acknowledged = acknowledge_ci_incident_as_responder(
                engine, code, payload.episode, actor_user_id=user.id,
                confirmation=payload.confirmation, environ=environ,
            )
        except InstagramAckDenied:
            raise HTTPException(
                status_code=409, detail="Incident not available for acknowledgment"
            ) from None
        except Exception:
            raise HTTPException(
                status_code=503, detail="Incident center unavailable"
            ) from None
        return {"acknowledged": acknowledged}

    return router
