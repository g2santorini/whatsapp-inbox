import hashlib
import json
import os
import re

import requests
from datetime import datetime, timedelta
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import func, inspect, or_, text
from sqlalchemy.orm import Session

from . import models, schemas
from .database import Base, engine, get_db
from .template_registry import (
    build_template_variables,
    get_template_definition,
    missing_required_fields,
)
from .whatsapp_sender import (
    is_valid_e164_phone,
    send_whatsapp_reaction_message,
    send_whatsapp_template_message as send_meta_template_message,
)
from .reporting_service import get_template_report_items_data

load_dotenv()

app = FastAPI(title="WhatsApp Inbox")
APP_VERSION = "sendro-message-author-attribution-2026-05-07"

CORS_ALLOWED_ORIGINS = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,https://sendro-frontend.onrender.com",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip() for origin in CORS_ALLOWED_ORIGINS.split(",") if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "sendro_verify_token_123")
SENDRO_WEBHOOK_API_KEY = os.getenv("SENDRO_WEBHOOK_API_KEY")

Base.metadata.create_all(bind=engine)


def ensure_follow_up_column():
    inspector = inspect(engine)

    try:
        columns = [column["name"] for column in inspector.get_columns("conversations")]
    except Exception as exc:
        print("⚠️ Could not inspect conversations table:", exc, flush=True)
        return

    if "follow_up" in columns:
        return

    if engine.dialect.name == "postgresql":
        statement = text(
            "ALTER TABLE conversations "
            "ADD COLUMN follow_up BOOLEAN NOT NULL DEFAULT false"
        )
    else:
        statement = text(
            "ALTER TABLE conversations "
            "ADD COLUMN follow_up BOOLEAN NOT NULL DEFAULT 0"
        )

    with engine.begin() as connection:
        connection.execute(statement)

    print("✅ Added follow_up column to conversations table", flush=True)


def ensure_message_status_columns():
    inspector = inspect(engine)

    try:
        columns = [column["name"] for column in inspector.get_columns("messages")]
    except Exception as exc:
        print("⚠️ Could not inspect messages table:", exc, flush=True)
        return

    columns_to_add = []

    if "whatsapp_message_id" not in columns:
        columns_to_add.append(("whatsapp_message_id", "string"))

    if "whatsapp_status" not in columns:
        columns_to_add.append(("whatsapp_status", "string"))

    if "whatsapp_status_updated_at" not in columns:
        columns_to_add.append(("whatsapp_status_updated_at", "datetime"))

    if "message_type" not in columns:
        columns_to_add.append(("message_type", "string"))

    if "media_id" not in columns:
        columns_to_add.append(("media_id", "string"))

    if "media_mime_type" not in columns:
        columns_to_add.append(("media_mime_type", "string"))

    if "media_filename" not in columns:
        columns_to_add.append(("media_filename", "string"))

    if "reaction_emoji" not in columns:
        columns_to_add.append(("reaction_emoji", "string"))

    if "reaction_updated_at" not in columns:
        columns_to_add.append(("reaction_updated_at", "datetime"))

    if not columns_to_add:
        if "message_type" in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE messages "
                        "SET message_type = 'text' "
                        "WHERE message_type IS NULL OR message_type = ''"
                    )
                )
        return

    with engine.begin() as connection:
        for column_name, column_type in columns_to_add:
            if engine.dialect.name == "postgresql":
                if column_type == "datetime":
                    statement = text(
                        f"ALTER TABLE messages ADD COLUMN {column_name} TIMESTAMP"
                    )
                else:
                    statement = text(
                        f"ALTER TABLE messages ADD COLUMN {column_name} VARCHAR"
                    )
            else:
                if column_type == "datetime":
                    statement = text(
                        f"ALTER TABLE messages ADD COLUMN {column_name} DATETIME"
                    )
                else:
                    statement = text(
                        f"ALTER TABLE messages ADD COLUMN {column_name} VARCHAR"
                    )

            connection.execute(statement)
            print(f"✅ Added {column_name} column to messages table", flush=True)

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE messages "
                "SET message_type = 'text' "
                "WHERE message_type IS NULL OR message_type = ''"
            )
        )


def ensure_user_report_permission_column():
    inspector = inspect(engine)

    try:
        columns = [column["name"] for column in inspector.get_columns("users")]
    except Exception as exc:
        print("⚠️ Could not inspect users table:", exc, flush=True)
        return

    if "can_view_reports" in columns:
        return

    if engine.dialect.name == "postgresql":
        statement = text(
            "ALTER TABLE users "
            "ADD COLUMN can_view_reports BOOLEAN NOT NULL DEFAULT false"
        )
    else:
        statement = text(
            "ALTER TABLE users "
            "ADD COLUMN can_view_reports BOOLEAN NOT NULL DEFAULT 0"
        )

    with engine.begin() as connection:
        connection.execute(statement)

    print("✅ Added can_view_reports column to users table", flush=True)


ensure_follow_up_column()
ensure_message_status_columns()
ensure_user_report_permission_column()

app.mount("/static", StaticFiles(directory="app/static"), name="static")


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


