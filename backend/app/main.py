import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets

import pyotp
import qrcode
import qrcode.image.svg
import requests
from cryptography.fernet import Fernet, InvalidToken
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
from sqlalchemy import and_, case, func, inspect, or_, text
from sqlalchemy.exc import IntegrityError
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
APP_VERSION = "sendro-performance-phase1-2026-08-01"

CORS_ALLOWED_ORIGINS = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,https://sendro-frontend.onrender.com",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip() for origin in CORS_ALLOWED_ORIGINS.split(",") if origin.strip()
    ],
    allow_credentials=True,
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

    if "inbound_reaction_at" not in columns:
        columns_to_add.append(("inbound_reaction_at", "datetime"))

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


def ensure_user_profile_columns():
    inspector = inspect(engine)

    try:
        columns = {column["name"] for column in inspector.get_columns("users")}
    except Exception as exc:
        print("⚠️ Could not inspect users table:", exc, flush=True)
        return

    columns_to_add = []

    if "display_name" not in columns:
        columns_to_add.append(("display_name", "VARCHAR"))

    if "assignment_color" not in columns:
        columns_to_add.append(("assignment_color", "VARCHAR(7)"))

    if "assignment_text_color" not in columns:
        columns_to_add.append(("assignment_text_color", "VARCHAR(7)"))

    if not columns_to_add:
        return

    with engine.begin() as connection:
        for column_name, column_type in columns_to_add:
            connection.execute(
                text(
                    f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
                )
            )
            print(f"✅ Added {column_name} column to users table", flush=True)


def ensure_user_security_columns():
    inspector = inspect(engine)

    try:
        columns = {column["name"] for column in inspector.get_columns("users")}
    except Exception as exc:
        print("⚠️ Could not inspect users table:", exc, flush=True)
        return

    columns_to_add = []

    if "auth_version" not in columns:
        columns_to_add.append(
            ("auth_version", "INTEGER NOT NULL DEFAULT 1")
        )

    if "must_change_password" not in columns:
        boolean_default = "false" if engine.dialect.name == "postgresql" else "0"
        columns_to_add.append(
            (
                "must_change_password",
                f"BOOLEAN NOT NULL DEFAULT {boolean_default}",
            )
        )

    if not columns_to_add:
        return

    with engine.begin() as connection:
        for column_name, column_type in columns_to_add:
            connection.execute(
                text(
                    f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
                )
            )
            print(f"✅ Added {column_name} column to users table", flush=True)


def ensure_user_mfa_columns():
    inspector = inspect(engine)

    try:
        columns = {column["name"] for column in inspector.get_columns("users")}
    except Exception as exc:
        print("⚠️ Could not inspect users table:", exc, flush=True)
        return

    boolean_default = "false" if engine.dialect.name == "postgresql" else "0"
    columns_to_add = []

    if "mfa_required" not in columns:
        columns_to_add.append(
            ("mfa_required", f"BOOLEAN NOT NULL DEFAULT {boolean_default}")
        )

    if "mfa_enabled" not in columns:
        columns_to_add.append(
            ("mfa_enabled", f"BOOLEAN NOT NULL DEFAULT {boolean_default}")
        )

    if "mfa_secret_encrypted" not in columns:
        columns_to_add.append(("mfa_secret_encrypted", "TEXT"))

    if "mfa_pending_secret_encrypted" not in columns:
        columns_to_add.append(("mfa_pending_secret_encrypted", "TEXT"))

    if "mfa_recovery_codes_hashed" not in columns:
        columns_to_add.append(("mfa_recovery_codes_hashed", "TEXT"))

    if not columns_to_add:
        return

    with engine.begin() as connection:
        for column_name, column_type in columns_to_add:
            connection.execute(
                text(
                    f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
                )
            )
            print(f"✅ Added {column_name} column to users table", flush=True)


ensure_follow_up_column()
ensure_message_status_columns()
ensure_user_report_permission_column()
ensure_user_profile_columns()
ensure_user_security_columns()
ensure_user_mfa_columns()

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

    customer_activity_rows = (
        db.query(
            models.Message.conversation_id,
            func.max(
                case(
                    (
                        models.Message.direction == "inbound",
                        models.Message.created_at,
                    ),
                    else_=None,
                )
            ).label("last_inbound_at"),
            func.max(models.Message.inbound_reaction_at).label(
                "last_inbound_reaction_at"
            ),
        )
        .filter(models.Message.conversation_id.in_(conversation_ids))
        .group_by(models.Message.conversation_id)
        .all()
    )

    last_inbound_by_conversation_id = {
        row.conversation_id: row.last_inbound_at for row in customer_activity_rows
    }

    last_inbound_reaction_by_conversation_id = {
        row.conversation_id: row.last_inbound_reaction_at
        for row in customer_activity_rows
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

    for conversation in conversations:
        customer_activity_times = (
            last_inbound_by_conversation_id.get(conversation.id),
            last_inbound_reaction_by_conversation_id.get(conversation.id),
        )

        last_customer_activity_at = max(
            (
                activity_time
                for activity_time in customer_activity_times
                if activity_time is not None
            ),
            default=None,
        )

        fields = build_customer_service_window_fields(last_customer_activity_at)
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
    last_inbound_message_at = (
        db.query(func.max(models.Message.created_at))
        .filter(
            models.Message.conversation_id == conversation_id,
            models.Message.direction == "inbound",
        )
        .scalar()
    )

    last_inbound_reaction_at = (
        db.query(func.max(models.Message.inbound_reaction_at))
        .filter(
            models.Message.conversation_id == conversation_id,
            models.Message.inbound_reaction_at.isnot(None),
        )
        .scalar()
    )

    return max(
        (
            activity_time
            for activity_time in (
                last_inbound_message_at,
                last_inbound_reaction_at,
            )
            if activity_time is not None
        ),
        default=None,
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


def parse_whatsapp_timestamp(timestamp_value) -> datetime:
    if timestamp_value is not None:
        try:
            return datetime.utcfromtimestamp(int(timestamp_value))
        except (TypeError, ValueError, OSError, OverflowError):
            pass

    return datetime.utcnow()


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


class LoginResponse(BaseModel):
    access_token: str | None = None
    token_type: str | None = None
    mfa_required: bool = False
    challenge_token: str | None = None
    trusted_device_available: bool = False


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

PASSWORD_MIN_LENGTH = 10
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_FAILURE_WINDOW_MINUTES = int(
    os.getenv("LOGIN_FAILURE_WINDOW_MINUTES", "15")
)
LOGIN_LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))
COMMON_PASSWORDS = {
    "1234567890",
    "123456789a",
    "administrator",
    "changeme123",
    "letmein123",
    "password123",
    "qwerty1234",
    "sendro1234",
    "sunsetoia",
    "welcome123",
}
DUMMY_PASSWORD_HASH = pwd_context.hash("sendro-dummy-password-check")

MFA_ISSUER = os.getenv("MFA_ISSUER", "Sendro")
MFA_TOTP_DIGITS = 6
MFA_TOTP_PERIOD_SECONDS = 30
MFA_TOTP_WINDOW = 1
MFA_RECOVERY_CODE_COUNT = 10
MFA_RECOVERY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MFA_CHALLENGE_MINUTES = int(os.getenv("MFA_CHALLENGE_MINUTES", "5"))
MFA_CHALLENGE_MAX_ATTEMPTS = int(os.getenv("MFA_CHALLENGE_MAX_ATTEMPTS", "5"))
TRUSTED_DEVICE_DAYS = int(os.getenv("TRUSTED_DEVICE_DAYS", "15"))
TRUSTED_DEVICE_MAX_PER_USER = int(
    os.getenv("TRUSTED_DEVICE_MAX_PER_USER", "10")
)
TRUSTED_DEVICE_COOKIE_NAME = os.getenv(
    "TRUSTED_DEVICE_COOKIE_NAME",
    "sendro_trusted_device",
)
TRUSTED_DEVICE_COOKIE_SECURE = (
    os.getenv("TRUSTED_DEVICE_COOKIE_SECURE", "true").strip().lower()
    not in {"0", "false", "no", "off"}
)
TRUSTED_DEVICE_COOKIE_SAMESITE = os.getenv(
    "TRUSTED_DEVICE_COOKIE_SAMESITE",
    "none",
).strip().lower()

