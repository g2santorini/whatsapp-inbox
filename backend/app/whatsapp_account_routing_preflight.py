"""Inert, pure WhatsApp destination-account routing preflight (NOT active).

This module is NOT imported by Sendro's live webhook and does not read, write
or query any database. It prepares future multi-company integration tests.

SECURITY: Meta body fields are untrusted assertions until the caller verifies
the exact raw body against Meta's configured app secret. The explicit
signature_verified=True argument is a calling-contract reminder, not a
replacement for cryptographic verification. Company routing must use an
independently reviewed, server-side (WABA ID, Phone Number ID) -> tenant map.
Never infer a tenant from the *customer* phone, user ID or tenant count.

Intentionally returns identifiers/account metadata only, not messages, contact
details, provider tokens, or any customer personal data.
"""
from dataclasses import dataclass
from collections.abc import Mapping


MAX_ENTRIES = 32
MAX_CHANGES_PER_ENTRY = 128


class WhatsAppRoutingPreflightError(ValueError):
    """A malformed, unauthenticated or unmapped delivery is not routable."""


@dataclass(frozen=True)
class AccountRoute:
    entry_index: int
    change_index: int
    event_type: str
    tenant_id: int
    waba_id: str
    phone_number_id: str


def _meta_id(value, field):
    if not isinstance(value, str) or not value.isascii():
        raise WhatsAppRoutingPreflightError("Missing or invalid " + field)
    if not value.isdecimal() or not 5 <= len(value) <= 32:
        raise WhatsAppRoutingPreflightError("Missing or invalid " + field)
    return value


def preflight_whatsapp_account_routes(
    payload,
    approved_accounts: Mapping[tuple[str, str], int],
    *,
    signature_verified: bool,
) -> tuple[AccountRoute, ...]:
    """All-or-nothing routing decisions only, without persistence or side effects.

    In a future implementation, signature verification MUST happen before this
    function and the approved mapping MUST be loaded from independently
    verified tenant-owned account configuration. Do not call from production
    while WhatsApp tenant routing is not fully approved and integrated.
    """
    if signature_verified is not True:
        raise WhatsAppRoutingPreflightError("Signed delivery not verified")
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        raise WhatsAppRoutingPreflightError("Invalid WhatsApp webhook object")
    if not isinstance(approved_accounts, Mapping) or not approved_accounts:
        raise WhatsAppRoutingPreflightError("No verified business routing available")
    entries = payload.get("entry")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
        raise WhatsAppRoutingPreflightError("Malformed or oversized entries")

    results = []
    for entry_idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise WhatsAppRoutingPreflightError("Invalid entry")
        waba_id = _meta_id(entry.get("id"), "business account ID")
        changes = entry.get("changes")
        if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_CHANGES_PER_ENTRY:
            raise WhatsAppRoutingPreflightError("Malformed or oversized changes")
        for change_idx, change in enumerate(changes):
            if not isinstance(change, dict) or change.get("field") != "messages":
                raise WhatsAppRoutingPreflightError("Unsupported WhatsApp change")
            value = change.get("value")
            if not isinstance(value, dict):
                raise WhatsAppRoutingPreflightError("Malformed change value")
            metadata = value.get("metadata")
            if not isinstance(metadata, dict):
                raise WhatsAppRoutingPreflightError("Missing destination account metadata")
            phone_id = _meta_id(metadata.get("phone_number_id"), "phone number ID")
            has_messages = isinstance(value.get("messages"), list) and bool(value["messages"])
            has_statuses = isinstance(value.get("statuses"), list) and bool(value["statuses"])
            if has_messages == has_statuses:
                raise WhatsAppRoutingPreflightError("Missing or ambiguous event type")
            tenant_id = approved_accounts.get((waba_id, phone_id))
            if type(tenant_id) is not int or tenant_id < 1:
                raise WhatsAppRoutingPreflightError("Unverified WhatsApp destination account")
            results.append(AccountRoute(
                entry_index=entry_idx, change_index=change_idx,
                event_type="message" if has_messages else "status",
                tenant_id=tenant_id, waba_id=waba_id,
                phone_number_id=phone_id,
            ))

    # No partial acceptance: if any change was malformed, nothing is returned.
    return tuple(results)
