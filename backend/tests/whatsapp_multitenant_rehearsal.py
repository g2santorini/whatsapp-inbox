"""TEST-ONLY multi-company WhatsApp storage rehearsal. NOT imported by live code.

Only the disposable GitHub CI PostgreSQL at 127.0.0.1:55440/sendro_wa_ci
is allowed. Synthetic messages only. No Meta network, tokens, scheduler,
Render connection, live webhook, production schema or real customer data.
Tables are ephemeral `wa_ci_*` test fixtures, not Sendro migrations.
"""
import json
import os

from sqlalchemy import text

from backend.app.whatsapp_account_routing_preflight import (
    preflight_whatsapp_account_routes,
)
from backend.app.whatsapp_webhook_security import is_valid_meta_webhook_signature


class SyntheticDeliveryRejected(ValueError):
    """Untrusted or malformed delivery: never partially acknowledge."""


def _guard(engine):
    u = engine.url
    if not (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("SENDRO_WHATSAPP_PG_CI_APPROVAL")
        == "ephemeral-whatsapp-postgres-only"
        and u.drivername == "postgresql+psycopg"
        and u.host == "127.0.0.1"
        and u.port == 55440
        and u.database == "sendro_wa_ci"
        and u.username == "sendro_wa_ci"
    ):
        raise PermissionError("Refusing non-ephemeral WhatsApp test database")


def _id(item):
    if not isinstance(item, str) or not 1 <= len(item) <= 128:
        raise SyntheticDeliveryRejected("Missing provider identifier")
    return item


def _customer(item):
    if not isinstance(item, str) or not item.isascii() or not item.isdecimal():
        raise SyntheticDeliveryRejected("Invalid synthetic customer identifier")
    if not 6 <= len(item) <= 20:
        raise SyntheticDeliveryRejected("Invalid synthetic customer identifier")
    return item


def _events(payload, routes):
    """Validate *all* entries and event items before beginning any writes."""
    events = []
    for route in routes:
        value = payload["entry"][route.entry_index]["changes"][route.change_index]["value"]
        items = value.get("messages") if route.event_type == "message" else value.get("statuses")
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise SyntheticDeliveryRejected("Invalid event batch")
        for item in items:
            if not isinstance(item, dict):
                raise SyntheticDeliveryRejected("Invalid event")
            provider_id = _id(item.get("id"))
            if route.event_type == "status":
                status = item.get("status")
                if status not in ("sent", "delivered", "read", "failed"):
                    raise SyntheticDeliveryRejected("Unsupported status")
                events.append((route, "status", provider_id, status, None))
                continue
            kind = item.get("type")
            if kind == "text":
                phone = _customer(item.get("from"))
                text_value = item.get("text")
                if not isinstance(text_value, dict):
                    raise SyntheticDeliveryRejected("Missing text message")
                body = text_value.get("body")
                if not isinstance(body, str) or not 1 <= len(body) <= 4096:
                    raise SyntheticDeliveryRejected("Invalid message text")
                events.append((route, "inbound", provider_id, phone, body))
            elif kind == "reaction":
                reaction = item.get("reaction")
                if not isinstance(reaction, dict):
                    raise SyntheticDeliveryRejected("Invalid reaction")
                target = _id(reaction.get("message_id"))
                emoji = reaction.get("emoji")
                if not isinstance(emoji, str) or len(emoji) > 16:
                    raise SyntheticDeliveryRejected("Invalid reaction emoji")
                events.append((route, "reaction", provider_id, target, emoji))
            else:
                # Do not acknowledge unsupported media as successfully stored.
                raise SyntheticDeliveryRejected("Unsupported synthetic message type")
    return events


def _conversation_id(db, tenant_id, account_id, customer):
    return db.execute(text("""
        INSERT INTO public.wa_ci_conversations
            (tenant_id, account_id, external_customer_id)
        VALUES (:tenant, :account, :customer)
        ON CONFLICT (account_id, external_customer_id)
        DO UPDATE SET external_customer_id = EXCLUDED.external_customer_id
        RETURNING id
    """), {"tenant": tenant_id, "account": account_id,
           "customer": customer}).scalar_one()


def _accounts(db):
    rows = db.execute(text("""
        SELECT id, tenant_id, waba_id, phone_number_id
        FROM public.wa_ci_accounts
        WHERE status = 'active'
    """)).mappings().all()
    registry = {}
    account_ids = {}
    for item in rows:
        key = (item["waba_id"], item["phone_number_id"])
        if key in registry:
            raise SyntheticDeliveryRejected("Duplicate account owner")
        registry[key] = item["tenant_id"]
        account_ids[key] = item["id"]
    return registry, account_ids