if TRUSTED_DEVICE_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    TRUSTED_DEVICE_COOKIE_SAMESITE = "none"


def get_mfa_fernet() -> Fernet:
    derived_key = hashlib.sha256(
        f"sendro-mfa-encryption:{SECRET_KEY}".encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(derived_key))


MFA_FERNET = get_mfa_fernet()


def encrypt_mfa_value(value: str) -> str:
    return MFA_FERNET.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_mfa_value(value: str | None) -> str:
    if not value:
        raise HTTPException(
            status_code=400,
            detail="Authenticator setup is not available",
        )

    try:
        return MFA_FERNET.decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError):
        raise HTTPException(
            status_code=500,
            detail="Authenticator data could not be decrypted. Ask an administrator to reset it.",
        )


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def normalize_mfa_code(code: str) -> str:
    return re.sub(r"[\s-]+", "", str(code or "")).upper()


def verify_totp_code(secret: str, code: str) -> bool:
    normalized_code = normalize_mfa_code(code)

    if not re.fullmatch(r"\d{6}", normalized_code):
        return False

    return bool(
        pyotp.TOTP(
            secret,
            digits=MFA_TOTP_DIGITS,
            interval=MFA_TOTP_PERIOD_SECONDS,
        ).verify(normalized_code, valid_window=MFA_TOTP_WINDOW)
    )


def build_otpauth_uri(user: models.User, secret: str) -> str:
    account_label = user.email or user.username
    return pyotp.TOTP(
        secret,
        digits=MFA_TOTP_DIGITS,
        interval=MFA_TOTP_PERIOD_SECONDS,
    ).provisioning_uri(
        name=account_label,
        issuer_name=MFA_ISSUER,
    )


def build_mfa_qr_code_data_url(otpauth_uri: str) -> str:
    image = qrcode.make(
        otpauth_uri,
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=8,
        border=2,
    )
    buffer = io.BytesIO()
    image.save(buffer)
    encoded_svg = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded_svg}"


