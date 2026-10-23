"""Dormant authenticated completion of a captured Instagram OAuth code.

This is a **library**, NOT a FastAPI endpoint, worker or live token exchange.
It requires the previously committed encrypted callback and the exact
authenticated Sendro session. No DB schema is installed automatically.

The caller MUST commit the one-use DELETE transaction successfully BEFORE
giving the returned code to Meta's code-exchange endpoint. Never print,
log, serialize, return to a browser, or persist a plaintext authorization code.
"""

from dataclasses import dataclass
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from .instagram_oauth_state import (
    InstagramOAuthDenied,
    _now,
    _state_hash,
    _require_current_user_and_fresh_mfa,
    _require_owner_admin,
)

_TABLE = "public.sendro_instagram_oauth_challenges"


@dataclass(frozen=True, repr=False)
class ClaimedInstagramCode:
    tenant_id: int
    user_id: int
    authorization_code: str

    def __repr__(self):
        return "ClaimedInstagramCode(<redacted>)"

    def __str__(self):
        return "<redacted Instagram authorization code>"


def claim_captured_instagram_code(
    conn, *, state: str, user, tenant_id: int, bearer_token: str,
    jwt_secret: str, jwt_algorithm: str, encryption_key: str,
    now_epoch: int | None = None,
) -> ClaimedInstagramCode:
    """Burn exactly one unexpired callback code bound to this admin/tenant.

    This function must execute inside one explicit, committed transaction.
    A future route must invoke Sendro's original get_current_active_user
    dependency first, restrict to a verified staging host, and ensure
    request origin/session binding before calling this helper.
    This function does not use or trust a tenant_id encoded in the URL,
    does not authenticate the Meta GET callback, and does not touch tokens.
    """
    now = _now(now_epoch)
    digest = _state_hash(state)
    _require_current_user_and_fresh_mfa(
        user, bearer_token=bearer_token, jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm, now_epoch=now,
    )
    _require_owner_admin(conn, tenant_id=tenant_id, user_id=user.id)
    if not isinstance(encryption_key, str):
        raise InstagramOAuthDenied("Instagram callback key unavailable")
    try:
        cipher = Fernet(encryption_key.encode("ascii"))
    except (ValueError, TypeError, UnicodeError, AttributeError):
        raise InstagramOAuthDenied("Instagram callback key unavailable") from None

    row = conn.execute(text(f"""
        DELETE FROM {_TABLE}
         WHERE state_hash = :state_hash
           AND tenant_id = :tenant_id
           AND user_id = :user_id
           AND expires_epoch > :now_epoch
           AND received_epoch IS NOT NULL
           AND received_epoch <= :now_epoch
           AND encrypted_authorization_code IS NOT NULL
        RETURNING user_id, tenant_id, encrypted_authorization_code
    """), {
        "state_hash": digest, "tenant_id": tenant_id,
        "user_id": user.id, "now_epoch": now,
    }).mappings().one_or_none()
    if row is None:
        raise InstagramOAuthDenied("Instagram callback unavailable or already used")
    try:
        raw = cipher.decrypt(bytes(row["encrypted_authorization_code"]))
        code = raw.decode("ascii")
        if not 1 <= len(code) <= 2048 or any(ord(c) < 33 or ord(c) > 126 for c in code):
            raise ValueError("Invalid authorization code bytes")
    except (InvalidToken, UnicodeError, TypeError, ValueError, AttributeError):
        raise InstagramOAuthDenied("Instagram callback cannot be decrypted") from None
    return ClaimedInstagramCode(
        tenant_id=int(row["tenant_id"]),
        user_id=int(row["user_id"]),
        authorization_code=code,
    )