SECRET_KEY = get_required_env("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))

WHATSAPP_ACCESS_TOKEN = get_required_env("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = get_required_env("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v25.0")
WHATSAPP_SEND_ENABLED = os.getenv("WHATSAPP_SEND_ENABLED", "true").lower() == "true"

CUSTOMER_SERVICE_WINDOW_HOURS = 24


def build_customer_service_window_fields(last_inbound_at: datetime | None) -> dict:
    if last_inbound_at is None:
        return {
            "customer_service_expires_at": None,
            "customer_service_window_open": False,
            "customer_service_time_left_seconds": None,
        }

    expires_at = last_inbound_at + timedelta(hours=CUSTOMER_SERVICE_WINDOW_HOURS)
    now = datetime.utcnow()
    seconds_left = int((expires_at - now).total_seconds())
    window_open = seconds_left > 0

    return {
        "customer_service_expires_at": expires_at,
        "customer_service_window_open": window_open,
        "customer_service_time_left_seconds": max(seconds_left, 0),
    }


def apply_customer_service_window_fields(
    conversation: models.Conversation,
    fields: dict,
):
    conversation.customer_service_expires_at = fields["customer_service_expires_at"]
    conversation.customer_service_window_open = fields["customer_service_window_open"]
    conversation.customer_service_time_left_seconds = fields[
        "customer_service_time_left_seconds"
    ]


def attach_customer_service_window_data(
    db: Session,
    conversations: list[models.Conversation],
):
    if not conversations:
        return conversations

    conversation_ids = [conversation.id for conversation in conversations]

    last_inbound_rows = (
        db.query(
            models.Message.conversation_id,
            func.max(models.Message.created_at).label("last_inbound_at"),
        )
        .filter(
            models.Message.conversation_id.in_(conversation_ids),
            models.Message.direction == "inbound",
        )
        .group_by(models.Message.conversation_id)
        .all()
    )

    last_inbound_by_conversation_id = {
        row.conversation_id: row.last_inbound_at for row in last_inbound_rows
    }

    latest_message_rows = (
        db.query(
            models.Message.conversation_id,
            func.max(models.Message.id).label("last_message_id"),
        )
        .filter(models.Message.conversation_id.in_(conversation_ids))
        .group_by(models.Message.conversation_id)
        .subquery()
    )

    last_message_direction_rows = (
        db.query(
            models.Message.conversation_id,
            models.Message.direction,
            models.Message.reaction_emoji,
        )
        .join(
            latest_message_rows,
            models.Message.id == latest_message_rows.c.last_message_id,
        )
        .all()
    )

    last_message_direction_by_conversation_id = {}

    for row in last_message_direction_rows:
        effective_direction = row.direction

        if row.direction == "inbound" and row.reaction_emoji:
            effective_direction = "outbound"

        last_message_direction_by_conversation_id[row.conversation_id] = (
            effective_direction
        )

    last_message_direction_by_conversation_id = {
        row.conversation_id: row.direction for row in last_message_direction_rows
    }

    for conversation in conversations:
        last_inbound_at = last_inbound_by_conversation_id.get(conversation.id)
        fields = build_customer_service_window_fields(last_inbound_at)
        apply_customer_service_window_fields(conversation, fields)

        conversation.last_message_direction = (
            last_message_direction_by_conversation_id.get(conversation.id)
        )

    return conversations


def attach_customer_service_window_to_conversation(
    db: Session,
    conversation: models.Conversation,
):
    attach_customer_service_window_data(db, [conversation])
    return conversation


def get_last_inbound_message_at(
    db: Session,
    conversation_id: int,
) -> datetime | None:
    return (
        db.query(func.max(models.Message.created_at))
        .filter(
            models.Message.conversation_id == conversation_id,
            models.Message.direction == "inbound",
        )
        .scalar()
    )


def ensure_customer_service_window_is_open(
    db: Session,
    conversation_id: int,
):
    last_inbound_at = get_last_inbound_message_at(db, conversation_id)
    customer_service_fields = build_customer_service_window_fields(last_inbound_at)

    if customer_service_fields["customer_service_window_open"]:
        return

    raise HTTPException(
        status_code=400,
        detail="Customer service session expired. Please send an approved template message.",
    )


def normalize_whatsapp_phone(phone: str) -> str:
    return phone.strip().replace("+", "").replace(" ", "")


def extract_whatsapp_message_id(whatsapp_result: dict | None) -> str | None:
    if not isinstance(whatsapp_result, dict):
        return None

    messages = whatsapp_result.get("messages")

    if not isinstance(messages, list) or not messages:
        return None

    first_message = messages[0]

    if not isinstance(first_message, dict):
        return None

    return first_message.get("id")


def get_or_create_sendro_webhook_user(db: Session) -> models.User:
    webhook_user = (
        db.query(models.User)
        .filter(
            or_(
                models.User.username == "sendro_webhook",
                models.User.email == "sendro_webhook@sendro.local",
            )
        )
        .first()
    )

    if webhook_user is not None:
        return webhook_user

    webhook_user = models.User(
        username="sendro_webhook",
        email="sendro_webhook@sendro.local",
        full_name="Sendro CRM Webhook",
        hashed_password=get_password_hash("not-for-login"),
        role="user",
        disabled=True,
    )

    db.add(webhook_user)
    db.commit()
    db.refresh(webhook_user)

    return webhook_user


def find_conversation_by_whatsapp_phone(
    db: Session,
    phone: str,
) -> models.Conversation | None:
    normalized_phone = normalize_whatsapp_phone(phone)

    return (
        db.query(models.Conversation)
        .filter(
            or_(
                models.Conversation.contact_phone == phone,
                models.Conversation.contact_phone == normalized_phone,
                models.Conversation.contact_phone == f"+{normalized_phone}",
            )
        )
        .order_by(models.Conversation.updated_at.desc())
        .first()
    )


def build_template_preview_content(template_type: str, item_data: dict) -> str:
    def value(field_name: str) -> str:
        raw_value = item_data.get(field_name)

        if raw_value is None:
            return ""

        return str(raw_value).strip()

    def fallback_preview() -> str:
        lines = [f"WhatsApp template sent: {template_type}"]

        fields = [
            ("external_id", "External ID"),
            ("guest_name", "Guest"),
            ("reservation_number", "Reservation"),
            ("tour_name", "Tour"),
            ("cruise_date", "Cruise date"),
            ("pickup_time", "Pickup time"),
            ("pickup_point", "Pickup point"),
            ("google_maps", "Google Maps"),
            ("passenger_info_link", "Passenger info link"),
        ]

        for field_name, label in fields:
            field_value = value(field_name)

            if field_value:
                lines.append(f"{label}: {field_value}")

        return "\n".join(lines)

    guest_name = value("guest_name")
    tour_name = value("tour_name")
    reservation_number = value("reservation_number")
    cruise_date = value("cruise_date")
    pickup_time = value("pickup_time")
    pickup_point = value("pickup_point")
    google_maps = value("google_maps")
    passenger_info_link = value("passenger_info_link")

    if template_type == "missing_hotel_details":
        return f"""Dear {guest_name},

Greetings from the beautiful Santorini, and thank you for choosing Sunset Oia for your sailing experience.

Regarding your reservation number {reservation_number}, please send us the name of your hotel so that we can arrange your pick-up time and meeting point.

If you are staying at an Airbnb, please send us the name of the accommodation, along with the contact details of your host.

We remain at your disposal for any additional information or clarification.

Best regards,
Sunset Oia Sailing Team"""

    if template_type == "pickup_reminder_meeting_point_missing_details":
        return f"""Dear {guest_name},

We are contacting you from Sunset Oia regarding your sailing cruise {tour_name} with reservation number {reservation_number}.

We would like to inform you / remind you that your pick-up time for your sailing cruise on {cruise_date} will be:

Pickup time & point: at {pickup_time} from {pickup_point}

Google Maps:
{google_maps}

Please click the link below to fill in the passenger details required by the port authorities:
{passenger_info_link}

Should you need any additional information regarding your cruise, please call us at 0030 22860 72200 or contact us on WhatsApp.

Best regards,
Sunset Oia Sailing Team"""

    if template_type == "pickup_reminder_meeting_point":
        return f"""Dear {guest_name},

We are contacting you from Sunset Oia regarding your sailing cruise {tour_name} with reservation number {reservation_number}.

We would like to inform you / remind you that your pick-up time for your sailing cruise on {cruise_date} will be:

Pickup time & point: at {pickup_time} from {pickup_point}

Google Maps:
{google_maps}

Should you need any additional information regarding your cruise, please call us at 0030 22860 72200 or contact us on WhatsApp.

Best regards,
Sunset Oia Sailing Team"""

    if template_type == "pickup_reminder_hotel_missing_details":
        return f"""Dear {guest_name},

We are contacting you from Sunset Oia regarding your sailing cruise {tour_name} with reservation number {reservation_number}.

We would like to inform you / remind you that your pick-up time for your sailing cruise on {cruise_date} will be:

Pickup time & point: at {pickup_time} from {pickup_point}

Please click the link below to fill in the passenger details required by the port authorities:
{passenger_info_link}

Should you need any additional information regarding your cruise, please call us at 0030 22860 72200 or contact us on WhatsApp.

Best regards,
Sunset Oia Sailing Team"""

    if template_type == "pickup_reminder_hotel":
        return f"""Dear {guest_name},

We are contacting you from Sunset Oia regarding your sailing cruise {tour_name} with reservation number {reservation_number}.

We would like to inform you / remind you that your pick-up time for your sailing cruise on {cruise_date} will be:

Pickup time & point: at {pickup_time} from {pickup_point}

Should you need any additional information regarding your cruise, please call us at 0030 22860 72200 or contact us on WhatsApp.

Best regards,
Sunset Oia Sailing Team"""

    if template_type == "cruise_pickup_reminder":
        return f"""Dear {guest_name},

We are contacting you from Sunset Oia regarding your sailing cruise {tour_name} with reservation number {reservation_number}.

We would like to remind you that your pick-up time for your cruise on {cruise_date} will be:

Pickup time & point: at {pickup_time} from {pickup_point}
Google Maps: {google_maps}

Should you need any additional information, feel free to contact us on WhatsApp.

Best regards,
Sunset Oia Sailing Team"""

    if template_type == "post_call_followup_request":
        return f"""Dear {guest_name},

Following our recent phone conversation regarding your interest in a sailing cruise, we kindly ask you to send us a message on WhatsApp so we can share the available options with you.

We look forward to assisting you.

Best regards,
Sunset Oia Sailing Team"""

    return fallback_preview()


def save_sent_template_message_to_sendro(
    db: Session,
    item: schemas.TemplateBatchItem,
    phone: str,
    whatsapp_message_id: str | None,
) -> models.Message:
    normalized_phone = normalize_whatsapp_phone(phone)
    now = datetime.utcnow()

    webhook_user = get_or_create_sendro_webhook_user(db)

    guest_name = item.guest_name.strip() if item.guest_name else None
    contact_name = guest_name or f"+{normalized_phone}"

    conversation = find_conversation_by_whatsapp_phone(db, phone)

    if conversation is None:
        conversation = models.Conversation(
            contact_name=contact_name,
            contact_phone=f"+{normalized_phone}",
            status="closed",
            assigned_to_user_id=None,
            unread_count=0,
            follow_up=False,
            last_message_at=now,
            created_at=now,
            updated_at=now,
            user_id=webhook_user.id,
        )

        db.add(conversation)
        db.flush()

    else:
        if guest_name:
            conversation.contact_name = guest_name

        conversation.contact_phone = f"+{normalized_phone}"
        conversation.status = "closed"
        conversation.assigned_to_user_id = None
        conversation.unread_count = 0
        conversation.follow_up = False
        conversation.last_message_at = now
        conversation.updated_at = now

    preview_content = build_template_preview_content(
        template_type=item.template_type,
        item_data=item.dict(),
    )

    db_message = models.Message(
        content=preview_content,
        direction="outbound",
        is_read=True,
        whatsapp_message_id=whatsapp_message_id,
        whatsapp_status="sent" if whatsapp_message_id else None,
        whatsapp_status_updated_at=now if whatsapp_message_id else None,
        user_id=webhook_user.id,
        conversation_id=conversation.id,
    )

    db.add(db_message)
    db.commit()
    db.refresh(db_message)

    return db_message


TEMPLATE_BATCH_STATUSES = {
    "sent",
    "failed",
    "no_number",
    "invalid_number",
    "validation_failed",
    "duplicate",
}


def normalize_template_batch_status(status_value: str | None) -> str | None:
    if not status_value:
        return None

    normalized_status = status_value.strip().lower()

    if normalized_status not in TEMPLATE_BATCH_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid status filter. Allowed values: "
                "sent, failed, no_number, invalid_number, validation_failed, duplicate"
            ),
        )

    return normalized_status


def build_template_batch_tour_name(batch: schemas.TemplateBatchRequest) -> str | None:
    for item in batch.items:
        if item.tour_name and item.tour_name.strip():
            return item.tour_name.strip()

    parts = [
        batch.vessel_name,
        batch.cruise_type,
        batch.cruise_slot,
    ]

    clean_parts = [part.strip() for part in parts if part and part.strip()]

    if clean_parts:
        return " ".join(clean_parts)

    return None


def build_template_duplicate_key(
    batch: schemas.TemplateBatchRequest,
    item: schemas.TemplateBatchItem,
    phone: str | None,
) -> str:
    parts = [
        batch.operation_date or "",
        batch.option_code or "",
        item.external_id or "",
        item.template_type or "",
        phone or item.phone or "",
    ]

    return "|".join(str(part).strip() for part in parts)