def process_signed_synthetic_delivery(engine, raw_body, signature, *, app_secret):
    """Atomic account-verified synthetic ingestion. NEVER called in production."""
    _guard(engine)  # validate BEFORE opening a DB connection
    if not isinstance(raw_body, bytes) or not 1 <= len(raw_body) <= 131072:
        raise SyntheticDeliveryRejected("Invalid delivery size")
    if not is_valid_meta_webhook_signature(raw_body, signature, app_secret):
        raise SyntheticDeliveryRejected("Unverified Meta signature")
    try:
        payload = json.loads(raw_body)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise SyntheticDeliveryRejected("Invalid JSON") from exc

    totals = {"inbound": 0, "statuses": 0, "reactions": 0}
    with engine.begin() as db:
        registry, account_ids = _accounts(db)
        routes = preflight_whatsapp_account_routes(
            payload, registry, signature_verified=True
        )
        events = _events(payload, routes)
        for route, kind, provider_id, data1, data2 in events:
            account_id = account_ids[(route.waba_id, route.phone_number_id)]
            if kind == "inbound":
                conversation_id = _conversation_id(
                    db, route.tenant_id, account_id, data1
                )
                saved = db.execute(text("""
                    INSERT INTO public.wa_ci_messages (
                        tenant_id, account_id, conversation_id,
                        provider_message_id, direction, body, delivery_status
                    ) VALUES (
                        :tenant, :account, :conversation, :provider,
                        'inbound', :body, NULL
                    )
                    ON CONFLICT (account_id, provider_message_id) DO NOTHING
                    RETURNING id
                """), {"tenant": route.tenant_id, "account": account_id,
                       "conversation": conversation_id, "provider": provider_id,
                       "body": data2}).scalar_one_or_none()
                if saved is not None:
                    db.execute(text("""
                        UPDATE public.wa_ci_conversations SET unread_count=unread_count+1
                        WHERE id=:cid AND tenant_id=:tenant AND account_id=:account
                    """), {"cid": conversation_id, "tenant": route.tenant_id,
                           "account": account_id})
                    totals["inbound"] += 1
            elif kind == "status":
                # Only outbound messages under the EXACT receiving account.
                # No downgrade from read/delivered, no foreign-tenant updates.
                predecessors = {
                    "sent": ("pending",), "delivered": ("pending", "sent"),
                    "read": ("pending", "sent", "delivered"),
                    "failed": ("pending", "sent"),
                }[data1]
                changed = db.execute(text("""
                    UPDATE public.wa_ci_messages SET delivery_status=:new_status
                    WHERE tenant_id=:tenant AND account_id=:account
                      AND provider_message_id=:provider
                      AND direction='outbound'
                      AND delivery_status=ANY(:predecessors)
                """), {"new_status": data1, "tenant": route.tenant_id,
                       "account": account_id, "provider": provider_id,
                       "predecessors": list(predecessors)})
                totals["statuses"] += changed.rowcount
            else:
                original = db.execute(text("""
                    SELECT id FROM public.wa_ci_messages
                    WHERE tenant_id=:tenant AND account_id=:account
                      AND provider_message_id=:original
                """), {"tenant": route.tenant_id, "account": account_id,
                       "original": data1}).scalar_one_or_none()
                if original is None:
                    continue
                accepted = db.execute(text("""
                    INSERT INTO public.wa_ci_reactions
                        (tenant_id, account_id, provider_reaction_id, target_message_id)
                    VALUES (:tenant, :account, :reaction, :target)
                    ON CONFLICT (account_id, provider_reaction_id) DO NOTHING
                    RETURNING provider_reaction_id
                """), {"tenant": route.tenant_id, "account": account_id,
                       "reaction": provider_id, "target": original}).scalar_one_or_none()
                if accepted is not None:
                    db.execute(text("""
                        UPDATE public.wa_ci_messages SET reaction_emoji=:emoji
                        WHERE id=:original AND tenant_id=:tenant AND account_id=:account
                    """), {"emoji": data2, "original": original,
                           "tenant": route.tenant_id, "account": account_id})
                    totals["reactions"] += 1
    return totals  # deliberately no guest IDs/message contents/account IDs


def stage_outbound_synthetic_intent(engine, *, tenant_id, account_id,
                                    customer, provider_message_id):
    """Test-only persistence. Does NOT send a WhatsApp message."""
    _guard(engine)
    if type(tenant_id) is not int or type(account_id) is not int:
        raise SyntheticDeliveryRejected("Invalid outbound owner")
    customer = _customer(customer)
    provider_message_id = _id(provider_message_id)
    with engine.begin() as db:
        exists = db.execute(text("""
            SELECT 1 FROM public.wa_ci_accounts
            WHERE id=:account AND tenant_id=:tenant AND status='active'
        """), {"account": account_id, "tenant": tenant_id}).scalar_one_or_none()
        if exists is None:
            raise SyntheticDeliveryRejected("Unverified outbound account")
        cid = _conversation_id(db, tenant_id, account_id, customer)
        written = db.execute(text("""
            INSERT INTO public.wa_ci_messages (
                tenant_id, account_id, conversation_id, provider_message_id,
                direction, body, delivery_status
            ) VALUES (:tenant, :account, :cid, :provider, 'outbound', NULL, 'pending')
            ON CONFLICT (account_id, provider_message_id) DO NOTHING
            RETURNING id
        """), {"tenant": tenant_id, "account": account_id, "cid": cid,
               "provider": provider_message_id}).scalar_one_or_none()
        return {"created": written is not None}
