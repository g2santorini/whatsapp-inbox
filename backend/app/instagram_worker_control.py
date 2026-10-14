"""Operator-only control for the Instagram message delivery worker.

This module is never imported by FastAPI startup or scheduled automatically.
Default invocation is read-only and prints only aggregate counts.

Usage (from backend/):
    python -m app.instagram_worker_control
A *future*, separately approved operator run may use --run-one only when
INSTAGRAM_WORKER_MANUAL_ENABLED=true is deliberately set. Until rollout is
approved, keep it unset and Instagram Meta webhook subscription OFF.
"""
import argparse
import os
import sys

from sqlalchemy import text

from .instagram_delivery_worker import process_one_pending_instagram_delivery


CONFIRM_PHRASE = "I_APPROVE_ONE_INSTAGRAM_DELIVERY"


def get_queue_counts(engine):
    """Return aggregate processing counts, never customer content or tokens."""
    with engine.connect() as db:
        items = db.execute(text("""
            SELECT processing_state, COUNT(*) AS total
            FROM public.sendro_channel_webhook_deliveries
            WHERE provider = 'instagram'
            GROUP BY processing_state
        """)).all()
    return {str(state): int(count) for state, count in items}


def execute_control(engine, *, run_one=False, confirmation=None, environ=None):
    """Only an explicitly authorized manual invocation may process a delivery."""
    env = os.environ if environ is None else environ
    if not run_one:
        return {"mode": "status", "queue": get_queue_counts(engine)}

    if (
        env.get("INSTAGRAM_WORKER_MANUAL_ENABLED", "").strip().lower() != "true"
        or confirmation != CONFIRM_PHRASE
    ):
        raise PermissionError("Instagram manual worker is disabled")

    key = env.get("INSTAGRAM_WEBHOOK_ENCRYPTION_KEY", "")
    if not key:
        raise ValueError("Instagram worker encryption key missing")

    result = process_one_pending_instagram_delivery(engine, key)
    return {
        "mode": "run-one",
        "status": result.status,
        "inserted_messages": result.inserted_messages,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Sendro Instagram worker: status-only unless explicitly unlocked"
    )
    parser.add_argument(
        "--run-one", action="store_true",
        help="process at most one queued delivery; requires explicit env gate and confirmation"
    )
    parser.add_argument(
        "--confirm", default=None,
        help="manual operator confirmation (only with --run-one)"
    )
    args = parser.parse_args(argv)

    if args.confirm and not args.run_one:
        parser.error("--confirm requires --run-one")
    if args.run_one and (
        os.getenv("INSTAGRAM_WORKER_MANUAL_ENABLED", "").lower() != "true"
        or args.confirm != CONFIRM_PHRASE
    ):
        print("Instagram manual worker: LOCKED - no deliveries processed")
        return 2

    # Import DB engine only in a CLI process, never as an application hook.
    from .database import engine

    try:
        outcome = execute_control(
            engine, run_one=args.run_one, confirmation=args.confirm
        )
    except Exception:
        # Do not leak SQL strings, customer data, connection URLs or secrets.
        print("Instagram worker: ERROR - check secure server logs")
        return 1

    if outcome["mode"] == "status":
        queue = outcome["queue"]
        print("Instagram worker: STATUS ONLY")
        for name in ("pending", "processing", "processed", "quarantined", "failed"):
            print(f"{name}: {queue.get(name, 0)}")
        print("No deliveries processed")
    else:
        print("Instagram worker: MANUAL ONE-DELIVERY")
        print("Processing state:", outcome["status"])
        print("New messages:", outcome["inserted_messages"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