def build_template_content_hash(item: schemas.TemplateBatchItem) -> str:
    item_data = item.dict()

    hash_payload = {
        "template_type": item.template_type,
        "guest_name": item_data.get("guest_name"),
        "tour_name": item_data.get("tour_name"),
        "reservation_number": item_data.get("reservation_number"),
        "cruise_date": item_data.get("cruise_date"),
        "pickup_time": item_data.get("pickup_time"),
        "pickup_point": item_data.get("pickup_point"),
        "google_maps": item_data.get("google_maps"),
        "passenger_info_link": item_data.get("passenger_info_link"),
    }

    raw_payload = json.dumps(
        hash_payload,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )

    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()


def get_or_reset_template_batch_report(
    db: Session,
    batch: schemas.TemplateBatchRequest,
) -> models.TemplateBatch:
    now = datetime.utcnow()
    tour_name = build_template_batch_tour_name(batch)

    db_batch = (
        db.query(models.TemplateBatch)
        .filter(models.TemplateBatch.batch_id == batch.batch_id)
        .first()
    )

    if db_batch is not None:
        db_batch.batch_label = batch.batch_label
        db_batch.source = batch.source
        db_batch.event = batch.event
        db_batch.option_code = batch.option_code
        db_batch.operation_date = batch.operation_date
        db_batch.tour_name = tour_name
        db_batch.updated_at = now

    else:
        db_batch = models.TemplateBatch(
            batch_id=batch.batch_id,
            batch_label=batch.batch_label,
            source=batch.source,
            event=batch.event,
            option_code=batch.option_code,
            operation_date=batch.operation_date,
            tour_name=tour_name,
            total=0,
            sent=0,
            failed=0,
            no_number=0,
            invalid_number=0,
            validation_failed=0,
            duplicate=0,
            created_at=now,
            updated_at=now,
        )

        db.add(db_batch)

    db.commit()
    db.refresh(db_batch)

    return db_batch


def find_existing_sent_template_duplicate(
    db: Session,
    batch: schemas.TemplateBatchRequest,
    item: schemas.TemplateBatchItem,
    phone: str | None,
) -> models.TemplateBatchItem | None:
    duplicate_key = build_template_duplicate_key(batch, item, phone)
    content_hash = build_template_content_hash(item)

    return (
        db.query(models.TemplateBatchItem)
        .filter(
            models.TemplateBatchItem.duplicate_key == duplicate_key,
            models.TemplateBatchItem.content_hash == content_hash,
            models.TemplateBatchItem.status == "sent",
        )
        .order_by(models.TemplateBatchItem.created_at.desc())
        .first()
    )


def add_template_batch_item_report(
    db: Session,
    db_batch: models.TemplateBatch,
    batch: schemas.TemplateBatchRequest,
    item: schemas.TemplateBatchItem,
    status_value: str,
    reason: str | None = None,
    phone: str | None = None,
    whatsapp_message_id: str | None = None,
    saved_message: models.Message | None = None,
) -> models.TemplateBatchItem:
    now = datetime.utcnow()

    db_item = models.TemplateBatchItem(
        batch_db_id=db_batch.id,
        batch_id=batch.batch_id,
        external_id=item.external_id,
        reservation_number=item.reservation_number,
        guest_name=item.guest_name,
        phone=phone or item.phone,
        option_code=batch.option_code,
        operation_date=batch.operation_date,
        tour_name=item.tour_name or db_batch.tour_name,
        template_type=item.template_type,
        status=status_value,
        reason=reason,
        whatsapp_message_id=whatsapp_message_id,
        whatsapp_status="sent" if whatsapp_message_id else None,
        whatsapp_status_updated_at=now if whatsapp_message_id else None,
        conversation_id=saved_message.conversation_id if saved_message else None,
        message_id=saved_message.id if saved_message else None,
        duplicate_key=build_template_duplicate_key(batch, item, phone),
        content_hash=build_template_content_hash(item),
        created_at=now,
    )

    db.add(db_item)
    db.commit()
    db.refresh(db_item)

    return db_item


def recalculate_template_batch_counts(
    db: Session,
    batch_id: str,
) -> models.TemplateBatch | None:
    db_batch = (
        db.query(models.TemplateBatch)
        .filter(models.TemplateBatch.batch_id == batch_id)
        .first()
    )

    if db_batch is None:
        return None

    status_counts = {
        "sent": 0,
        "failed": 0,
        "no_number": 0,
        "invalid_number": 0,
        "validation_failed": 0,
        "duplicate": 0,
    }

    rows = (
        db.query(
            models.TemplateBatchItem.status,
            func.count(models.TemplateBatchItem.id),
        )
        .filter(models.TemplateBatchItem.batch_id == batch_id)
        .group_by(models.TemplateBatchItem.status)
        .all()
    )

    for status_name, count_value in rows:
        normalized_status = (status_name or "").strip().lower()

        if normalized_status in status_counts:
            status_counts[normalized_status] = count_value

    db_batch.total = (
        db.query(models.TemplateBatchItem)
        .filter(models.TemplateBatchItem.batch_id == batch_id)
        .count()
    )
    db_batch.sent = status_counts["sent"]
    db_batch.failed = status_counts["failed"]
    db_batch.no_number = status_counts["no_number"]
    db_batch.invalid_number = status_counts["invalid_number"]
    db_batch.validation_failed = status_counts["validation_failed"]
    db_batch.duplicate = status_counts["duplicate"]
    db_batch.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(db_batch)

    return db_batch


def extract_whatsapp_status_failure_reason(status_item: dict) -> str | None:
    errors = status_item.get("errors")

    if not isinstance(errors, list) or not errors:
        return None

    first_error = errors[0]

    if not isinstance(first_error, dict):
        return None

    error_title = first_error.get("title")
    error_message = first_error.get("message")
    error_code = first_error.get("code")

    parts = []

    if error_code:
        parts.append(f"Code: {error_code}")

    if error_title:
        parts.append(str(error_title))

    if error_message:
        parts.append(str(error_message))

    if not parts:
        return None

    return " - ".join(parts)


WHATSAPP_STATUS_PRIORITY = {
    "sent": 1,
    "delivered": 2,
    "read": 3,
    "failed": 4,
}


def should_update_whatsapp_status(
    current_status: str | None,
    new_status: str | None,
) -> bool:
    if not new_status:
        return False

    if not current_status:
        return True

    current_priority = WHATSAPP_STATUS_PRIORITY.get(current_status.lower(), 0)
    new_priority = WHATSAPP_STATUS_PRIORITY.get(new_status.lower(), 0)

    return new_priority >= current_priority


def send_whatsapp_text_message(to_phone: str, text: str):
    if not WHATSAPP_SEND_ENABLED:
        print("⚠️ WHATSAPP SEND DISABLED - message not sent", flush=True)
        return {"status": "disabled"}

    normalized_phone = normalize_whatsapp_phone(to_phone)

    url = (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": normalized_phone,
        "type": "text",
        "text": {
            "body": text,
        },
    }

    print("📤 SENDING WHATSAPP MESSAGE:", flush=True)
    print("URL:", url, flush=True)
    print("To:", normalized_phone, flush=True)
    print("Payload:", payload, flush=True)

    response = requests.post(url, headers=headers, json=payload, timeout=15)

    if response.status_code >= 400:
        print("❌ WHATSAPP SEND ERROR:", flush=True)
        print("Status:", response.status_code, flush=True)
        print("Response:", response.text, flush=True)
        print("Payload:", payload, flush=True)

        raise HTTPException(
            status_code=502,
            detail=f"WhatsApp send failed: {response.text}",
        )

    print("✅ WHATSAPP MESSAGE SENT:", flush=True)
    print(response.json(), flush=True)

    return response.json()


def send_whatsapp_template_message(
    to_phone: str,
    template_name: str,
    language_code: str,
    variables: list[str],
):
    if not WHATSAPP_SEND_ENABLED:
        print("⚠️ WHATSAPP TEMPLATE SEND DISABLED - message not sent", flush=True)
        return {"status": "disabled"}

    normalized_phone = normalize_whatsapp_phone(to_phone)

    url = (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": normalized_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language_code,
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": str(value),
                        }
                        for value in variables
                    ],
                }
            ],
        },
    }

    print("📨 SENDING WHATSAPP TEMPLATE MESSAGE:", flush=True)
    print("URL:", url, flush=True)
    print("To:", normalized_phone, flush=True)
    print("Template:", template_name, flush=True)
    print("Language:", language_code, flush=True)
    print("Variables:", variables, flush=True)

    response = requests.post(url, headers=headers, json=payload, timeout=15)

    if response.status_code >= 400:
        print("❌ WHATSAPP TEMPLATE SEND ERROR:", flush=True)
        print("Status:", response.status_code, flush=True)
        print("Response:", response.text, flush=True)
        print("Payload:", payload, flush=True)

        raise HTTPException(
            status_code=502,
            detail=f"WhatsApp template send failed: {response.text}",
        )

    print("✅ WHATSAPP TEMPLATE MESSAGE SENT:", flush=True)
    print(response.json(), flush=True)

    return response.json()


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


class FollowUpUpdate(BaseModel):
    follow_up: bool


class TemplateMessageRequest(BaseModel):
    contact_name: str | None = None
    contact_phone: str
    template_name: str = "cruise_pickup_reminder"
    language_code: str = "en"
    variables: list[str]
    preview_content: str


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

