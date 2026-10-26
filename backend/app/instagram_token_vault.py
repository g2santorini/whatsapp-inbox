"""Dormant, tenant-bound encrypted Instagram Login token vault.

Not routed, imported by app startup, scheduled, or deployed. Nothing in this
module opens a database connection. Every call needs an explicit transaction.
Only **long-lived Instagram Login** tokens are accepted. WhatsApp tokens and
OAuth authorization codes must never be passed to these helpers.
"""
from dataclasses import dataclass
import json
import time

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from .instagram_oauth_state import (
    InstagramOAuthDenied,
    _require_current_user_and_fresh_mfa,
    _require_owner_admin,
)

_TABLE = "public.sendro_instagram_token_vault"
_MIN_TOKEN_LENGTH = 10
_MAX_TOKEN_LENGTH = 8192
_MAX_LIFETIME = 62 * 24 * 3600
_MIN_LIFETIME = 24 * 3600
_REFRESH_MIN_AGE = 24 * 3600


class InstagramTokenVaultDenied(PermissionError):
    """Safe fixed messages only; never add token contents or SQL parameters."""


@dataclass(frozen=True, repr=False)
class InstagramTokenSecret:
    """Server-memory credential only. Never JSON serialize or return to UI."""
    access_token: str
    instagram_user_id: str
    issued_at_epoch: int
    expires_at_epoch: int
    revision: int

    def __repr__(self):
        return "InstagramTokenSecret(<redacted>)"

    def __str__(self):
        return "<redacted Instagram credential>"


def _epoch(now_epoch=None):
    now = int(time.time()) if now_epoch is None else now_epoch
    if type(now) is not int or now <= 0:
        raise InstagramTokenVaultDenied("Invalid token vault time")
    return now


def _validate_ids(tenant_id, account_id, provider_user_id):
    if (type(tenant_id) is not int or tenant_id <= 0
            or type(account_id) is not int or account_id <= 0
            or not isinstance(provider_user_id, str)
            or not provider_user_id.isascii() or not provider_user_id.isdecimal()
            or not 1 <= len(provider_user_id) <= 128):
        raise InstagramTokenVaultDenied("Invalid Instagram account binding")


def _authorize(conn, *, user, tenant_id, bearer_token, jwt_secret, jwt_algorithm, now):
    try:
        _require_current_user_and_fresh_mfa(
            user, bearer_token=bearer_token, jwt_secret=jwt_secret,
            jwt_algorithm=jwt_algorithm, now_epoch=now,
        )
        _require_owner_admin(conn, tenant_id=tenant_id, user_id=user.id)
    except InstagramOAuthDenied:
        raise InstagramTokenVaultDenied("Instagram token access denied") from None


def _require_account(conn, *, tenant_id, account_id, provider_user_id):
    _validate_ids(tenant_id, account_id, provider_user_id)
    exists = conn.execute(text("""
        SELECT 1 FROM public.sendro_channel_accounts
         WHERE id = :account_id AND tenant_id = :tenant_id
           AND platform = 'instagram' AND external_account_id = :provider_id
           AND status IN ('testing', 'active')
    """), {"account_id": account_id, "tenant_id": tenant_id,
           "provider_id": provider_user_id}).scalar_one_or_none()
    if exists is None:
        raise InstagramTokenVaultDenied("Instagram account is not enrolled for this business")


def _cipher(key):
    if not isinstance(key, str):
        raise InstagramTokenVaultDenied("Instagram token encryption unavailable")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, TypeError, UnicodeError, AttributeError):
        raise InstagramTokenVaultDenied("Instagram token encryption unavailable") from None


def _validate_long_lived(token, *, issued_at, expires_at):
    if (not isinstance(token, str) or not _MIN_TOKEN_LENGTH <= len(token) <= _MAX_TOKEN_LENGTH
            or not token.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in token)):
        raise InstagramTokenVaultDenied("Invalid Instagram long-lived token")
    if (type(issued_at) is not int or type(expires_at) is not int
            or not _MIN_LIFETIME <= expires_at - issued_at <= _MAX_LIFETIME):
        raise InstagramTokenVaultDenied("Invalid Instagram token lifetime")


