"""Disabled-by-default, library-only attended ONE Instagram DM pilot control.

This is NOT a scheduler, FastAPI route, worker process, CLI or Meta listener.
There is intentionally NO automatic deployment action. Calling the control on
any database requires a future explicit operator approval and separate gates.
Do not set pilot flags in Render before a signed-off, attended pilot window.
"""
import os

from .instagram_delivery_worker import (
    InstagramPilotScope,
    process_one_pending_instagram_delivery,
)


CONFIRM_PHRASE = "I_APPROVE_EXACTLY_ONE_INSTAGRAM_PILOT_DM"


class InstagramPilotDisabled(PermissionError):
    """An attended pilot is not explicitly authorized in this process."""


def execute_attended_one_dm_pilot(
    engine, *, scope, confirmation=None, environ=None
):
    """Run at most one exact queued inbound DM, or return blocked/idle.

    All gates are checked BEFORE a database connection is opened.
    An operator must independently approve one exact queue row and the
    Instagram account/tenant. No automatic retry, polling or alert transport;
    supervision and backup verification remain rollout prerequisites.

    Returns only generic status/counter — no customer IDs, payloads, tokens.
    """
    env = os.environ if environ is None else environ
    if not isinstance(scope, InstagramPilotScope):
        raise InstagramPilotDisabled("Instagram pilot has no approved scope")
    if (
        env.get("INSTAGRAM_PILOT_ONE_DM_ENABLED", "").strip().lower() != "true"
        or env.get("INSTAGRAM_WORKER_MANUAL_ENABLED", "").strip().lower() != "true"
        or confirmation != CONFIRM_PHRASE
        or env.get("INSTAGRAM_PILOT_DELIVERY_ID") != str(scope.delivery_id)
        or env.get("INSTAGRAM_PILOT_TENANT_ID") != str(scope.tenant_id)
        or env.get("INSTAGRAM_PILOT_ACCOUNT_ID") != str(scope.channel_account_id)
        or env.get("INSTAGRAM_PILOT_BUSINESS_ACCOUNT_ID") != scope.business_account_id
    ):
        raise InstagramPilotDisabled("Instagram pilot is disabled or scope differs")
    key = env.get("INSTAGRAM_WEBHOOK_ENCRYPTION_KEY", "")
    if not isinstance(key, str) or not key:
        raise InstagramPilotDisabled("Instagram pilot encryption is unavailable")

    result = process_one_pending_instagram_delivery(
        engine, key, pilot_scope=scope
    )
    if result.status not in ("processed", "idle", "blocked"):
        raise RuntimeError("Instagram pilot returned an unexpected state")
    return {
        "mode": "attended_one_dm",
        "status": result.status,
        "inserted_messages": result.inserted_messages,
    }
