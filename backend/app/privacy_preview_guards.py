"""Small, staging-only privacy preview HTTP guards; no database writes.

Single Render staging instance: in-process per-user sliding-window limiter.
This is defense-in-depth, not a multi-replica/global abuse prevention service.
"""
import math
import time
from collections import deque
from threading import Lock

from fastapi import HTTPException

PRIVACY_ROUTE_PREFIX = "/privacy/requests"
PRIVACY_WORKFLOW_PREFIX = "/privacy/workflow"


class PrivacyRequestLimiter:
    """Bounded in-memory budget shared by both preview GET routes per user."""

    def __init__(self, *, max_calls: int = 30, window_seconds: int = 60,
                 max_users: int = 1000):
        if min(max_calls, window_seconds, max_users) < 1:
            raise ValueError("Limits must be positive")
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.max_users = max_users
        self._lock = Lock()
        self._hits: dict[int, deque[float]] = {}

    def check(self, user_id: int, *, now: float | None = None) -> None:
        if type(user_id) is not int or user_id < 1:
            raise HTTPException(status_code=403, detail="Privacy access denied")
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            existing = self._hits.get(user_id)
            if existing is None:
                if len(self._hits) >= self.max_users:
                    # Keep memory bounded; do not permit bypass by rotating identities.
                    for uid, history in list(self._hits.items()):
                        if history[-1] <= timestamp - self.window_seconds:
                            del self._hits[uid]
                    if len(self._hits) >= self.max_users:
                        raise HTTPException(status_code=429,
                            detail="Privacy request limit reached",
                            headers={"Retry-After": str(self.window_seconds)})
                existing = deque()
                self._hits[user_id] = existing

            while existing and existing[0] <= timestamp - self.window_seconds:
                existing.popleft()
            if len(existing) >= self.max_calls:
                retry = max(1, math.ceil(
                    self.window_seconds - (timestamp - existing[0])))
                raise HTTPException(status_code=429,
                    detail="Privacy request limit reached",
                    headers={"Retry-After": str(retry)})
            existing.append(timestamp)


class PrivacyNoStoreMiddleware:
    """Set cache restrictions on *all* GDPR HTTP statuses, incl. 401/403/422/429."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (scope.get("type") != "http" or not (
            path == PRIVACY_ROUTE_PREFIX
            or path.startswith(PRIVACY_ROUTE_PREFIX + "/")
            or path == PRIVACY_WORKFLOW_PREFIX
            or path.startswith(PRIVACY_WORKFLOW_PREFIX + "/")
        )):
            await self.app(scope, receive, send)
            return

        async def safe_send(message):
            if message["type"] == "http.response.start":
                excluded = {b"cache-control", b"pragma", b"expires",
                            b"x-robots-tag"}
                existing = [(k, v) for k, v in message.get("headers", [])
                            if k.lower() not in excluded]
                message = {**message, "headers": existing + [
                    (b"cache-control", b"no-store, private"),
                    (b"pragma", b"no-cache"),
                    (b"expires", b"0"),
                    (b"x-robots-tag", b"noindex, nofollow"),
                ]}
            await send(message)

        await self.app(scope, receive, safe_send)