def _encrypt(cipher, *, tenant_id, account_id, provider_id, token):
    data = {"v": 1, "purpose": "sendro-instagram-login-long-lived",
            "tenant": tenant_id, "account": account_id,
            "provider_user_id": provider_id, "token": token}
    return cipher.encrypt(json.dumps(data, separators=(",", ":")).encode("utf-8"))


def _decrypt(cipher, ciphertext, *, tenant_id, account_id, provider_id):
    try:
        payload = json.loads(cipher.decrypt(bytes(ciphertext)).decode("utf-8"))
        if (type(payload) is not dict or set(payload) != {
                "v", "purpose", "tenant", "account", "provider_user_id", "token"}
                or payload["v"] != 1
                or payload["purpose"] != "sendro-instagram-login-long-lived"
                or payload["tenant"] != tenant_id
                or payload["account"] != account_id
                or payload["provider_user_id"] != provider_id):
            raise ValueError("Wrong account binding")
        token = payload["token"]
        if not isinstance(token, str) or not _MIN_TOKEN_LENGTH <= len(token) <= _MAX_TOKEN_LENGTH:
            raise ValueError("Invalid decrypted credential")
        return token
    except (InvalidToken, ValueError, TypeError, UnicodeError, KeyError, AttributeError):
        raise InstagramTokenVaultDenied("Instagram credential decryption failed") from None


def enroll_new_long_lived_token(
    conn, *, user, tenant_id, channel_account_id, provider_user_id,
    bearer_token, jwt_secret, jwt_algorithm, encryption_key,
    long_lived_token, expires_in_seconds, now_epoch=None,
):
    """One-time install, no overwrite. Caller MUST commit its transaction.

    Future trusted server integration must verify provider_user_id using a
    Meta profile response. It must match the approved channel account.
    """
    now = _epoch(now_epoch)
    _authorize(conn, user=user, tenant_id=tenant_id, bearer_token=bearer_token,
               jwt_secret=jwt_secret, jwt_algorithm=jwt_algorithm, now=now)
    _require_account(conn, tenant_id=tenant_id, account_id=channel_account_id,
                     provider_user_id=provider_user_id)
    if type(expires_in_seconds) is not int:
        raise InstagramTokenVaultDenied("Invalid Instagram token lifetime")
    expiry = now + expires_in_seconds
    _validate_long_lived(long_lived_token, issued_at=now, expires_at=expiry)
    ciphertext = _encrypt(_cipher(encryption_key), tenant_id=tenant_id,
        account_id=channel_account_id, provider_id=provider_user_id,
        token=long_lived_token)
    inserted = conn.execute(text(f"""
        INSERT INTO {_TABLE} (tenant_id, channel_account_id, provider_user_id,
            encrypted_token, issued_epoch, expires_epoch, revision)
        VALUES (:tenant, :account, :provider, :ciphertext, :issued, :expires, 1)
        ON CONFLICT (tenant_id, channel_account_id) DO NOTHING
        RETURNING revision
    """), dict(tenant=tenant_id, account=channel_account_id,
              provider=provider_user_id, ciphertext=ciphertext,
              issued=now, expires=expiry)).scalar_one_or_none()
    if inserted is None:
        raise InstagramTokenVaultDenied("Instagram account already has a credential")
    return {"connected": True, "expires_at_epoch": expiry, "revision": 1}


def load_long_lived_token_for_admin(
    conn, *, user, tenant_id, channel_account_id, provider_user_id,
    bearer_token, jwt_secret, jwt_algorithm, encryption_key, now_epoch=None,
):
    """Server-only use. Do NOT return this object from a FastAPI endpoint."""
    now = _epoch(now_epoch)
    _authorize(conn, user=user, tenant_id=tenant_id, bearer_token=bearer_token,
               jwt_secret=jwt_secret, jwt_algorithm=jwt_algorithm, now=now)
    _require_account(conn, tenant_id=tenant_id, account_id=channel_account_id,
                     provider_user_id=provider_user_id)
    row = conn.execute(text(f"""
        SELECT encrypted_token, issued_epoch, expires_epoch, revision
          FROM {_TABLE}
         WHERE tenant_id = :tenant AND channel_account_id = :account
           AND provider_user_id = :provider
    """), dict(tenant=tenant_id, account=channel_account_id,
               provider=provider_user_id)).mappings().one_or_none()
    if row is None or row["expires_epoch"] <= now:
        raise InstagramTokenVaultDenied("Instagram credential missing or expired")
    token = _decrypt(_cipher(encryption_key), row["encrypted_token"],
        tenant_id=tenant_id, account_id=channel_account_id, provider_id=provider_user_id)
    _validate_long_lived(token, issued_at=row["issued_epoch"],
                         expires_at=row["expires_epoch"])
    return InstagramTokenSecret(
        access_token=token, instagram_user_id=provider_user_id,
        issued_at_epoch=row["issued_epoch"],
        expires_at_epoch=row["expires_epoch"], revision=row["revision"])