ALLOWED_USER_ROLES = {"admin", "power_user", "user"}


def is_admin(user: models.User) -> bool:
    return user.role == "admin"


def is_power_user(user: models.User) -> bool:
    return user.role == "power_user"


def can_view_all_conversations(user: models.User) -> bool:
    return is_admin(user) or is_power_user(user)


def can_override_conversation_assignment(user: models.User) -> bool:
    return is_admin(user) or is_power_user(user)


def can_view_template_reports(user: models.User) -> bool:
    return (
        is_admin(user)
        or is_power_user(user)
        or bool(getattr(user, "can_view_reports", False))
    )


def user_can_access_conversation(
    user: models.User,
    conversation: models.Conversation,
) -> bool:
    return True


def user_can_mark_conversation_as_read(
    user: models.User,
    conversation: models.Conversation,
) -> bool:
    return (
        conversation.assigned_to_user_id is None
        or conversation.assigned_to_user_id == user.id
        or can_override_conversation_assignment(user)
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_REGEX.match(email))


def create_initial_admin_if_needed():
    db = Session(bind=engine)

    try:
        existing_user_count = db.query(models.User).count()

        if existing_user_count > 0:
            return

        username = os.getenv("INITIAL_ADMIN_USERNAME")
        email = os.getenv("INITIAL_ADMIN_EMAIL")
        password = os.getenv("INITIAL_ADMIN_PASSWORD")

        if not username or not email or not password:
            print("⚠️ Initial admin was not created because env vars are missing.")
            return

        initial_admin = models.User(
            username=username.strip(),
            email=email.strip().lower(),
            full_name=username.strip(),
            hashed_password=get_password_hash(password),
            role="admin",
            disabled=False,
        )

        db.add(initial_admin)
        db.commit()

        print(f"✅ Initial admin user created: {username}")

    finally:
        db.close()


create_initial_admin_if_needed()


