"""CI-ONLY active-incident episode classifier and throttled dispatch staging.

This is an explicitly invoked synthetic proof, NOT production monitoring.
No scheduler, API route, service, Meta requests or customer record updates.
Only a disposable GitHub Actions Postgres URL with all separate opt-ins may
be queried/written. The CI test fixture creates the episode table.
"""
import os
from sqlalchemy import text

from .instagram_alert_outbox_ci import APPROVED_CODES
from .instagram_alert_dispatch_ci import _gate as _dispatch_gate
from .instagram_queue_reliability import _utc_now, read_instagram_queue_health


class InstagramEpisodeDisabled(PermissionError):
    """CI-only incident episode sampling has not been enabled."""


class InstagramEpisodeFailure(RuntimeError):
    """Redacted failure: no partial alert episode / dispatch publication."""


def _gate(engine, environ):
    flags = _dispatch_gate(engine, environ)
    if flags.get("INSTAGRAM_ALERT_EPISODE_CI_ENABLED") != "true":
        raise InstagramEpisodeDisabled("Instagram alert episode sampling is CI-only")
    return flags


def observe_ci_instagram_episodes(
    engine, *, environ=None, now=None, backlog_threshold=50, stale_minutes=15,
):
    """Atomically stage one notification per *continuous active* alert code.

    A persistent incident is sampled repeatedly but does NOT generate a
    new dispatch version on each observation. When it clears, its episode
    closes. If it later recurs, exactly one NEW dispatch version is staged.
    No real message is processed, retried or acknowledged.

    The health SELECT and the transaction are separate; no lossless live
    monitoring or operator notification is implied. A live implementation
    would need consistent atomic event collection / durable polling policy.
    """
    _gate(engine, environ)
    current = _utc_now(now)
    try:
        health = read_instagram_queue_health(
            engine, now=current, backlog_threshold=backlog_threshold,
            stale_minutes=stale_minutes,
        )
        active_codes = set(health["alert_codes"])
        if not active_codes.issubset(APPROVED_CODES):
            raise InstagramEpisodeFailure("Unknown Instagram alert code")

        new_episodes = 0
        resolved = 0
        with engine.begin() as db:
            for code in sorted(APPROVED_CODES):
                current_row = db.execute(text("""
                    SELECT episode_number, is_active, observation_count
                    FROM public.sendro_ci_instagram_alert_episodes
                    WHERE alert_code = :code
                    FOR UPDATE
                """), {"code": code}).mappings().first()

                if code in active_codes:
                    if current_row is None:
                        episode_number = 1
                        db.execute(text("""
                            INSERT INTO public.sendro_ci_instagram_alert_episodes
                                (alert_code, episode_number, is_active,
                                 observation_count, first_seen_at, last_seen_at)
                            VALUES (:code, 1, TRUE, 1, :now, :now)
                        """), {"code": code, "now": current})
                    elif current_row["is_active"]:
                        db.execute(text("""
                            UPDATE public.sendro_ci_instagram_alert_episodes
                            SET observation_count = observation_count + 1,
                                last_seen_at = :now
                            WHERE alert_code = :code
                        """), {"code": code, "now": current})
                        continue
                    else:
                        episode_number = int(current_row["episode_number"]) + 1
                        db.execute(text("""
                            UPDATE public.sendro_ci_instagram_alert_episodes
                            SET episode_number = :number, is_active = TRUE,
                                observation_count = 1, first_seen_at = :now,
                                last_seen_at = :now, resolved_at = NULL
                            WHERE alert_code = :code
                        """), {
                            "code": code, "number": episode_number, "now": current,
                        })

                    # Atomic with episode creation. Never re-stage persistent
                    # observations, even after a successful human ack.
                    db.execute(text("""
                        INSERT INTO public.sendro_ci_instagram_alert_dispatch
                            (alert_code, target_observations, status, available_at)
                        VALUES (:code, :version, 'pending', :now)
                        ON CONFLICT (alert_code) DO UPDATE
                        SET target_observations = EXCLUDED.target_observations,
                            status = CASE WHEN
                                public.sendro_ci_instagram_alert_dispatch.status = 'leased'
                                THEN 'leased' ELSE 'pending' END,
                            available_at = CASE WHEN
                                public.sendro_ci_instagram_alert_dispatch.status = 'leased'
                                THEN public.sendro_ci_instagram_alert_dispatch.available_at
                                ELSE EXCLUDED.available_at END,
                            attempts = CASE WHEN
                                public.sendro_ci_instagram_alert_dispatch.status = 'leased'
                                THEN public.sendro_ci_instagram_alert_dispatch.attempts
                                ELSE 0 END
                        WHERE public.sendro_ci_instagram_alert_dispatch.target_observations
                              < EXCLUDED.target_observations
                    """), {"code": code, "version": episode_number, "now": current})
                    new_episodes += 1

                elif current_row is not None and current_row["is_active"]:
                    db.execute(text("""
                        UPDATE public.sendro_ci_instagram_alert_episodes
                        SET is_active = FALSE, resolved_at = :now
                        WHERE alert_code = :code
                    """), {"code": code, "now": current})
                    resolved += 1

        return {
            "active_codes": tuple(sorted(active_codes)),
            "new_episodes": new_episodes,
            "resolved": resolved,
        }
    except InstagramEpisodeFailure:
        raise
    except Exception:
        raise InstagramEpisodeFailure(
            "Instagram CI alert episode sampling not committed"
        ) from None


def read_ci_episode_status(engine, *, environ=None):
    """Return only redacted episode codes and numeric state metadata."""
    _gate(engine, environ)
    try:
        with engine.connect() as db:
            rows = db.execute(text("""
                SELECT alert_code, episode_number, is_active, observation_count
                FROM public.sendro_ci_instagram_alert_episodes
                ORDER BY alert_code
            """)).mappings().all()
    except Exception:
        raise InstagramEpisodeFailure("Instagram CI episode status unavailable") from None
    return tuple(dict(row) for row in rows)
