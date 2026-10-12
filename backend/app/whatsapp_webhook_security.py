"""Verification helpers for incoming Meta WhatsApp webhook requests.

Opt-in enforcement is controlled by WHATSAPP_WEBHOOK_SIGNATURE_REQUIRED.
Never log the application secret or an untrusted request body.
"""
import hashlib
import hmac


def is_valid_meta_webhook_signature(
    raw_body: bytes,
    signature_header: str | None,
    app_secret: str,
) -> bool:
    """Meta signs the exact UTF-8 request bytes with HMAC-SHA256."""
    if not app_secret or not signature_header or not signature_header.startswith("sha256="):
        return False

    supplied_digest = signature_header[len("sha256="):]
    if len(supplied_digest) != 64:
        return False
    try:
        bytes.fromhex(supplied_digest)
    except ValueError:
        return False

    expected_digest = hmac.new(
        app_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_digest, supplied_digest.lower())