def get_user(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()


def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()


def get_conversation(db: Session, conversation_id: int):
    return (
        db.query(models.Conversation)
        .filter(models.Conversation.id == conversation_id)
        .first()
    )


def attach_message_author_data(
    db: Session,
    messages: list[models.Message],
):
    if not messages:
        return messages

    user_ids = {message.user_id for message in messages if message.user_id is not None}

    if not user_ids:
        return messages

    users = db.query(models.User).filter(models.User.id.in_(user_ids)).all()

    users_by_id = {user.id: user for user in users}

    for message in messages:
        author = users_by_id.get(message.user_id)

        if author is None:
            message.author_name = None
            message.author_username = None
            message.author_role = None
            continue

        display_name = (
            author.full_name.strip()
            if author.full_name and author.full_name.strip()
            else author.username
        )

        message.author_name = display_name
        message.author_username = author.username
        message.author_role = author.role

    return messages


def touch_conversation(conversation: models.Conversation):
    now = datetime.utcnow()
    conversation.updated_at = now
    conversation.last_message_at = now


def authenticate_user(db: Session, username: str, password: str):
    user = get_user(db, username)
    if not user:
        return False

    if not verify_password(password, user.hashed_password):
        return False

    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")

        if username is None:
            raise credentials_exception

        token_data = TokenData(username=username)

    except JWTError:
        raise credentials_exception

    user = get_user(db, username=token_data.username)

    if user is None:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: Annotated[models.User, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")

    return current_user


@app.post(
    "/webhooks/send-template",
    response_model=schemas.TemplateBatchResponse,
)
def send_template_webhook(
    batch: schemas.TemplateBatchRequest,
    x_sendro_webhook_key: str | None = Header(
        default=None,
        alias="X-Sendro-Webhook-Key",
    ),
    db: Session = Depends(get_db),
):
    if SENDRO_WEBHOOK_API_KEY:
        if x_sendro_webhook_key != SENDRO_WEBHOOK_API_KEY:
            raise HTTPException(
                status_code=401,
                detail="Invalid webhook API key",
            )
    else:
        print(
            "⚠️ SENDRO_WEBHOOK_API_KEY is not set. "
            "Webhook endpoint is not protected.",
            flush=True,
        )

    db_batch = get_or_reset_template_batch_report(db, batch)

    results: list[schemas.TemplateBatchResult] = []

    sent_count = 0
    failed_count = 0
    no_number_count = 0
    invalid_number_count = 0
    validation_failed_count = 0
    duplicate_count = 0

    for item in batch.items:
        item_data = item.dict()

        external_id = item.external_id
        template_type = item.template_type
        phone = item.phone.strip() if item.phone else None

        if not phone:
            no_number_count += 1

            reason = "Phone number is empty or missing"

            add_template_batch_item_report(
                db=db,
                db_batch=db_batch,
                batch=batch,
                item=item,
                status_value="no_number",
                reason=reason,
                phone=item.phone,
            )

            results.append(
                schemas.TemplateBatchResult(
                    external_id=external_id,
                    template_type=template_type,
                    phone=item.phone,
                    status="no_number",
                    reason=reason,
                )
            )
            continue

        if not is_valid_e164_phone(phone):
            invalid_number_count += 1

            reason = "Phone number must be in E.164 format, for example +306900000000"

            add_template_batch_item_report(
                db=db,
                db_batch=db_batch,
                batch=batch,
                item=item,
                status_value="invalid_number",
                reason=reason,
                phone=phone,
            )

            results.append(
                schemas.TemplateBatchResult(
                    external_id=external_id,
                    template_type=template_type,
                    phone=phone,
                    status="invalid_number",
                    reason=reason,
                )
            )
            continue

        try:
            template_definition = get_template_definition(template_type)
        except KeyError as exc:
            validation_failed_count += 1

            reason = str(exc)

            add_template_batch_item_report(
                db=db,
                db_batch=db_batch,
                batch=batch,
                item=item,
                status_value="validation_failed",
                reason=reason,
                phone=phone,
            )

            results.append(
                schemas.TemplateBatchResult(
                    external_id=external_id,
                    template_type=template_type,
                    phone=phone,
                    status="validation_failed",
                    reason=reason,
                )
            )
            continue

        missing_fields = missing_required_fields(template_type, item_data)

        if missing_fields:
            validation_failed_count += 1

            reason = f"Missing required fields: {', '.join(missing_fields)}"

            add_template_batch_item_report(
                db=db,
                db_batch=db_batch,
                batch=batch,
                item=item,
                status_value="validation_failed",
                reason=reason,
                phone=phone,
            )

            results.append(
                schemas.TemplateBatchResult(
                    external_id=external_id,
                    template_type=template_type,
                    phone=phone,
                    status="validation_failed",
                    reason=reason,
                )
            )
            continue

        body_variables = build_template_variables(template_type, item_data)

        existing_duplicate = find_existing_sent_template_duplicate(
            db=db,
            batch=batch,
            item=item,
            phone=phone,
        )

        if existing_duplicate is not None:
            duplicate_count += 1

            reason = (
                "Duplicate template blocked. "
                f"Already sent in batch {existing_duplicate.batch_id}, "
                f"item_id {existing_duplicate.id}, "
                f"message_id {existing_duplicate.message_id}, "
                f"whatsapp_message_id {existing_duplicate.whatsapp_message_id}."
            )

            add_template_batch_item_report(
                db=db,
                db_batch=db_batch,
                batch=batch,
                item=item,
                status_value="duplicate",
                reason=reason,
                phone=phone,
            )

            results.append(
                schemas.TemplateBatchResult(
                    external_id=external_id,
                    template_type=template_type,
                    phone=phone,
                    status="duplicate",
                    reason=reason,
                    whatsapp_message_id=None,
                )
            )
            continue

        try:
            whatsapp_result = send_meta_template_message(
                to_phone=phone,
                template_name=template_definition.meta_template_name,
                language_code=template_definition.language_code,
                body_variables=body_variables,
            )

            whatsapp_message_id = extract_whatsapp_message_id(whatsapp_result)

        except Exception as exc:
            failed_count += 1

            reason = str(exc)

            add_template_batch_item_report(
                db=db,
                db_batch=db_batch,
                batch=batch,
                item=item,
                status_value="failed",
                reason=reason,
                phone=phone,
            )

            results.append(
                schemas.TemplateBatchResult(
                    external_id=external_id,
                    template_type=template_type,
                    phone=phone,
                    status="failed",
                    reason=reason,
                )
            )
            continue

        save_warning = None
        saved_message = None

        try:
            saved_message = save_sent_template_message_to_sendro(
                db=db,
                item=item,
                phone=phone,
                whatsapp_message_id=whatsapp_message_id,
            )

            print(
                f"✅ TEMPLATE SAVED IN SENDRO: "
                f"conversation_id={saved_message.conversation_id} "
                f"message_id={saved_message.id} "
                f"wamid={whatsapp_message_id}",
                flush=True,
            )

        except Exception as exc:
            db.rollback()
            save_warning = (
                "WhatsApp template was sent, but Sendro could not save "
                "the message. Check backend logs."
            )

            print(
                f"⚠️ TEMPLATE SENT BUT NOT SAVED IN SENDRO: "
                f"external_id={external_id} "
                f"phone={phone} "
                f"wamid={whatsapp_message_id} "
                f"error={exc}",
                flush=True,
            )

        sent_count += 1

        add_template_batch_item_report(
            db=db,
            db_batch=db_batch,
            batch=batch,
            item=item,
            status_value="sent",
            reason=save_warning,
            phone=phone,
            whatsapp_message_id=whatsapp_message_id,
            saved_message=saved_message,
        )

        results.append(
            schemas.TemplateBatchResult(
                external_id=external_id,
                template_type=template_type,
                phone=phone,
                status="sent",
                reason=save_warning,
                whatsapp_message_id=whatsapp_message_id,
            )
        )

    recalculate_template_batch_counts(db, batch.batch_id)

    return schemas.TemplateBatchResponse(
        batch_id=batch.batch_id,
        batch_label=batch.batch_label,
        total=len(batch.items),
        sent=sent_count,
        failed=failed_count,
        no_number=no_number_count,
        invalid_number=invalid_number_count,
        validation_failed=validation_failed_count,
        duplicate=duplicate_count,
        results=results,
    )


@app.get(
    "/template-batches/",
    response_model=list[schemas.TemplateBatchReportSummaryOut],
)
def get_template_batches(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
    operation_date: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    option_code: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    whatsapp_status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if not can_view_template_reports(current_user):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view template batch reports",
        )

    query = db.query(models.TemplateBatch)

    if operation_date:
        query = query.filter(models.TemplateBatch.operation_date == operation_date)

    if date_from:
        query = query.filter(models.TemplateBatch.operation_date >= date_from)

    if date_to:
        query = query.filter(models.TemplateBatch.operation_date <= date_to)

    if option_code:
        query = query.filter(models.TemplateBatch.option_code == option_code.strip())

    normalized_status = normalize_template_batch_status(status_filter)

    if normalized_status:
        status_column = getattr(models.TemplateBatch, normalized_status)
        query = query.filter(status_column > 0)

    if whatsapp_status:
        normalized_whatsapp_status = whatsapp_status.strip().lower()

        matching_batch_ids = (
            db.query(models.TemplateBatchItem.batch_id)
            .filter(
                models.TemplateBatchItem.whatsapp_status == normalized_whatsapp_status
            )
            .subquery()
        )

        query = query.filter(models.TemplateBatch.batch_id.in_(matching_batch_ids))

    search_query = q.strip() if q else ""

    if search_query:
        search_pattern = f"%{search_query}%"

        query = query.filter(
            or_(
                models.TemplateBatch.batch_id.ilike(search_pattern),
                models.TemplateBatch.batch_label.ilike(search_pattern),
                models.TemplateBatch.option_code.ilike(search_pattern),
                models.TemplateBatch.tour_name.ilike(search_pattern),
            )
        )

    return (
        query.order_by(models.TemplateBatch.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@app.get(
    "/template-batches/{batch_id}",
    response_model=schemas.TemplateBatchReportDetailOut,
)
def get_template_batch_detail(
    batch_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
    status_filter: str | None = Query(default=None, alias="status"),
    whatsapp_status: str | None = Query(default=None),
):
    if not can_view_template_reports(current_user):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view template batch reports",
        )

    db_batch = (
        db.query(models.TemplateBatch)
        .filter(models.TemplateBatch.batch_id == batch_id)
        .first()
    )

    if db_batch is None:
        raise HTTPException(status_code=404, detail="Template batch not found")

    items_query = db.query(models.TemplateBatchItem).filter(
        models.TemplateBatchItem.batch_id == batch_id
    )

    normalized_status = normalize_template_batch_status(status_filter)

    if normalized_status:
        items_query = items_query.filter(
            models.TemplateBatchItem.status == normalized_status
        )

    if whatsapp_status:
        items_query = items_query.filter(
            models.TemplateBatchItem.whatsapp_status == whatsapp_status.strip().lower()
        )

    db_batch.items = items_query.order_by(models.TemplateBatchItem.id.asc()).all()

    return db_batch


@app.get(
    "/template-report-items/",
    response_model=schemas.TemplateReportItemsResponse,
)
def get_template_report_items(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
    operation_date: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    option_code: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    whatsapp_status: str | None = Query(default=None),
    time_slot: str | None = Query(default=None),
    result_status: str | None = Query(default=None),
    problems_only: bool = Query(default=False),
    q: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if not can_view_template_reports(current_user):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view template reports",
        )

    return get_template_report_items_data(
        db=db,
        operation_date=operation_date,
        date_from=date_from,
        date_to=date_to,
        option_code=option_code,
        status_filter=status_filter,
        whatsapp_status=whatsapp_status,
        time_slot=time_slot,
        result_status=result_status,
        problems_only=problems_only,
        q=q,
        limit=limit,
        offset=offset,
    )


@app.get("/webhook/whatsapp")
def verify_whatsapp_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return int(hub_challenge)

    raise HTTPException(status_code=403, detail="Invalid verify token")


@app.post("/webhook/whatsapp")
async def receive_whatsapp_message(
    request: Request,
    db: Session = Depends(get_db),
):
    data = await request.json()

    try:
        entry = data["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

        if "statuses" in value:
            statuses = value.get("statuses", [])

            for status_item in statuses:
                whatsapp_message_id = status_item.get("id")
                whatsapp_status = status_item.get("status")
                timestamp_value = status_item.get("timestamp")

                if not whatsapp_message_id or not whatsapp_status:
                    continue

                status_updated_at = datetime.utcnow()

                if timestamp_value:
                    try:
                        status_updated_at = datetime.utcfromtimestamp(
                            int(timestamp_value)
                        )
                    except (TypeError, ValueError):
                        status_updated_at = datetime.utcnow()

                db_message = (
                    db.query(models.Message)
                    .filter(models.Message.whatsapp_message_id == whatsapp_message_id)
                    .first()
                )

                db_batch_items = (
                    db.query(models.TemplateBatchItem)
                    .filter(
                        models.TemplateBatchItem.whatsapp_message_id
                        == whatsapp_message_id
                    )
                    .all()
                )

                if db_message is None and not db_batch_items:
                    print(
                        f"⚠️ WHATSAPP STATUS FOR UNKNOWN MESSAGE: "
                        f"{whatsapp_message_id} -> {whatsapp_status}",
                        flush=True,
                    )
                    continue

                if db_message is not None:
                    if not should_update_whatsapp_status(
                        db_message.whatsapp_status,
                        whatsapp_status,
                    ):
                        print(
                            f"ℹ️ WHATSAPP STATUS IGNORED DOWNGRADE: "
                            f"message_id={db_message.id} "
                            f"wamid={whatsapp_message_id} "
                            f"current={db_message.whatsapp_status} "
                            f"new={whatsapp_status}",
                            flush=True,
                        )
                        continue

                    db_message.whatsapp_status = whatsapp_status
                    db_message.whatsapp_status_updated_at = status_updated_at

                    print(
                        f"✅ WHATSAPP MESSAGE STATUS UPDATED: "
                        f"message_id={db_message.id} "
                        f"wamid={whatsapp_message_id} "
                        f"status={whatsapp_status}",
                        flush=True,
                    )

                failure_reason = None

                if whatsapp_status and whatsapp_status.lower() == "failed":
                    failure_reason = extract_whatsapp_status_failure_reason(status_item)

                updated_batch_items_count = 0

                for db_batch_item in db_batch_items:
                    if not should_update_whatsapp_status(
                        db_batch_item.whatsapp_status,
                        whatsapp_status,
                    ):
                        continue

                    db_batch_item.whatsapp_status = whatsapp_status
                    db_batch_item.whatsapp_status_updated_at = status_updated_at

                    if failure_reason:
                        db_batch_item.reason = failure_reason

                    updated_batch_items_count += 1

                if updated_batch_items_count:
                    print(
                        f"✅ TEMPLATE BATCH ITEM STATUS UPDATED: "
                        f"wamid={whatsapp_message_id} "
                        f"status={whatsapp_status} "
                        f"items={updated_batch_items_count}",
                        flush=True,
                    )

            db.commit()
            return {"status": "ok"}

        if "messages" not in value:
            print("ℹ️ WHATSAPP WEBHOOK RECEIVED WITHOUT MESSAGE", flush=True)
            print(value, flush=True)
            return {"status": "ok"}

        message = value["messages"][0]
        contact = value["contacts"][0]

        whatsapp_message_id = message.get("id")
        message_type = message.get("type", "unknown")

        media_id = None
        media_mime_type = None
        media_filename = None

        if message_type == "text":
            text = message.get("text", {}).get("body", "")

        elif message_type == "button":
            button = message.get("button", {})
            text = button.get("text") or button.get("payload") or "[Button reply]"

        elif message_type == "interactive":
            interactive = message.get("interactive", {})
            button_reply = interactive.get("button_reply") or {}
            list_reply = interactive.get("list_reply") or {}

            text = (
                button_reply.get("title")
                or list_reply.get("title")
                or "[Interactive message]"
            )

        elif message_type == "reaction":
            reaction = message.get("reaction", {})
            reaction_message_id = reaction.get("message_id")
            emoji = str(reaction.get("emoji") or "").strip()

            original_message = None

            if reaction_message_id:
                original_message = (
                    db.query(models.Message)
                    .filter(models.Message.whatsapp_message_id == reaction_message_id)
                    .first()
                )

            if original_message is not None:
                original_message.reaction_emoji = emoji or None
                original_message.reaction_updated_at = datetime.utcnow()

                db.commit()

                print(
                    f"[REACTION] original_message_id={original_message.id} "
                    f"original_wamid={reaction_message_id} "
                    f"reaction_wamid={whatsapp_message_id} "
                    f"emoji={emoji!r}",
                    flush=True,
                )

                return {"status": "ok"}

            print(
                f"[REACTION_UNMATCHED] "
                f"original_wamid={reaction_message_id} "
                f"reaction_wamid={whatsapp_message_id} "
                f"emoji={emoji!r}",
                flush=True,
            )

            return {"status": "ok"}

        elif message_type == "image":
            image = message.get("image", {})
            caption = str(image.get("caption") or "").strip()

            media_id = image.get("id")
            media_mime_type = image.get("mime_type")
            media_filename = None

            text = "Photo received"

            if caption:
                text = f"{text}\nCaption: {caption}"

        elif message_type == "document":
            document = message.get("document", {})
            filename = str(document.get("filename") or "").strip()
            caption = str(document.get("caption") or "").strip()

            media_id = document.get("id")
            media_mime_type = document.get("mime_type")
            media_filename = filename or None

            text = "Document received"

            if filename:
                text = f"{text}: {filename}"

            if caption:
                text = f"{text}\nCaption: {caption}"

        elif message_type == "video":
            video = message.get("video", {})
            caption = str(video.get("caption") or "").strip()

            media_id = video.get("id")
            media_mime_type = video.get("mime_type")
            media_filename = None

            text = "Video received"

            if caption:
                text = f"{text}\nCaption: {caption}"

        elif message_type == "audio":
            audio = message.get("audio", {})

            media_id = audio.get("id")
            media_mime_type = audio.get("mime_type")
            media_filename = None

            text = "Audio message received"

        elif message_type == "sticker":
            sticker = message.get("sticker", {})

            media_id = sticker.get("id")
            media_mime_type = sticker.get("mime_type")
            media_filename = None

            text = "Sticker received"

        else:
            text = f"[Unsupported WhatsApp message type: {message_type}]"

        if not text:
            text = f"[Unsupported WhatsApp message type: {message_type}]"

        phone = message["from"]
        normalized_phone = normalize_whatsapp_phone(phone)
        name = contact["profile"]["name"]

        webhook_user = db.query(models.User).first()

        if webhook_user is None:
            webhook_user = models.User(
                username="whatsapp_webhook",
                email="whatsapp_webhook@sendro.local",
                full_name="WhatsApp Webhook",
                hashed_password=get_password_hash("change-me-later"),
                role="admin",
                disabled=False,
            )
            db.add(webhook_user)
            db.commit()
            db.refresh(webhook_user)

        conversation = (
            db.query(models.Conversation)
            .filter(
                or_(
                    models.Conversation.contact_phone == phone,
                    models.Conversation.contact_phone == normalized_phone,
                    models.Conversation.contact_phone == f"+{normalized_phone}",
                )
            )
            .order_by(models.Conversation.updated_at.desc())
            .first()
        )

        now = datetime.utcnow()

        if conversation is None:
            conversation = models.Conversation(
                contact_name=name,
                contact_phone=f"+{normalized_phone}",
                status="open",
                assigned_to_user_id=None,
                unread_count=0,
                last_message_at=now,
                created_at=now,
                updated_at=now,
                user_id=webhook_user.id,
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)

        db_message = models.Message(
            content=text,
            direction="inbound",
            is_read=False,
            whatsapp_message_id=whatsapp_message_id,
            message_type=message_type,
            media_id=media_id,
            media_mime_type=media_mime_type,
            media_filename=media_filename,
            user_id=webhook_user.id,
            conversation_id=conversation.id,
        )

        db.add(db_message)

        conversation.status = "open"
        conversation.follow_up = False
        conversation.unread_count = (conversation.unread_count or 0) + 1
        conversation.last_message_at = now
        conversation.updated_at = now

        db.commit()
        db.refresh(db_message)

        print("📩 SAVED WHATSAPP MESSAGE:", flush=True)
        print("Conversation ID:", conversation.id, flush=True)
        print("Message ID:", db_message.id, flush=True)
        print("Name:", name, flush=True)
        print("Phone:", phone, flush=True)
        print("Message type:", message_type, flush=True)
        print("WhatsApp message ID:", whatsapp_message_id, flush=True)
        print("Media ID:", media_id, flush=True)
        print("Media MIME type:", media_mime_type, flush=True)
        print("Media filename:", media_filename, flush=True)
        print("Text:", text, flush=True)

    except Exception as e:
        print("❌ Error saving WhatsApp message:", e, flush=True)

    return {"status": "ok"}


@app.post(
    "/users/",
    response_model=schemas.UserOut,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    user: schemas.UserCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only admins can create users",
        )

    username = user.username.strip()
    email = user.email.strip().lower()
    full_name = user.full_name.strip() if user.full_name else None
    requested_role = (user.role or "user").strip().lower()

    if not username:
        raise HTTPException(
            status_code=400,
            detail="Username cannot be empty",
        )

    if not is_valid_email(email):
        raise HTTPException(
            status_code=400,
            detail="Please enter a valid email address",
        )

    if requested_role not in ALLOWED_USER_ROLES:
        raise HTTPException(
            status_code=400,
            detail="Invalid role. Allowed roles: admin, power_user, user",
        )

    existing_user = get_user(db, username)
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    existing_email = get_user_by_email(db, email)
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = get_password_hash(user.password)

    db_user = models.User(
        username=username,
        email=email,
        full_name=full_name,
        hashed_password=hashed_password,
        role=requested_role,
        disabled=False,
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


@app.get("/users/", response_model=list[schemas.UserOut])
def get_users(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    users = db.query(models.User).order_by(models.User.full_name.asc()).all()
    return users


@app.patch("/users/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    user_update: schemas.UserUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only admins can update users",
        )

    db_user = db.query(models.User).filter(models.User.id == user_id).first()

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    new_username = None
    new_email = None
    new_full_name = None
    new_role = None

    if user_update.username is not None:
        new_username = user_update.username.strip()

        if not new_username:
            raise HTTPException(
                status_code=400,
                detail="Username cannot be empty",
            )

        if db_user.id == current_user.id and new_username != db_user.username:
            raise HTTPException(
                status_code=400,
                detail="You cannot change your own username",
            )

        existing_username = (
            db.query(models.User)
            .filter(
                models.User.username == new_username,
                models.User.id != user_id,
            )
            .first()
        )

        if existing_username:
            raise HTTPException(
                status_code=400,
                detail="Username already registered",
            )

    if user_update.email is not None:
        new_email = user_update.email.strip().lower()

        if not new_email:
            raise HTTPException(
                status_code=400,
                detail="Email cannot be empty",
            )

        if not is_valid_email(new_email):
            raise HTTPException(
                status_code=400,
                detail="Please enter a valid email address",
            )

        existing_email = (
            db.query(models.User)
            .filter(
                models.User.email == new_email,
                models.User.id != user_id,
            )
            .first()
        )

    if user_update.full_name is not None:
        new_full_name = user_update.full_name.strip() or None

    if user_update.role is not None:
        new_role = user_update.role.strip().lower()

        if new_role not in ALLOWED_USER_ROLES:
            raise HTTPException(
                status_code=400,
                detail="Invalid role. Allowed roles: admin, power_user, user",
            )

        if db_user.id == current_user.id and new_role != "admin":
            raise HTTPException(
                status_code=400,
                detail="You cannot remove your own admin role",
            )

    if user_update.disabled is not None:
        if db_user.id == current_user.id and user_update.disabled:
            raise HTTPException(
                status_code=400,
                detail="You cannot disable your own account",
            )

    is_admin_role_being_removed = (
        db_user.role == "admin" and new_role is not None and new_role != "admin"
    )

    is_admin_being_disabled = db_user.role == "admin" and user_update.disabled is True

    if is_admin_role_being_removed or is_admin_being_disabled:
        active_admin_count = (
            db.query(models.User)
            .filter(
                models.User.role == "admin",
                models.User.disabled.is_(False),
            )
            .count()
        )

        if active_admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="You cannot remove or disable the last active admin",
            )

    if new_username is not None:
        db_user.username = new_username

    if new_email is not None:
        db_user.email = new_email

    if user_update.full_name is not None:
        db_user.full_name = new_full_name

    if new_role is not None:
        db_user.role = new_role

    if user_update.disabled is not None:
        db_user.disabled = user_update.disabled

    if user_update.can_view_reports is not None:
        db_user.can_view_reports = user_update.can_view_reports

    db.commit()
    db.refresh(db_user)

    return db_user


@app.patch("/users/{user_id}/password", response_model=schemas.UserOut)
def reset_user_password(
    user_id: int,
    password_reset: schemas.UserPasswordReset,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only admins can reset user passwords",
        )

    db_user = db.query(models.User).filter(models.User.id == user_id).first()

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    new_password = password_reset.password.strip()

    if len(new_password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 6 characters long",
        )

    db_user.hashed_password = get_password_hash(new_password)

    db.commit()
    db.refresh(db_user)

    return db_user


@app.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
):
    user = authenticate_user(db, form_data.username, form_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires,
    )

    return Token(access_token=access_token, token_type="bearer")


@app.get("/users/me/", response_model=schemas.UserOut)
async def read_users_me(
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    return current_user


@app.get("/conversations/", response_model=list[schemas.ConversationOut])
def get_conversations(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
    q: str | None = Query(default=None),
):
    query = db.query(models.Conversation)

    search_query = q.strip() if q else ""

    if search_query:
        search_pattern = f"%{search_query}%"

        matching_message_conversation_ids = (
            db.query(models.Message.conversation_id)
            .filter(models.Message.content.ilike(search_pattern))
            .subquery()
        )

        query = query.filter(
            or_(
                models.Conversation.contact_name.ilike(search_pattern),
                models.Conversation.contact_phone.ilike(search_pattern),
                models.Conversation.status.ilike(search_pattern),
                models.Conversation.id.in_(matching_message_conversation_ids),
            )
        )

    conversations = query.order_by(models.Conversation.updated_at.desc()).all()

    return attach_customer_service_window_data(db, conversations)


@app.post(
    "/conversations/send-template/",
    response_model=schemas.ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation_and_send_template(
    template_request: TemplateMessageRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    contact_phone = template_request.contact_phone.strip()
    normalized_phone = normalize_whatsapp_phone(contact_phone)

    contact_name = (
        template_request.contact_name.strip()
        if template_request.contact_name and template_request.contact_name.strip()
        else f"+{normalized_phone}"
    )

    if not normalized_phone.isdigit():
        raise HTTPException(
            status_code=400,
            detail="Phone number must include country code, for example +306900000000",
        )

    template_type = template_request.template_name.strip()

    try:
        template_definition = get_template_definition(template_type)
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    expected_variable_count = len(template_definition.body_variable_order)

    if len(template_request.variables) != expected_variable_count:
        expected_fields = ", ".join(template_definition.body_variable_order)
        raise HTTPException(
            status_code=400,
            detail=(
                f"{template_type} requires exactly {expected_variable_count} "
                f"variables: {expected_fields}"
            ),
        )

    cleaned_variables = [
        str(variable or "").strip() for variable in template_request.variables
    ]

    missing_variable_labels = [
        field_name
        for field_name, variable_value in zip(
            template_definition.body_variable_order,
            cleaned_variables,
        )
        if not variable_value
    ]

    if missing_variable_labels:
        raise HTTPException(
            status_code=400,
            detail=(
                "Missing required template values: "
                + ", ".join(missing_variable_labels)
            ),
        )

    preview_content = template_request.preview_content.strip()

    if not preview_content:
        raise HTTPException(
            status_code=400,
            detail="Preview content is required",
        )

    whatsapp_result = send_whatsapp_template_message(
        to_phone=f"+{normalized_phone}",
        template_name=template_definition.meta_template_name,
        language_code=template_definition.language_code,
        variables=cleaned_variables,
    )

    whatsapp_message_id = extract_whatsapp_message_id(whatsapp_result)
    now = datetime.utcnow()

    conversation = (
        db.query(models.Conversation)
        .filter(
            or_(
                models.Conversation.contact_phone == contact_phone,
                models.Conversation.contact_phone == normalized_phone,
                models.Conversation.contact_phone == f"+{normalized_phone}",
            )
        )
        .order_by(models.Conversation.updated_at.desc())
        .first()
    )

    if conversation is None:
        conversation = models.Conversation(
            contact_name=contact_name,
            contact_phone=f"+{normalized_phone}",
            status="closed",
            assigned_to_user_id=None,
            unread_count=0,
            follow_up=False,
            last_message_at=now,
            created_at=now,
            updated_at=now,
            user_id=current_user.id,
        )

        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    else:
        conversation.contact_name = contact_name
        conversation.contact_phone = f"+{normalized_phone}"
        conversation.status = "closed"
        conversation.assigned_to_user_id = None
        conversation.unread_count = 0
        conversation.follow_up = False
        conversation.last_message_at = now
        conversation.updated_at = now

    db_message = models.Message(
        content=preview_content,
        direction="outbound",
        is_read=True,
        whatsapp_message_id=whatsapp_message_id,
        whatsapp_status="sent" if whatsapp_message_id else None,
        whatsapp_status_updated_at=now if whatsapp_message_id else None,
        user_id=current_user.id,
        conversation_id=conversation.id,
    )

    db.add(db_message)
    db.commit()
    db.refresh(conversation)

    print(
        f"[SEND_TEMPLATE] conversation_id={conversation.id} "
        f"user_id={current_user.id} "
        f"template_type={template_type} "
        f"meta_template={template_definition.meta_template_name} "
        f"wamid={whatsapp_message_id} "
        f"whatsapp_result={whatsapp_result}",
        flush=True,
    )

    return attach_customer_service_window_to_conversation(db, conversation)


@app.post(
    "/conversations/",
    response_model=schemas.ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    conversation: schemas.ConversationCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    now = datetime.utcnow()

    normalized_phone = normalize_whatsapp_phone(conversation.contact_phone)

    db_conversation = models.Conversation(
        contact_name=conversation.contact_name,
        contact_phone=f"+{normalized_phone}",
        status="open",
        assigned_to_user_id=None,
        unread_count=0,
        last_message_at=now,
        created_at=now,
        updated_at=now,
        user_id=current_user.id,
    )

    db.add(db_conversation)
    db.commit()
    db.refresh(db_conversation)

    return attach_customer_service_window_to_conversation(db, db_conversation)


@app.get(
    "/conversations/{conversation_id}/messages/",
    response_model=list[schemas.MessageOut],
)
def get_conversation_messages(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not user_can_access_conversation(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation",
        )

    messages = (
        db.query(models.Message)
        .filter(models.Message.conversation_id == conversation_id)
        .order_by(models.Message.created_at.asc())
        .all()
    )

    return attach_message_author_data(db, messages)


@app.get("/messages/{message_id}/media")
def get_message_media(
    message_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    db_message = (
        db.query(models.Message).filter(models.Message.id == message_id).first()
    )

    if db_message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    if not db_message.media_id:
        raise HTTPException(status_code=404, detail="Message has no media")

    conversation = get_conversation(db, db_message.conversation_id)

    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not user_can_access_conversation(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this media",
        )

    media_info_url = (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/" f"{db_message.media_id}"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
    }

    media_info_response = requests.get(
        media_info_url,
        headers=headers,
        timeout=15,
    )

    if media_info_response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Could not get WhatsApp media info: {media_info_response.text}",
        )

    media_info = media_info_response.json()
    media_url = media_info.get("url")

    if not media_url:
        raise HTTPException(
            status_code=502,
            detail="WhatsApp media URL was missing",
        )

    media_response = requests.get(
        media_url,
        headers=headers,
        timeout=30,
    )

    if media_response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Could not download WhatsApp media: {media_response.text}",
        )

    media_type = (
        media_response.headers.get("Content-Type")
        or db_message.media_mime_type
        or "application/octet-stream"
    )

    safe_filename = (
        db_message.media_filename or f"whatsapp-media-{db_message.id}"
    ).replace('"', "")

    return Response(
        content=media_response.content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_filename}"',
            "Cache-Control": "private, max-age=300",
        },
    )


@app.post(
    "/conversations/{conversation_id}/messages/",
    response_model=schemas.MessageOut,
    status_code=status.HTTP_201_CREATED,
)
def create_message(
    conversation_id: int,
    message: schemas.MessageCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not user_can_access_conversation(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation",
        )

    if (
        conversation.assigned_to_user_id is not None
        and conversation.assigned_to_user_id != current_user.id
        and not can_override_conversation_assignment(current_user)
    ):
        raise HTTPException(
            status_code=403,
            detail="This conversation is taken by another user",
        )

    ensure_customer_service_window_is_open(db, conversation_id)

    whatsapp_result = send_whatsapp_text_message(
        to_phone=conversation.contact_phone,
        text=message.content,
    )

    whatsapp_message_id = extract_whatsapp_message_id(whatsapp_result)
    now = datetime.utcnow()

    db_message = models.Message(
        content=message.content,
        direction="outbound",
        is_read=True,
        whatsapp_message_id=whatsapp_message_id,
        whatsapp_status="sent" if whatsapp_message_id else None,
        whatsapp_status_updated_at=now if whatsapp_message_id else None,
        user_id=current_user.id,
        conversation_id=conversation_id,
    )

    db.add(db_message)

    conversation.status = "closed"
    conversation.assigned_to_user_id = None
    conversation.unread_count = 0
    touch_conversation(conversation)

    db.commit()
    db.refresh(db_message)

    print(
        f"[SEND] conversation_id={conversation_id} "
        f"user_id={current_user.id} "
        f"wamid={whatsapp_message_id} "
        f"whatsapp_result={whatsapp_result}",
        flush=True,
    )

    return attach_message_author_data(db, [db_message])[0]


class MessageReactionCreate(BaseModel):
    emoji: str | None = None


@app.post("/messages/{message_id}/reaction/", response_model=schemas.MessageOut)
def create_message_reaction(
    message_id: int,
    reaction: MessageReactionCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    db_message = (
        db.query(models.Message).filter(models.Message.id == message_id).first()
    )

    if not db_message:
        raise HTTPException(status_code=404, detail="Message not found")

    conversation = get_conversation(db, db_message.conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if db_message.direction != "inbound":
        raise HTTPException(
            status_code=400,
            detail="You can only react to customer messages",
        )

    if not db_message.whatsapp_message_id:
        raise HTTPException(
            status_code=400,
            detail="This message does not have a WhatsApp message ID",
        )

    if not user_can_access_conversation(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation",
        )

    if (
        conversation.assigned_to_user_id is not None
        and conversation.assigned_to_user_id != current_user.id
        and not can_override_conversation_assignment(current_user)
    ):
        raise HTTPException(
            status_code=403,
            detail="This conversation is taken by another user",
        )

    ensure_customer_service_window_is_open(db, conversation.id)

    reaction_emoji = None if reaction.emoji is None else str(reaction.emoji).strip()

    if reaction_emoji == "":
        reaction_emoji = None

    whatsapp_result = send_whatsapp_reaction_message(
        to_phone=conversation.contact_phone,
        whatsapp_message_id=db_message.whatsapp_message_id,
        emoji=reaction_emoji,
    )

    now = datetime.utcnow()

    db_message.reaction_emoji = reaction_emoji
    db_message.reaction_updated_at = now

    latest_message = (
        db.query(models.Message)
        .filter(models.Message.conversation_id == conversation.id)
        .order_by(models.Message.created_at.desc(), models.Message.id.desc())
        .first()
    )

    if latest_message and latest_message.id == db_message.id and reaction_emoji:
        conversation.status = "closed"
        conversation.assigned_to_user_id = None
        conversation.unread_count = 0
        touch_conversation(conversation)

    db.commit()
    db.refresh(db_message)

    print(
        f"[REACTION SEND] conversation_id={conversation.id} "
        f"message_id={db_message.id} "
        f"user_id={current_user.id} "
        f"emoji={reaction_emoji or '(remove reaction)'} "
        f"whatsapp_result={whatsapp_result}",
        flush=True,
    )

    return attach_message_author_data(db, [db_message])[0]


@app.post("/conversations/{conversation_id}/take/")
def take_conversation(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not user_can_access_conversation(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation",
        )

    if (
        conversation.assigned_to_user_id is not None
        and conversation.assigned_to_user_id != current_user.id
        and not can_override_conversation_assignment(current_user)
    ):
        raise HTTPException(
            status_code=403,
            detail="This conversation is already taken by another user",
        )

    conversation.assigned_to_user_id = current_user.id
    conversation.status = "open"
    conversation.unread_count = 0
    touch_conversation(conversation)

    db.commit()

    print(f"[TAKE] conversation_id={conversation_id} assigned_to={current_user.id}")

    return {
        "status": "ok",
        "conversation_id": conversation_id,
        "assigned_to_user_id": current_user.id,
        "conversation_status": conversation.status,
        "unread_count": conversation.unread_count,
    }


@app.post("/conversations/{conversation_id}/close/")
def close_conversation(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not user_can_access_conversation(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation",
        )

    if (
        conversation.assigned_to_user_id is not None
        and conversation.assigned_to_user_id != current_user.id
        and not can_override_conversation_assignment(current_user)
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the assigned user, a power user, or an admin can close this conversation",
        )

    conversation.status = "closed"
    conversation.assigned_to_user_id = None
    conversation.unread_count = 0
    touch_conversation(conversation)

    db.commit()

    print(
        f"[CLOSE] conversation_id={conversation_id} closed_by={current_user.id}",
        flush=True,
    )

    return {
        "status": "ok",
        "conversation_id": conversation_id,
        "conversation_status": conversation.status,
        "unread_count": conversation.unread_count,
    }


@app.patch("/conversations/{conversation_id}/follow-up")
def update_conversation_follow_up(
    conversation_id: int,
    follow_up_update: FollowUpUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not user_can_access_conversation(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation",
        )

    if conversation.status != "closed":
        raise HTTPException(
            status_code=400,
            detail="Only done conversations can be marked for follow up",
        )

    conversation.follow_up = follow_up_update.follow_up
    touch_conversation(conversation)

    db.commit()

    print(
        f"[FOLLOW_UP] conversation_id={conversation_id} "
        f"follow_up={conversation.follow_up} "
        f"updated_by={current_user.id}",
        flush=True,
    )

    return {
        "status": "ok",
        "conversation_id": conversation_id,
        "follow_up": conversation.follow_up,
        "conversation_status": conversation.status,
    }


@app.delete("/conversations/{conversation_id}/")
def delete_conversation(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only admins can delete conversations",
        )

    message_ids = [
        message_id
        for (message_id,) in (
            db.query(models.Message.id)
            .filter(models.Message.conversation_id == conversation_id)
            .all()
        )
    ]

    if message_ids:
        db.query(models.TemplateBatchItem).filter(
            models.TemplateBatchItem.message_id.in_(message_ids)
        ).update(
            {models.TemplateBatchItem.message_id: None},
            synchronize_session=False,
        )

    db.query(models.TemplateBatchItem).filter(
        models.TemplateBatchItem.conversation_id == conversation_id
    ).update(
        {models.TemplateBatchItem.conversation_id: None},
        synchronize_session=False,
    )

    deleted_messages_count = (
        db.query(models.Message)
        .filter(models.Message.conversation_id == conversation_id)
        .delete(synchronize_session=False)
    )

    db.delete(conversation)
    db.commit()

    print(
        f"[DELETE] conversation_id={conversation_id} "
        f"deleted_by={current_user.id} "
        f"deleted_messages={deleted_messages_count}",
        flush=True,
    )

    return {
        "status": "ok",
        "conversation_id": conversation_id,
        "deleted_messages": deleted_messages_count,
    }


@app.post("/conversations/{conversation_id}/archive/")
def archive_conversation(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not user_can_access_conversation(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation",
        )

    if (
        conversation.assigned_to_user_id is not None
        and conversation.assigned_to_user_id != current_user.id
        and not can_override_conversation_assignment(current_user)
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the assigned user, a power user, or an admin can archive this conversation",
        )

    conversation.status = "archived"
    conversation.unread_count = 0
    touch_conversation(conversation)

    db.commit()

    print(
        f"[ARCHIVE] conversation_id={conversation_id} archived_by={current_user.id}",
        flush=True,
    )

    return {
        "status": "ok",
        "conversation_id": conversation_id,
        "conversation_status": conversation.status,
        "unread_count": conversation.unread_count,
    }


@app.post("/conversations/{conversation_id}/unarchive/")
def unarchive_conversation(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not user_can_access_conversation(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation",
        )

    if (
        conversation.assigned_to_user_id is not None
        and conversation.assigned_to_user_id != current_user.id
        and not can_override_conversation_assignment(current_user)
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the assigned user, a power user, or an admin can unarchive this conversation",
        )

    conversation.status = "closed"
    touch_conversation(conversation)

    db.commit()

    print(
        f"[UNARCHIVE] conversation_id={conversation_id} unarchived_by={current_user.id}",
        flush=True,
    )

    return {
        "status": "ok",
        "conversation_id": conversation_id,
        "conversation_status": conversation.status,
        "unread_count": conversation.unread_count,
    }


@app.post("/conversations/{conversation_id}/release/")
def release_conversation(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not user_can_access_conversation(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation",
        )

    if (
        conversation.assigned_to_user_id != current_user.id
        and not can_override_conversation_assignment(current_user)
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the assigned user, a power user, or an admin can release this conversation",
        )

    conversation.assigned_to_user_id = None
    touch_conversation(conversation)

    db.commit()

    print(f"[RELEASE] conversation_id={conversation_id} released_by={current_user.id}")

    return {
        "status": "ok",
        "conversation_id": conversation_id,
        "assigned_to_user_id": None,
        "conversation_status": conversation.status,
        "unread_count": conversation.unread_count,
    }


@app.post(
    "/conversations/{conversation_id}/simulate-inbound/",
    response_model=schemas.MessageOut,
    status_code=status.HTTP_201_CREATED,
)
def simulate_inbound_message(
    conversation_id: int,
    message: schemas.MessageCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db_message = models.Message(
        content=message.content,
        direction="inbound",
        is_read=False,
        user_id=current_user.id,
        conversation_id=conversation_id,
    )

    db.add(db_message)

    conversation.status = "open"
    conversation.follow_up = False
    conversation.unread_count = (conversation.unread_count or 0) + 1
    touch_conversation(conversation)

    db.commit()
    db.refresh(db_message)

    print(
        f"[SIMULATE_INBOUND] conversation_id={conversation_id} "
        f"user_id={current_user.id} unread_count={conversation.unread_count} "
        f"content={message.content!r}",
        flush=True,
    )

    return attach_message_author_data(db, [db_message])[0]


@app.post("/conversations/{conversation_id}/mark-as-read/")
def mark_conversation_as_read(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not user_can_access_conversation(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation",
        )

    if not user_can_mark_conversation_as_read(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="Only the assigned user, a power user, or an admin can mark this conversation as read",
        )

    unread_messages = (
        db.query(models.Message)
        .filter(
            models.Message.conversation_id == conversation_id,
            models.Message.direction == "inbound",
            models.Message.is_read.is_(False),
        )
        .all()
    )

    updated_count = 0

    for msg in unread_messages:
        msg.is_read = True
        updated_count += 1

    conversation.unread_count = 0
    conversation.updated_at = datetime.utcnow()

    db.commit()

    print(
        f"[MARK_AS_READ] conversation_id={conversation_id} "
        f"user_id={current_user.id} updated_count={updated_count}",
        flush=True,
    )

    return {
        "status": "ok",
        "conversation_id": conversation_id,
        "updated_count": updated_count,
        "unread_count": conversation.unread_count,
    }


@app.get("/")
def read_root():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/test")
def read_test_page():
    return FileResponse("app/static/test.html")
