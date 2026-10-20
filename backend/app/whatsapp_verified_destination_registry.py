"""INERT, read-only WhatsApp destination-account registry adapter.

No automatic migration, DB connection, request route, webhook subscription,
message logging, sending, or customer data. The schema in
ops/db/20261020_whatsapp_verified_destinations_MANUAL_ONLY.sql is NOT applied
to Render, and this adapter is NOT invoked by the live webhook.

The caller must *first* verify Meta's HMAC over the exact raw webhook bytes.
Reading verified mapping rows is not a substitute for that signature check.
"""
from types import MappingProxyType

from sqlalchemy import text

from backend.app.whatsapp_account_routing_preflight import (
    WhatsAppRoutingPreflightError,
)


MAX_VERIFIED_DESTINATIONS = 1024

# No evidence UUID, reviewer names, phone numbers of guests or tokens selected.
VERIFIED_DESTINATIONS_SQL = text("""
    SELECT waba_id, phone_number_id, tenant_id
    FROM public.sendro_whatsapp_verified_destinations
    WHERE revoked_at IS NULL
    ORDER BY phone_number_id
    LIMIT :limit
""")


# Future dedicated-schema option; remains INERT and unmounted.
# The original public-table resolver above is retained for earlier CI/PRs.
DEDICATED_VERIFIED_DESTINATIONS_SQL = text("""
    SELECT waba_id, phone_number_id, tenant_id
    FROM sendro_whatsapp.verified_destinations
    WHERE revoked_at IS NULL
    ORDER BY phone_number_id
    LIMIT :limit
""")


def _checked_meta_id(value):
    return (isinstance(value, str)
            and value.isascii()
            and value.isdecimal()
            and 5 <= len(value) <= 32)


def _load_verified_whatsapp_registry(db, query):
    """Return an immutable mapping for signed-envelope routing only.

    Unknown and empty registry entries MUST fail closed. Bounded, aggregate-free,
    metadata-only lookup; does not mutate the provided SQLAlchemy session.
    No implicit tenant ownership or fallback to the customer phone number.
    """
    rows = db.execute(
        query,
        {"limit": MAX_VERIFIED_DESTINATIONS + 1},
    ).mappings().all()
    if not rows or len(rows) > MAX_VERIFIED_DESTINATIONS:
        raise WhatsAppRoutingPreflightError(
            "Missing or oversized verified WhatsApp registry"
        )
    registry = {}
    owners_by_phone_id = {}
    for row in rows:
        waba_id = row["waba_id"]
        phone_id = row["phone_number_id"]
        tenant_id = row["tenant_id"]
        if (not _checked_meta_id(waba_id)
                or not _checked_meta_id(phone_id)
                or type(tenant_id) is not int
                or tenant_id < 1):
            raise WhatsAppRoutingPreflightError("Invalid verified destination")
        if phone_id in owners_by_phone_id or (waba_id, phone_id) in registry:
            raise WhatsAppRoutingPreflightError("Duplicate WhatsApp ownership")
        registry[(waba_id, phone_id)] = tenant_id
        owners_by_phone_id[phone_id] = tenant_id
    return MappingProxyType(registry)


def load_verified_whatsapp_registry(db):
    """Legacy inert public-table preflight; NOT connected to live webhooks."""
    return _load_verified_whatsapp_registry(db, VERIFIED_DESTINATIONS_SQL)


def load_dedicated_whatsapp_registry(db):
    """Future dedicated-schema metadata read only; NOT used by live routes."""
    return _load_verified_whatsapp_registry(db, DEDICATED_VERIFIED_DESTINATIONS_SQL)