def hash_recovery_code(code: str) -> str:
    normalized_code = normalize_mfa_code(code)
    return hmac.new(
        SECRET_KEY.encode("utf-8"),
        f"sendro-recovery:{normalized_code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_recovery_codes() -> tuple[list[str], list[str]]:
    plain_codes = []

    for _ in range(MFA_RECOVERY_CODE_COUNT):
        raw_code = "".join(
            secrets.choice(MFA_RECOVERY_CODE_ALPHABET) for _ in range(12)
        )
        plain_codes.append(
            f"{raw_code[:4]}-{raw_code[4:8]}-{raw_code[8:]}"
        )

    hashed_codes = [hash_recovery_code(code) for code in plain_codes]
    return plain_codes, hashed_codes


def hash_mfa_challenge_token(challenge_token: str) -> str:
    return hashlib.sha256(challenge_token.encode("utf-8")).hexdigest()


def hash_trusted_device_token(device_token: str) -> str:
    return hmac.new(
        SECRET_KEY.encode("utf-8"),
        f"sendro-trusted-device:{device_token}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def clear_trusted_device_cookie(response: Response) -> None:
    response.delete_cookie(
        key=TRUSTED_DEVICE_COOKIE_NAME,
        path="/",
        secure=TRUSTED_DEVICE_COOKIE_SECURE,
        httponly=True,
        samesite=TRUSTED_DEVICE_COOKIE_SAMESITE,
    )


def set_trusted_device_cookie(
    response: Response,
    device_token: str,
    max_age_seconds: int,
) -> None:
    response.set_cookie(
        key=TRUSTED_DEVICE_COOKIE_NAME,
        value=device_token,
        max_age=max(1, max_age_seconds),
        path="/",
        secure=TRUSTED_DEVICE_COOKIE_SECURE,
        httponly=True,
        samesite=TRUSTED_DEVICE_COOKIE_SAMESITE,
    )


def cleanup_trusted_devices(db: Session, now: datetime) -> None:
    deleted_count = db.query(models.TrustedDevice).filter(
        models.TrustedDevice.expires_at <= now
    ).delete(synchronize_session=False)

    if deleted_count:
        db.commit()


def create_trusted_device(
    db: Session,
    user: models.User,
    response: Response,
    now: datetime,
) -> None:
    cleanup_trusted_devices(db, now)

    existing_devices = (
        db.query(models.TrustedDevice)
        .filter(models.TrustedDevice.user_id == user.id)
        .order_by(models.TrustedDevice.created_at.desc())
        .all()
    )

    keep_existing_count = max(0, TRUSTED_DEVICE_MAX_PER_USER - 1)
    for stale_device in existing_devices[keep_existing_count:]:
        db.delete(stale_device)

    device_token = secrets.token_urlsafe(48)
    expires_at = now + timedelta(days=TRUSTED_DEVICE_DAYS)
    db.add(
        models.TrustedDevice(
            token_hash=hash_trusted_device_token(device_token),
            user_id=user.id,
            auth_version=user.auth_version or 1,
            created_at=now,
            last_used_at=now,
            expires_at=expires_at,
        )
    )
    db.commit()

    set_trusted_device_cookie(
        response,
        device_token,
        int((expires_at - now).total_seconds()),
    )


def trusted_device_is_valid(
    db: Session,
    user: models.User,
    request: Request,
    response: Response,
    now: datetime,
) -> bool:
    if user.role == "admin":
        return False

    device_token = request.cookies.get(TRUSTED_DEVICE_COOKIE_NAME)
    if not device_token:
        return False

    token_hash = hash_trusted_device_token(device_token)
    trusted_device = (
        db.query(models.TrustedDevice)
        .filter(models.TrustedDevice.token_hash == token_hash)
        .first()
    )

    if trusted_device is None:
        clear_trusted_device_cookie(response)
        return False

    if trusted_device.user_id != user.id:
        return False

    current_auth_version = user.auth_version or 1
    if (
        trusted_device.expires_at <= now
        or trusted_device.auth_version != current_auth_version
        or user.disabled
        or not user.mfa_enabled
    ):
        db.delete(trusted_device)
        db.commit()
        clear_trusted_device_cookie(response)
        return False

    remaining_seconds = int((trusted_device.expires_at - now).total_seconds())
    rotated_token = secrets.token_urlsafe(48)
    trusted_device.token_hash = hash_trusted_device_token(rotated_token)
    trusted_device.last_used_at = now
    db.commit()
    set_trusted_device_cookie(response, rotated_token, remaining_seconds)
    return True


def cleanup_mfa_login_challenges(db: Session, now: datetime) -> None:
    stale_cutoff = now - timedelta(days=1)
    db.query(models.MfaLoginChallenge).filter(
        or_(
            models.MfaLoginChallenge.expires_at < now,
            and_(
                models.MfaLoginChallenge.consumed_at.isnot(None),
                models.MfaLoginChallenge.consumed_at < stale_cutoff,
            ),
        )
    ).delete(synchronize_session=False)
    db.commit()


def create_mfa_login_challenge(
    db: Session,
    user: models.User,
    now: datetime,
) -> str:
    cleanup_mfa_login_challenges(db, now)
    db.query(models.MfaLoginChallenge).filter(
        models.MfaLoginChallenge.user_id == user.id,
        models.MfaLoginChallenge.consumed_at.is_(None),
    ).delete(synchronize_session=False)

    challenge_token = secrets.token_urlsafe(32)
    db.add(
        models.MfaLoginChallenge(
            challenge_hash=hash_mfa_challenge_token(challenge_token),
            user_id=user.id,
            failed_attempts=0,
            created_at=now,
            expires_at=now + timedelta(minutes=MFA_CHALLENGE_MINUTES),
        )
    )
    db.commit()
    return challenge_token


def load_recovery_code_hashes(user: models.User) -> list[str]:
    if not user.mfa_recovery_codes_hashed:
        return []

    try:
        values = json.loads(user.mfa_recovery_codes_hashed)
    except (TypeError, ValueError):
        return []

    return [str(value) for value in values if value]


def verify_and_consume_mfa_code(user: models.User, code: str) -> bool:
    secret = decrypt_mfa_value(user.mfa_secret_encrypted)

    if verify_totp_code(secret, code):
        return True

    submitted_hash = hash_recovery_code(code)
    recovery_hashes = load_recovery_code_hashes(user)

    for index, stored_hash in enumerate(recovery_hashes):
        if hmac.compare_digest(submitted_hash, stored_hash):
            del recovery_hashes[index]
            user.mfa_recovery_codes_hashed = json.dumps(recovery_hashes)
            return True

    return False


def issue_access_token_for_user(user: models.User) -> Token:
    access_token = create_access_token(
        data={
            "sub": user.username,
            "ver": user.auth_version or 1,
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=access_token, token_type="bearer")


ALLOWED_USER_ROLES = {"admin", "power_user", "user"}
ASSIGNMENT_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
QUICK_REPLY_SHORTCUT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
QUICK_REPLY_SCOPES = {"team", "personal"}


def normalize_assignment_color(value: str | None) -> str | None:
    if value is None:
        return None

    normalized_value = value.strip().lower()

    if not normalized_value:
        return None

    if not ASSIGNMENT_COLOR_PATTERN.fullmatch(normalized_value):
        raise HTTPException(
            status_code=400,
            detail="Assignment color must be a valid hex color such as #1d4ed8",
        )

    return normalized_value


def normalize_assignment_text_color(value: str | None) -> str | None:
    if value is None:
        return None

    normalized_value = value.strip().lower()

    if not normalized_value:
        return None

    if not ASSIGNMENT_COLOR_PATTERN.fullmatch(normalized_value):
        raise HTTPException(
            status_code=400,
            detail="Assignment text color must be a valid hex color such as #ffffff",
        )

    return normalized_value


def is_admin(user: models.User) -> bool:
    return user.role == "admin"


def is_power_user(user: models.User) -> bool:
    return user.role == "power_user"


def can_create_quick_replies(user: models.User) -> bool:
    return bool(user and not user.disabled)


def can_create_quick_reply_scope(user: models.User, scope: str) -> bool:
    return scope == "personal" or (scope == "team" and is_admin(user))


def can_view_quick_reply(user: models.User, quick_reply: models.QuickReply) -> bool:
    return quick_reply.scope == "team" or (
        quick_reply.scope == "personal"
        and quick_reply.created_by_user_id == user.id
    )


def can_edit_quick_reply(user: models.User, quick_reply: models.QuickReply) -> bool:
    return (
        quick_reply.scope == "team" and is_admin(user)
    ) or (
        quick_reply.scope == "personal"
        and quick_reply.created_by_user_id == user.id
    )


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


def validate_new_password(
    password: str,
    username: str,
    email: str,
):
    if len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Password must be at least {PASSWORD_MIN_LENGTH} characters long"
            ),
        )

    normalized_password = password.casefold()
    email_name = email.split("@", 1)[0].casefold()
    blocked_values = {
        username.casefold(),
        email.casefold(),
        email_name,
        *COMMON_PASSWORDS,
    }

    if (
        not password.strip()
        or len(set(normalized_password)) < 4
        or normalized_password in blocked_values
    ):
        raise HTTPException(
            status_code=400,
            detail="Choose a password that is not your username, email, or a common password",
        )


def get_login_throttle_key(request: Request, username: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    normalized_username = username.strip().casefold()
    raw_key = f"{SECRET_KEY}:{client_host}:{normalized_username}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def get_retry_after_seconds(locked_until: datetime, now: datetime) -> int:
    return max(1, int((locked_until - now).total_seconds()) + 1)


def raise_login_throttled(retry_after_seconds: int):
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many login attempts. Please wait before trying again.",
        headers={"Retry-After": str(retry_after_seconds)},
    )


def check_login_throttle(
    db: Session,
    throttle_key: str,
    now: datetime,
):
    throttle = (
        db.query(models.LoginThrottle)
        .filter(models.LoginThrottle.throttle_key == throttle_key)
        .with_for_update()
        .first()
    )

    if throttle and throttle.locked_until and throttle.locked_until > now:
        raise_login_throttled(
            get_retry_after_seconds(throttle.locked_until, now)
        )

    return throttle


def record_login_failure(
    db: Session,
    throttle_key: str,
    throttle: models.LoginThrottle | None,
    now: datetime,
) -> int | None:
    window_start_cutoff = now - timedelta(
        minutes=LOGIN_FAILURE_WINDOW_MINUTES
    )

    if throttle is None:
        throttle = models.LoginThrottle(
            throttle_key=throttle_key,
            failed_attempts=0,
            window_started_at=now,
            last_failed_at=now,
        )
        db.add(throttle)
    elif throttle.window_started_at < window_start_cutoff:
        throttle.failed_attempts = 0
        throttle.window_started_at = now
        throttle.locked_until = None

    throttle.failed_attempts += 1
    throttle.last_failed_at = now

    retry_after_seconds = None

    if throttle.failed_attempts >= LOGIN_MAX_FAILURES:
        throttle.locked_until = now + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
        retry_after_seconds = get_retry_after_seconds(throttle.locked_until, now)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_throttle = (
            db.query(models.LoginThrottle)
            .filter(models.LoginThrottle.throttle_key == throttle_key)
            .with_for_update()
            .first()
        )

        if existing_throttle is None:
            raise

        return record_login_failure(
            db,
            throttle_key,
            existing_throttle,
            now,
        )

    return retry_after_seconds


def clear_login_failures(db: Session, throttle_key: str):
    db.query(models.LoginThrottle).filter(
        models.LoginThrottle.throttle_key == throttle_key
    ).delete(synchronize_session=False)
    db.commit()


def cleanup_stale_login_throttles(db: Session, now: datetime):
    stale_cutoff = now - timedelta(days=1)
    deleted_count = db.query(models.LoginThrottle).filter(
        models.LoginThrottle.last_failed_at < stale_cutoff
    ).delete(synchronize_session=False)

    if deleted_count:
        db.commit()


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
            author.display_name.strip()
            if author.display_name and author.display_name.strip()
            else (
                author.full_name.strip()
                if author.full_name and author.full_name.strip()
                else author.username
            )
        )

        message.author_name = display_name
        message.author_username = author.username
        message.author_role = author.role

    return messages