def rotate_refreshed_long_lived_token(
    conn, *, user, tenant_id, channel_account_id, provider_user_id,
    bearer_token, jwt_secret, jwt_algorithm, encryption_key,
    old_revision, new_long_lived_token, new_expires_in_seconds, now_epoch=None,
):
    """CAS rotation; never silently overwrite a newly refreshed credential.

    Only call after Meta authenticated the refresh and returned a new token.
    Automated renewal requires independently reviewed service credentials.
    """
    now = _epoch(now_epoch)
    _authorize(conn, user=user, tenant_id=tenant_id, bearer_token=bearer_token,
               jwt_secret=jwt_secret, jwt_algorithm=jwt_algorithm, now=now)
    _require_account(conn, tenant_id=tenant_id, account_id=channel_account_id,
                     provider_user_id=provider_user_id)
    if type(old_revision) is not int or old_revision < 1:
        raise InstagramTokenVaultDenied("Invalid Instagram credential revision")
    if type(new_expires_in_seconds) is not int:
        raise InstagramTokenVaultDenied("Invalid Instagram token lifetime")
    expiry = now + new_expires_in_seconds
    _validate_long_lived(new_long_lived_token, issued_at=now, expires_at=expiry)
    cipher = _encrypt(_cipher(encryption_key), tenant_id=tenant_id,
        account_id=channel_account_id, provider_id=provider_user_id,
        token=new_long_lived_token)
    updated = conn.execute(text(f"""
        UPDATE {_TABLE}
           SET encrypted_token = :ciphertext,
               issued_epoch = :now, expires_epoch = :expiry,
               revision = revision + 1
         WHERE tenant_id = :tenant AND channel_account_id = :account
           AND provider_user_id = :provider AND revision = :expected
           AND issued_epoch <= :refresh_after AND expires_epoch > :now
        RETURNING revision
    """), dict(ciphertext=cipher, now=now, expiry=expiry,
              tenant=tenant_id, account=channel_account_id,
              provider=provider_user_id, expected=old_revision,
              refresh_after=now - _REFRESH_MIN_AGE)).scalar_one_or_none()
    if updated is None:
        raise InstagramTokenVaultDenied("Instagram refresh is not eligible or was superseded")
    return {"refreshed": True, "expires_at_epoch": expiry, "revision": int(updated)}


def disconnect_instagram_credential(
    conn, *, user, tenant_id, channel_account_id, provider_user_id,
    bearer_token, jwt_secret, jwt_algorithm, now_epoch=None,
):
    """Revoke Sendro's local token access only, NOT Meta's authorization.

    Updating the channel status and writing an audit event remain separate,
    reviewed requirements before any live rollout.
    """
    now = _epoch(now_epoch)
    _authorize(conn, user=user, tenant_id=tenant_id, bearer_token=bearer_token,
               jwt_secret=jwt_secret, jwt_algorithm=jwt_algorithm, now=now)
    _require_account(conn, tenant_id=tenant_id, account_id=channel_account_id,
                     provider_user_id=provider_user_id)
    deleted = conn.execute(text(f"""
        DELETE FROM {_TABLE}
         WHERE tenant_id = :tenant AND channel_account_id = :account
           AND provider_user_id = :provider
        RETURNING revision
    """), dict(tenant=tenant_id, account=channel_account_id,
              provider=provider_user_id)).scalar_one_or_none()
    return {"locally_disconnected": deleted is not None,
            "meta_authorization_revoked": False}