def touch_conversation(conversation: models.Conversation):
    now = datetime.utcnow()
    conversation.updated_at = now
    conversation.last_message_at = now


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
        token_auth_version = payload.get("ver")

        if username is None:
            raise credentials_exception

        token_data = TokenData(username=username)

    except JWTError:
        raise credentials_exception

    user = get_user(db, username=token_data.username)

    if user is None:
        raise credentials_exception

    current_auth_version = getattr(user, "auth_version", 1) or 1

    if token_auth_version is None:
        if current_auth_version != 1:
            raise credentials_exception
    elif token_auth_version != current_auth_version:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: Annotated[models.User, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")

    if getattr(current_user, "must_change_password", False):
        raise HTTPException(
            status_code=403,
            detail="Password change required",
        )

    if getattr(current_user, "mfa_setup_required", False):
        raise HTTPException(
            status_code=403,
            detail="Authenticator setup required",
        )

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

        # Duplicate detection has completed, so the current transaction no
        # longer needs to occupy a connection while Meta processes the send.
        db.close()

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
                reaction_received_at = parse_whatsapp_timestamp(
                    message.get("timestamp")
                )

                original_message.reaction_emoji = emoji or None
                original_message.reaction_updated_at = reaction_received_at

                if emoji:
                    original_message.inbound_reaction_at = reaction_received_at

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

        elif message_type == "location":
            location = message.get("location", {})

            latitude = location.get("latitude")
            longitude = location.get("longitude")
            location_name = str(location.get("name") or "").strip()
            location_address = str(location.get("address") or "").strip()

            location_lines = ["📍 Location shared"]

            if location_name:
                location_lines.append(f"Name: {location_name}")

            if location_address:
                location_lines.append(f"Address: {location_address}")

            if latitude is not None and longitude is not None:
                location_lines.append(f"Latitude: {latitude}")
                location_lines.append(f"Longitude: {longitude}")
                location_lines.append(
                    f"Google Maps: https://www.google.com/maps?q={latitude},{longitude}"
                )

            text = "\n".join(location_lines)

        else:
            text = f"[Unsupported WhatsApp message type: {message_type}]"

        if not text:
            text = f"[Unsupported WhatsApp message type: {message_type}]"

        phone = message["from"]
        normalized_phone = normalize_whatsapp_phone(phone)
        contacts = value.get("contacts") or []
        contact = contacts[0] if contacts else {}
        contact_profile = contact.get("profile") or {}
        name = str(contact_profile.get("name") or "").strip()

        if not name:
            name = f"+{normalized_phone}"

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
    display_name = user.display_name.strip() if user.display_name else None
    assignment_color = normalize_assignment_color(user.assignment_color)
    assignment_text_color = normalize_assignment_text_color(
        user.assignment_text_color
    )
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

    if display_name and len(display_name) > 24:
        raise HTTPException(
            status_code=400,
            detail="Display name must be 24 characters or fewer",
        )

    existing_user = get_user(db, username)
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    existing_email = get_user_by_email(db, email)
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    validate_new_password(user.password, username, email)
    hashed_password = get_password_hash(user.password)

    db_user = models.User(
        username=username,
        email=email,
        full_name=full_name,
        display_name=display_name,
        assignment_color=assignment_color,
        assignment_text_color=assignment_text_color,
        hashed_password=hashed_password,
        role=requested_role,
        disabled=False,
        must_change_password=True,
        mfa_required=bool(user.mfa_required),
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
    new_display_name = None
    new_assignment_color = None
    new_assignment_text_color = None
    new_role = None
    new_mfa_required = None

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

        if existing_email:
            raise HTTPException(
                status_code=400,
                detail="Email already registered",
            )

    if user_update.full_name is not None:
        new_full_name = user_update.full_name.strip() or None

    if user_update.display_name is not None:
        new_display_name = user_update.display_name.strip() or None

        if new_display_name and len(new_display_name) > 24:
            raise HTTPException(
                status_code=400,
                detail="Display name must be 24 characters or fewer",
            )

    if user_update.assignment_color is not None:
        new_assignment_color = normalize_assignment_color(
            user_update.assignment_color
        )

    if user_update.assignment_text_color is not None:
        new_assignment_text_color = normalize_assignment_text_color(
            user_update.assignment_text_color
        )

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

    if user_update.mfa_required is not None:
        new_mfa_required = bool(user_update.mfa_required)

    original_role = db_user.role
    original_disabled = db_user.disabled
    original_mfa_required = db_user.mfa_required

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

    if user_update.display_name is not None:
        db_user.display_name = new_display_name

    if user_update.assignment_color is not None:
        db_user.assignment_color = new_assignment_color

    if user_update.assignment_text_color is not None:
        db_user.assignment_text_color = new_assignment_text_color

    if new_role is not None:
        db_user.role = new_role

    if user_update.disabled is not None:
        db_user.disabled = user_update.disabled

    if user_update.can_view_reports is not None:
        db_user.can_view_reports = user_update.can_view_reports

    if new_mfa_required is not None:
        db_user.mfa_required = new_mfa_required

    security_policy_changed = (
        db_user.role != original_role
        or db_user.disabled != original_disabled
        or db_user.mfa_required != original_mfa_required
    )

    if security_policy_changed:
        db_user.auth_version = (db_user.auth_version or 1) + 1
        db.query(models.MfaLoginChallenge).filter(
            models.MfaLoginChallenge.user_id == db_user.id
        ).delete(synchronize_session=False)

    db.commit()
    db.refresh(db_user)

    return db_user


@app.patch("/users/me/password", response_model=schemas.UserOut)
def change_current_user_password(
    password_change: schemas.UserPasswordChange,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")

    if not verify_password(
        password_change.current_password,
        current_user.hashed_password,
    ):
        raise HTTPException(
            status_code=400,
            detail="Current password is incorrect",
        )

    validate_new_password(
        password_change.new_password,
        current_user.username,
        current_user.email,
    )

    if verify_password(
        password_change.new_password,
        current_user.hashed_password,
    ):
        raise HTTPException(
            status_code=400,
            detail="New password must be different from the current password",
        )

    current_user.hashed_password = get_password_hash(
        password_change.new_password
    )
    current_user.must_change_password = False
    current_user.auth_version = (current_user.auth_version or 1) + 1

    db.commit()
    db.refresh(current_user)

    return current_user


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

    if db_user.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Use the personal password change flow for your own account",
        )

    new_password = password_reset.password
    validate_new_password(new_password, db_user.username, db_user.email)

    if verify_password(new_password, db_user.hashed_password):
        raise HTTPException(
            status_code=400,
            detail="New password must be different from the current password",
        )

    db_user.hashed_password = get_password_hash(new_password)
    db_user.must_change_password = True
    db_user.auth_version = (db_user.auth_version or 1) + 1

    db.commit()
    db.refresh(db_user)

    return db_user


@app.post(
    "/users/me/mfa/setup",
    response_model=schemas.MfaSetupStartOut,
)
def start_current_user_mfa_setup(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")

    if current_user.must_change_password:
        raise HTTPException(
            status_code=403,
            detail="Change your temporary password before setting up Authenticator",
        )

    if current_user.mfa_enabled:
        raise HTTPException(
            status_code=400,
            detail="Authenticator is already enabled",
        )

    secret = generate_totp_secret()
    current_user.mfa_pending_secret_encrypted = encrypt_mfa_value(secret)

    db.commit()

    otpauth_uri = build_otpauth_uri(current_user, secret)

    return schemas.MfaSetupStartOut(
        secret=secret,
        otpauth_uri=otpauth_uri,
        qr_code_data_url=build_mfa_qr_code_data_url(otpauth_uri),
    )


@app.post(
    "/users/me/mfa/confirm",
    response_model=schemas.MfaSetupConfirmOut,
)
def confirm_current_user_mfa_setup(
    confirmation: schemas.MfaCodeRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")

    if current_user.must_change_password:
        raise HTTPException(
            status_code=403,
            detail="Change your temporary password before setting up Authenticator",
        )

    if current_user.mfa_enabled:
        raise HTTPException(
            status_code=400,
            detail="Authenticator is already enabled",
        )

    pending_secret = decrypt_mfa_value(
        current_user.mfa_pending_secret_encrypted
    )

    if not verify_totp_code(pending_secret, confirmation.code):
        raise HTTPException(
            status_code=400,
            detail="Invalid authenticator code",
        )

    recovery_codes, hashed_recovery_codes = generate_recovery_codes()
    current_user.mfa_secret_encrypted = encrypt_mfa_value(pending_secret)
    current_user.mfa_pending_secret_encrypted = None
    current_user.mfa_recovery_codes_hashed = json.dumps(
        hashed_recovery_codes
    )
    current_user.mfa_enabled = True
    current_user.auth_version = (current_user.auth_version or 1) + 1

    db.query(models.MfaLoginChallenge).filter(
        models.MfaLoginChallenge.user_id == current_user.id
    ).delete(synchronize_session=False)

    db.commit()

    return schemas.MfaSetupConfirmOut(
        enabled=True,
        recovery_codes=recovery_codes,
    )


@app.post(
    "/users/{user_id}/mfa/reset",
    response_model=schemas.MfaResetOut,
)
def reset_user_mfa(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only admins can reset Authenticator",
        )

    db_user = db.query(models.User).filter(models.User.id == user_id).first()

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    db_user.mfa_enabled = False
    db_user.mfa_secret_encrypted = None
    db_user.mfa_pending_secret_encrypted = None
    db_user.mfa_recovery_codes_hashed = None
    db_user.auth_version = (db_user.auth_version or 1) + 1

    db.query(models.MfaLoginChallenge).filter(
        models.MfaLoginChallenge.user_id == db_user.id
    ).delete(synchronize_session=False)

    db.commit()
    db.refresh(db_user)

    return schemas.MfaResetOut(
        user_id=db_user.id,
        mfa_enabled=db_user.mfa_enabled,
        mfa_setup_required=db_user.mfa_setup_required,
    )


@app.post(
    "/users/{user_id}/sessions/revoke",
    response_model=schemas.UserOut,
)
def revoke_user_sessions(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only admins can sign out user sessions",
        )

    db_user = db.query(models.User).filter(models.User.id == user_id).first()

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if db_user.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Use the normal logout button for your own account",
        )

    db_user.auth_version = (db_user.auth_version or 1) + 1
    db.query(models.MfaLoginChallenge).filter(
        models.MfaLoginChallenge.user_id == db_user.id
    ).delete(synchronize_session=False)

    db.commit()
    db.refresh(db_user)
    return db_user


def normalize_quick_reply_category_name(value: str | None) -> str:
    normalized_value = " ".join(str(value or "").strip().split())

    if not normalized_value:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")

    if len(normalized_value) > 60:
        raise HTTPException(
            status_code=400,
            detail="Category name must be 60 characters or fewer",
        )

    return normalized_value


def normalize_quick_reply_title(value: str | None) -> str:
    normalized_value = " ".join(str(value or "").strip().split())

    if not normalized_value:
        raise HTTPException(status_code=400, detail="Quick reply title cannot be empty")

    if len(normalized_value) > 100:
        raise HTTPException(
            status_code=400,
            detail="Quick reply title must be 100 characters or fewer",
        )

    return normalized_value


def normalize_quick_reply_content(value: str | None) -> str:
    normalized_value = str(value or "").strip()

    if not normalized_value:
        raise HTTPException(status_code=400, detail="Quick reply content cannot be empty")

    if len(normalized_value) > 4000:
        raise HTTPException(
            status_code=400,
            detail="Quick reply content must be 4,000 characters or fewer",
        )

    return normalized_value


def normalize_quick_reply_shortcut(value: str | None) -> str | None:
    normalized_value = str(value or "").strip().lower().lstrip("/")

    if not normalized_value:
        return None

    if not QUICK_REPLY_SHORTCUT_PATTERN.fullmatch(normalized_value):
        raise HTTPException(
            status_code=400,
            detail=(
                "Shortcut can contain lowercase letters, numbers, hyphens and "
                "underscores only"
            ),
        )

    return normalized_value


def normalize_quick_reply_scope(value: str | None) -> str:
    normalized_value = str(value or "personal").strip().lower()

    if normalized_value not in QUICK_REPLY_SCOPES:
        raise HTTPException(
            status_code=400,
            detail="Quick reply scope must be team or personal",
        )

    return normalized_value


def visible_quick_reply_filter(current_user: models.User):
    return or_(
        models.QuickReply.scope == "team",
        and_(
            models.QuickReply.scope == "personal",
            models.QuickReply.created_by_user_id == current_user.id,
        ),
    )


def get_favorite_quick_reply_ids(
    db: Session,
    user_id: int,
    quick_reply_ids: set[int] | None = None,
) -> set[int]:
    query = db.query(models.QuickReplyFavorite.quick_reply_id).filter(
        models.QuickReplyFavorite.user_id == user_id
    )

    if quick_reply_ids is not None:
        if not quick_reply_ids:
            return set()
        query = query.filter(
            models.QuickReplyFavorite.quick_reply_id.in_(quick_reply_ids)
        )

    return {quick_reply_id for (quick_reply_id,) in query.all()}


def set_quick_reply_favorite(
    db: Session,
    user_id: int,
    quick_reply_id: int,
    is_favorite: bool,
) -> None:
    existing_favorite = (
        db.query(models.QuickReplyFavorite)
        .filter(
            models.QuickReplyFavorite.user_id == user_id,
            models.QuickReplyFavorite.quick_reply_id == quick_reply_id,
        )
        .first()
    )

    if is_favorite and not existing_favorite:
        db.add(
            models.QuickReplyFavorite(
                user_id=user_id,
                quick_reply_id=quick_reply_id,
                created_at=datetime.utcnow(),
            )
        )
    elif not is_favorite and existing_favorite:
        db.delete(existing_favorite)


def get_quick_reply_category_or_404(
    db: Session,
    category_id: int,
) -> models.QuickReplyCategory:
    category = (
        db.query(models.QuickReplyCategory)
        .filter(models.QuickReplyCategory.id == category_id)
        .first()
    )

    if not category:
        raise HTTPException(status_code=404, detail="Quick reply category not found")

    return category


def validate_quick_reply_parent_category(
    db: Session,
    parent_id: int | None,
    category_id: int | None = None,
) -> models.QuickReplyCategory | None:
    if parent_id is None:
        return None

    if category_id is not None and parent_id == category_id:
        raise HTTPException(status_code=400, detail="A category cannot contain itself")

    parent = get_quick_reply_category_or_404(db, parent_id)

    if parent.parent_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Quick reply categories support one subcategory level",
        )

    if category_id is not None:
        child_exists = (
            db.query(models.QuickReplyCategory)
            .filter(models.QuickReplyCategory.parent_id == category_id)
            .first()
        )

        if child_exists:
            raise HTTPException(
                status_code=400,
                detail="A category with subcategories cannot become a subcategory",
            )

    return parent


def quick_reply_category_to_out(
    category: models.QuickReplyCategory,
    reply_count: int = 0,
) -> dict:
    return {
        "id": category.id,
        "name": category.name,
        "parent_id": category.parent_id,
        "sort_order": category.sort_order,
        "reply_count": int(reply_count or 0),
        "created_at": category.created_at,
        "updated_at": category.updated_at,
    }


def quick_reply_to_out(
    quick_reply: models.QuickReply,
    current_user: models.User,
    categories_by_id: dict[int, models.QuickReplyCategory],
    users_by_id: dict[int, models.User],
    favorite_quick_reply_ids: set[int],
) -> dict:
    category = categories_by_id.get(quick_reply.category_id)
    parent_category = (
        categories_by_id.get(category.parent_id)
        if category and category.parent_id
        else None
    )
    creator = users_by_id.get(quick_reply.created_by_user_id)
    creator_name = None

    if creator:
        creator_name = (
            creator.display_name
            or creator.full_name
            or creator.username
        )

    return {
        "id": quick_reply.id,
        "title": quick_reply.title,
        "content": quick_reply.content,
        "shortcut": quick_reply.shortcut,
        "category_id": quick_reply.category_id,
        "category_name": category.name if category else None,
        "parent_category_id": parent_category.id if parent_category else None,
        "parent_category_name": parent_category.name if parent_category else None,
        "scope": quick_reply.scope,
        "is_favorite": quick_reply.id in favorite_quick_reply_ids,
        "sort_order": quick_reply.sort_order,
        "created_by_user_id": quick_reply.created_by_user_id,
        "created_by_name": creator_name,
        "can_edit": can_edit_quick_reply(current_user, quick_reply),
        "can_delete": can_edit_quick_reply(current_user, quick_reply),
        "created_at": quick_reply.created_at,
        "updated_at": quick_reply.updated_at,
    }


@app.get(
    "/quick-reply-categories/",
    response_model=list[schemas.QuickReplyCategoryOut],
)
def get_quick_reply_categories(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    categories = (
        db.query(models.QuickReplyCategory)
        .order_by(
            models.QuickReplyCategory.sort_order.asc(),
            models.QuickReplyCategory.name.asc(),
        )
        .all()
    )
    counts = dict(
        db.query(
            models.QuickReply.category_id,
            func.count(models.QuickReply.id),
        )
        .filter(
            models.QuickReply.category_id.isnot(None),
            visible_quick_reply_filter(current_user),
        )
        .group_by(models.QuickReply.category_id)
        .all()
    )

    root_categories = [category for category in categories if category.parent_id is None]
    ordered_categories = []
    included_category_ids = set()

    for root_category in root_categories:
        ordered_categories.append(root_category)
        included_category_ids.add(root_category.id)

        for child_category in categories:
            if child_category.parent_id == root_category.id:
                ordered_categories.append(child_category)
                included_category_ids.add(child_category.id)

    ordered_categories.extend(
        category
        for category in categories
        if category.id not in included_category_ids
    )

    return [
        quick_reply_category_to_out(category, counts.get(category.id, 0))
        for category in ordered_categories
    ]


@app.post(
    "/quick-reply-categories/",
    response_model=schemas.QuickReplyCategoryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_quick_reply_category(
    category_create: schemas.QuickReplyCategoryCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only admins can create quick reply categories",
        )

    name = normalize_quick_reply_category_name(category_create.name)
    validate_quick_reply_parent_category(db, category_create.parent_id)

    duplicate = (
        db.query(models.QuickReplyCategory)
        .filter(func.lower(models.QuickReplyCategory.name) == name.lower())
        .first()
    )

    if duplicate:
        raise HTTPException(status_code=400, detail="Category name already exists")

    sort_order = category_create.sort_order

    if sort_order is None:
        highest_sort_order = (
            db.query(func.max(models.QuickReplyCategory.sort_order)).scalar() or 0
        )
        sort_order = highest_sort_order + 10

    category = models.QuickReplyCategory(
        name=name,
        parent_id=category_create.parent_id,
        sort_order=max(0, int(sort_order)),
        created_by_user_id=current_user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    db.add(category)
    db.commit()
    db.refresh(category)

    return quick_reply_category_to_out(category)


@app.patch(
    "/quick-reply-categories/{category_id}",
    response_model=schemas.QuickReplyCategoryOut,
)
def update_quick_reply_category(
    category_id: int,
    category_update: schemas.QuickReplyCategoryUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only admins can update quick reply categories",
        )

    category = get_quick_reply_category_or_404(db, category_id)
    updates = category_update.dict(exclude_unset=True)

    if "name" in updates:
        name = normalize_quick_reply_category_name(updates["name"])
        duplicate = (
            db.query(models.QuickReplyCategory)
            .filter(
                func.lower(models.QuickReplyCategory.name) == name.lower(),
                models.QuickReplyCategory.id != category_id,
            )
            .first()
        )

        if duplicate:
            raise HTTPException(status_code=400, detail="Category name already exists")

        category.name = name

    if "parent_id" in updates:
        validate_quick_reply_parent_category(
            db,
            updates["parent_id"],
            category_id=category_id,
        )
        category.parent_id = updates["parent_id"]

    if "sort_order" in updates and updates["sort_order"] is not None:
        category.sort_order = max(0, int(updates["sort_order"]))

    category.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(category)

    reply_count = (
        db.query(models.QuickReply)
        .filter(models.QuickReply.category_id == category.id)
        .count()
    )
    return quick_reply_category_to_out(category, reply_count)


@app.delete("/quick-reply-categories/{category_id}")
def delete_quick_reply_category(
    category_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only admins can delete quick reply categories",
        )

    category = get_quick_reply_category_or_404(db, category_id)
    db.query(models.QuickReply).filter(
        models.QuickReply.category_id == category.id
    ).update({models.QuickReply.category_id: None}, synchronize_session=False)
    db.query(models.QuickReplyCategory).filter(
        models.QuickReplyCategory.parent_id == category.id
    ).update({models.QuickReplyCategory.parent_id: None}, synchronize_session=False)
    db.delete(category)
    db.commit()

    return {"status": "deleted", "category_id": category_id}


@app.get("/quick-replies/", response_model=list[schemas.QuickReplyOut])
def get_quick_replies(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
    q: str | None = Query(default=None, max_length=120),
    category_id: int | None = Query(default=None),
    favorites_only: bool = Query(default=False),
):
    query = db.query(models.QuickReply).filter(
        visible_quick_reply_filter(current_user)
    )

    if category_id is not None:
        query = query.filter(models.QuickReply.category_id == category_id)

    if favorites_only:
        query = query.join(
            models.QuickReplyFavorite,
            and_(
                models.QuickReplyFavorite.quick_reply_id == models.QuickReply.id,
                models.QuickReplyFavorite.user_id == current_user.id,
            ),
        )

    search_value = str(q or "").strip()

    if search_value:
        search_pattern = f"%{search_value}%"
        query = query.outerjoin(
            models.QuickReplyCategory,
            models.QuickReply.category_id == models.QuickReplyCategory.id,
        ).filter(
            or_(
                models.QuickReply.title.ilike(search_pattern),
                models.QuickReply.shortcut.ilike(search_pattern),
                models.QuickReply.content.ilike(search_pattern),
                models.QuickReplyCategory.name.ilike(search_pattern),
            )
        )

    quick_replies = query.order_by(
        models.QuickReply.sort_order.asc(),
        models.QuickReply.title.asc(),
    ).all()
    categories = db.query(models.QuickReplyCategory).all()
    creator_ids = {reply.created_by_user_id for reply in quick_replies}
    creators = (
        db.query(models.User).filter(models.User.id.in_(creator_ids)).all()
        if creator_ids
        else []
    )
    categories_by_id = {category.id: category for category in categories}
    users_by_id = {creator.id: creator for creator in creators}
    favorite_quick_reply_ids = get_favorite_quick_reply_ids(
        db,
        current_user.id,
        {reply.id for reply in quick_replies},
    )

    quick_replies.sort(
        key=lambda reply: (
            reply.id not in favorite_quick_reply_ids,
            reply.sort_order,
            reply.title.lower(),
        )
    )

    return [
        quick_reply_to_out(
            quick_reply,
            current_user,
            categories_by_id,
            users_by_id,
            favorite_quick_reply_ids,
        )
        for quick_reply in quick_replies
    ]


def ensure_unique_quick_reply_shortcut(
    db: Session,
    shortcut: str | None,
    quick_reply_id: int | None = None,
) -> None:
    if not shortcut:
        return

    query = db.query(models.QuickReply).filter(
        func.lower(models.QuickReply.shortcut) == shortcut.lower()
    )

    if quick_reply_id is not None:
        query = query.filter(models.QuickReply.id != quick_reply_id)

    if query.first():
        raise HTTPException(status_code=400, detail="Shortcut already exists")


@app.post(
    "/quick-replies/",
    response_model=schemas.QuickReplyOut,
    status_code=status.HTTP_201_CREATED,
)
def create_quick_reply(
    quick_reply_create: schemas.QuickReplyCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    if not can_create_quick_replies(current_user):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to create quick replies",
        )

    title = normalize_quick_reply_title(quick_reply_create.title)
    content = normalize_quick_reply_content(quick_reply_create.content)
    shortcut = normalize_quick_reply_shortcut(quick_reply_create.shortcut)
    quick_reply_scope = normalize_quick_reply_scope(quick_reply_create.scope)

    if not can_create_quick_reply_scope(current_user, quick_reply_scope):
        raise HTTPException(
            status_code=403,
            detail="Only admins can create team quick replies",
        )

    ensure_unique_quick_reply_shortcut(db, shortcut)

    if quick_reply_create.category_id is not None:
        get_quick_reply_category_or_404(db, quick_reply_create.category_id)

    sort_order = quick_reply_create.sort_order

    if sort_order is None:
        highest_sort_order = db.query(func.max(models.QuickReply.sort_order)).scalar() or 0
        sort_order = highest_sort_order + 10

    quick_reply = models.QuickReply(
        title=title,
        content=content,
        shortcut=shortcut,
        scope=quick_reply_scope,
        category_id=quick_reply_create.category_id,
        sort_order=max(0, int(sort_order)),
        created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    db.add(quick_reply)
    db.flush()
    set_quick_reply_favorite(
        db,
        current_user.id,
        quick_reply.id,
        bool(quick_reply_create.is_favorite),
    )
    db.commit()
    db.refresh(quick_reply)

    categories = db.query(models.QuickReplyCategory).all()
    return quick_reply_to_out(
        quick_reply,
        current_user,
        {category.id: category for category in categories},
        {current_user.id: current_user},
        {quick_reply.id} if quick_reply_create.is_favorite else set(),
    )


@app.patch("/quick-replies/{quick_reply_id}", response_model=schemas.QuickReplyOut)
def update_quick_reply(
    quick_reply_id: int,
    quick_reply_update: schemas.QuickReplyUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    quick_reply = (
        db.query(models.QuickReply)
        .filter(models.QuickReply.id == quick_reply_id)
        .first()
    )

    if not quick_reply:
        raise HTTPException(status_code=404, detail="Quick reply not found")

    if not can_view_quick_reply(current_user, quick_reply):
        raise HTTPException(status_code=404, detail="Quick reply not found")

    updates = quick_reply_update.dict(exclude_unset=True)
    content_updates = {
        field_name: value
        for field_name, value in updates.items()
        if field_name != "is_favorite"
    }

    if content_updates and not can_edit_quick_reply(current_user, quick_reply):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to edit this quick reply",
        )

    if "title" in updates:
        quick_reply.title = normalize_quick_reply_title(updates["title"])

    if "content" in updates:
        quick_reply.content = normalize_quick_reply_content(updates["content"])

    if "shortcut" in updates:
        shortcut = normalize_quick_reply_shortcut(updates["shortcut"])
        ensure_unique_quick_reply_shortcut(db, shortcut, quick_reply.id)
        quick_reply.shortcut = shortcut

    if "category_id" in updates:
        if updates["category_id"] is not None:
            get_quick_reply_category_or_404(db, updates["category_id"])
        quick_reply.category_id = updates["category_id"]

    if "scope" in updates:
        requested_scope = normalize_quick_reply_scope(updates["scope"])

        if not can_create_quick_reply_scope(current_user, requested_scope):
            raise HTTPException(
                status_code=403,
                detail="Only admins can create team quick replies",
            )

        quick_reply.scope = requested_scope

    if "is_favorite" in updates and updates["is_favorite"] is not None:
        set_quick_reply_favorite(
            db,
            current_user.id,
            quick_reply.id,
            bool(updates["is_favorite"]),
        )

    if "sort_order" in updates and updates["sort_order"] is not None:
        quick_reply.sort_order = max(0, int(updates["sort_order"]))

    if content_updates:
        quick_reply.updated_by_user_id = current_user.id
        quick_reply.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(quick_reply)

    categories = db.query(models.QuickReplyCategory).all()
    creator = (
        db.query(models.User)
        .filter(models.User.id == quick_reply.created_by_user_id)
        .first()
    )
    return quick_reply_to_out(
        quick_reply,
        current_user,
        {category.id: category for category in categories},
        {creator.id: creator} if creator else {},
        get_favorite_quick_reply_ids(db, current_user.id, {quick_reply.id}),
    )


@app.delete("/quick-replies/{quick_reply_id}")
def delete_quick_reply(
    quick_reply_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    quick_reply = (
        db.query(models.QuickReply)
        .filter(models.QuickReply.id == quick_reply_id)
        .first()
    )

    if not quick_reply:
        raise HTTPException(status_code=404, detail="Quick reply not found")

    if not can_view_quick_reply(current_user, quick_reply):
        raise HTTPException(status_code=404, detail="Quick reply not found")

    if not can_edit_quick_reply(current_user, quick_reply):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to delete this quick reply",
        )

    db.query(models.QuickReplyFavorite).filter(
        models.QuickReplyFavorite.quick_reply_id == quick_reply.id
    ).delete(synchronize_session=False)
    db.delete(quick_reply)
    db.commit()

    return {"status": "deleted", "quick_reply_id": quick_reply_id}


@app.post("/token", response_model=LoginResponse)
async def login_for_access_token(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
):
    now = datetime.utcnow()
    cleanup_stale_login_throttles(db, now)
    throttle_key = get_login_throttle_key(request, form_data.username)
    throttle = check_login_throttle(db, throttle_key, now)

    user = get_user(db, form_data.username)
    password_hash = user.hashed_password if user else DUMMY_PASSWORD_HASH
    password_matches = verify_password(form_data.password, password_hash)
    login_allowed = bool(user and password_matches and not user.disabled)

    if not login_allowed:
        retry_after_seconds = record_login_failure(
            db,
            throttle_key,
            throttle,
            now,
        )

        if retry_after_seconds is not None:
            raise_login_throttled(retry_after_seconds)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    clear_login_failures(db, throttle_key)

    if user.mfa_enabled:
        if trusted_device_is_valid(db, user, request, response, now):
            token = issue_access_token_for_user(user)
            return LoginResponse(
                access_token=token.access_token,
                token_type=token.token_type,
            )

        challenge_token = create_mfa_login_challenge(db, user, now)
        return LoginResponse(
            mfa_required=True,
            challenge_token=challenge_token,
            trusted_device_available=user.role != "admin",
        )

    token = issue_access_token_for_user(user)
    return LoginResponse(
        access_token=token.access_token,
        token_type=token.token_type,
    )


@app.post("/token/mfa", response_model=Token)
def complete_mfa_login(
    verification: schemas.MfaLoginVerifyRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
):
    now = datetime.utcnow()
    challenge_hash = hash_mfa_challenge_token(verification.challenge_token)
    challenge = (
        db.query(models.MfaLoginChallenge)
        .filter(models.MfaLoginChallenge.challenge_hash == challenge_hash)
        .first()
    )

    if (
        not challenge
        or challenge.consumed_at is not None
        or challenge.expires_at <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticator request expired. Sign in again.",
        )

    if challenge.failed_attempts >= MFA_CHALLENGE_MAX_ATTEMPTS:
        challenge.consumed_at = now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Too many authenticator attempts. Sign in again.",
        )

    user = db.query(models.User).filter(models.User.id == challenge.user_id).first()

    if not user or user.disabled or not user.mfa_enabled:
        challenge.consumed_at = now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticator login is no longer available. Sign in again.",
        )

    if not verify_and_consume_mfa_code(user, verification.code):
        challenge.failed_attempts += 1

        if challenge.failed_attempts >= MFA_CHALLENGE_MAX_ATTEMPTS:
            challenge.consumed_at = now

        db.commit()

        if challenge.consumed_at is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Too many authenticator attempts. Sign in again.",
            )

        attempts_left = MFA_CHALLENGE_MAX_ATTEMPTS - challenge.failed_attempts
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authenticator code. {attempts_left} attempts remaining.",
        )

    challenge.consumed_at = now

    if verification.trust_device and user.role != "admin":
        create_trusted_device(db, user, response, now)
    else:
        db.commit()

    return issue_access_token_for_user(user)


@app.get("/users/me/", response_model=schemas.UserOut)
async def read_users_me(
    current_user: Annotated[models.User, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")

    return current_user


@app.get(
    "/conversations/summary/",
    response_model=schemas.ConversationSummaryOut,
)
def get_conversation_summary(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    active_filter = models.Conversation.status != "archived"

    summary = db.query(
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            active_filter,
                            models.Conversation.unread_count > 0,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("inbox_unread_conversations"),
        func.coalesce(
            func.sum(
                case(
                    (active_filter, models.Conversation.unread_count),
                    else_=0,
                )
            ),
            0,
        ).label("unread_messages"),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            active_filter,
                            models.Conversation.assigned_to_user_id == current_user.id,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("mine"),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(active_filter, models.Conversation.follow_up.is_(True)),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("follow_up"),
        func.coalesce(
            func.sum(
                case((models.Conversation.status == "archived", 1), else_=0)
            ),
            0,
        ).label("archived"),
    ).one()

    return {
        "inbox_unread_conversations": int(summary.inbox_unread_conversations or 0),
        "unread_messages": int(summary.unread_messages or 0),
        "mine": int(summary.mine or 0),
        "follow_up": int(summary.follow_up or 0),
        "archived": int(summary.archived or 0),
    }


@app.get("/conversations/", response_model=list[schemas.ConversationOut])
def get_conversations(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
    q: str | None = Query(default=None, max_length=100),
    view: str = Query(default="all"),
    limit: int | None = Query(default=None, ge=1, le=201),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(models.Conversation)

    normalized_view = view.strip().lower()

    if normalized_view not in {"all", "inbox", "mine", "follow_up", "archived"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation view",
        )

    if normalized_view == "inbox":
        query = query.filter(models.Conversation.status != "archived")
    elif normalized_view == "mine":
        query = query.filter(
            models.Conversation.status != "archived",
            models.Conversation.assigned_to_user_id == current_user.id,
        )
    elif normalized_view == "follow_up":
        query = query.filter(
            models.Conversation.status != "archived",
            models.Conversation.follow_up.is_(True),
        )
    elif normalized_view == "archived":
        query = query.filter(models.Conversation.status == "archived")

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

    ordered_query = query.order_by(
        models.Conversation.updated_at.desc(),
        models.Conversation.id.desc(),
    )

    if offset:
        ordered_query = ordered_query.offset(offset)

    if limit is not None:
        ordered_query = ordered_query.limit(limit)

    conversations = ordered_query.all()

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

    current_user_id = current_user.id

    # Authentication and validation queries start a transaction. Release that
    # database connection while Meta's API is doing network I/O, then let this
    # Session acquire a connection again only when persistence resumes.
    db.close()

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
            user_id=current_user_id,
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
        user_id=current_user_id,
        conversation_id=conversation.id,
    )

    db.add(db_message)
    db.commit()
    db.refresh(conversation)

    print(
        f"[SEND_TEMPLATE] conversation_id={conversation.id} "
        f"user_id={current_user_id} "
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
    limit: int = Query(default=100, ge=1, le=200),
    after_id: int | None = Query(default=None, ge=1),
    before_id: int | None = Query(default=None, ge=1),
):
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not user_can_access_conversation(current_user, conversation):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this conversation",
        )

    query = db.query(models.Message).filter(
        models.Message.conversation_id == conversation_id
    )

    if after_id is not None:
        messages = (
            query.filter(models.Message.id > after_id)
            .order_by(models.Message.id.asc())
            .limit(limit)
            .all()
        )
    elif before_id is not None:
        messages = (
            query.filter(models.Message.id < before_id)
            .order_by(models.Message.id.desc())
            .limit(limit)
            .all()
        )
        messages.reverse()
    else:
        messages = query.order_by(models.Message.id.desc()).limit(limit).all()
        messages.reverse()

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

    media_id = db_message.media_id
    media_mime_type = db_message.media_mime_type
    media_filename = db_message.media_filename
    message_id_for_filename = db_message.id

    # Media retrieval can involve two slow external requests. Everything needed
    # from PostgreSQL is already loaded, so release the connection first.
    db.close()

    media_info_url = (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/" f"{media_id}"
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
        or media_mime_type
        or "application/octet-stream"
    )

    safe_filename = (
        media_filename or f"whatsapp-media-{message_id_for_filename}"
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

    recipient_phone = conversation.contact_phone
    current_user_id = current_user.id

    # Do not occupy a pooled database connection during the external request.
    db.close()

    whatsapp_result = send_whatsapp_text_message(
        to_phone=recipient_phone,
        text=message.content,
    )

    whatsapp_message_id = extract_whatsapp_message_id(whatsapp_result)
    now = datetime.utcnow()

    conversation = get_conversation(db, conversation_id)

    if conversation is None:
        raise HTTPException(
            status_code=409,
            detail="Message was sent, but the conversation no longer exists",
        )

    db_message = models.Message(
        content=message.content,
        direction="outbound",
        is_read=True,
        whatsapp_message_id=whatsapp_message_id,
        whatsapp_status="sent" if whatsapp_message_id else None,
        whatsapp_status_updated_at=now if whatsapp_message_id else None,
        user_id=current_user_id,
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
        f"user_id={current_user_id} "
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

    recipient_phone = conversation.contact_phone
    whatsapp_message_id = db_message.whatsapp_message_id
    current_user_id = current_user.id

    # Reactions can wait up to 20 seconds on Meta. Return the read transaction's
    # connection to the pool before making that network call.
    db.close()

    whatsapp_result = send_whatsapp_reaction_message(
        to_phone=recipient_phone,
        whatsapp_message_id=whatsapp_message_id,
        emoji=reaction_emoji,
    )

    now = datetime.utcnow()

    db_message = (
        db.query(models.Message).filter(models.Message.id == message_id).first()
    )

    if db_message is None:
        raise HTTPException(
            status_code=409,
            detail="Reaction was sent, but the message no longer exists",
        )

    conversation = get_conversation(db, db_message.conversation_id)

    if conversation is None:
        raise HTTPException(
            status_code=409,
            detail="Reaction was sent, but the conversation no longer exists",
        )

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
        f"user_id={current_user_id} "
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


@app.post("/conversations/archive-old/")
def archive_old_conversations(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
    hours: int = Query(default=36, ge=1, le=24 * 365),
    dry_run: bool = Query(default=True),
    limit: int = Query(default=200, ge=1, le=1000),
):
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only admins can archive old conversations",
        )

    now = datetime.utcnow()
    cutoff = now - timedelta(hours=hours)

    old_conversations = (
        db.query(models.Conversation)
        .filter(
            models.Conversation.status != "archived",
            models.Conversation.last_message_at <= cutoff,
            models.Conversation.unread_count == 0,
            models.Conversation.assigned_to_user_id.is_(None),
            models.Conversation.follow_up.is_(False),
        )
        .order_by(models.Conversation.last_message_at.asc())
        .limit(limit)
        .all()
    )

    archived_conversations = []

    for conversation in old_conversations:
        archived_conversations.append(
            {
                "id": conversation.id,
                "contact_name": conversation.contact_name,
                "contact_phone": conversation.contact_phone,
                "status": conversation.status,
                "last_message_at": conversation.last_message_at,
            }
        )

        if not dry_run:
            conversation.status = "archived"
            conversation.unread_count = 0
            conversation.updated_at = now

    if not dry_run:
        db.commit()

    print(
        f"[ARCHIVE_OLD] dry_run={dry_run} hours={hours} "
        f"matched={len(old_conversations)} archived_by={current_user.id}",
        flush=True,
    )

    return {
        "status": "ok",
        "dry_run": dry_run,
        "hours": hours,
        "cutoff": cutoff,
        "matched_count": len(old_conversations),
        "archived_count": 0 if dry_run else len(old_conversations),
        "conversations": archived_conversations,
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
