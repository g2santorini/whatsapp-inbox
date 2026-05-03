import os
import requests
from datetime import datetime, timedelta
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
    send_whatsapp_template_message as send_meta_template_message,
)

load_dotenv()

app = FastAPI(title="WhatsApp Inbox")
APP_VERSION = "sendro-customer-service-window-2026-05-03"

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

    if not columns_to_add:
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


ensure_follow_up_column()
ensure_message_status_columns()

app.mount("/static", StaticFiles(directory="app/static"), name="static")


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


SECRET_KEY = get_required_env("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

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

    for conversation in conversations:
        last_inbound_at = last_inbound_by_conversation_id.get(conversation.id)
        fields = build_customer_service_window_fields(last_inbound_at)
        apply_customer_service_window_fields(conversation, fields)

    return conversations


def attach_customer_service_window_to_conversation(
    db: Session,
    conversation: models.Conversation,
):
    attach_customer_service_window_data(db, [conversation])
    return conversation


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


def user_can_access_conversation(
    user: models.User,
    conversation: models.Conversation,
) -> bool:
    if can_view_all_conversations(user):
        return True

    return (
        conversation.assigned_to_user_id is None
        or conversation.assigned_to_user_id == user.id
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


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


@app.get("/debug/version")
def debug_version():
    return {"version": APP_VERSION}


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

    results: list[schemas.TemplateBatchResult] = []

    sent_count = 0
    failed_count = 0
    no_number_count = 0
    invalid_number_count = 0
    validation_failed_count = 0

    for item in batch.items:
        item_data = item.dict()

        external_id = item.external_id
        template_type = item.template_type
        phone = item.phone.strip() if item.phone else None

        if not phone:
            no_number_count += 1
            results.append(
                schemas.TemplateBatchResult(
                    external_id=external_id,
                    template_type=template_type,
                    phone=item.phone,
                    status="no_number",
                    reason="Phone number is empty or missing",
                )
            )
            continue

        if not is_valid_e164_phone(phone):
            invalid_number_count += 1
            results.append(
                schemas.TemplateBatchResult(
                    external_id=external_id,
                    template_type=template_type,
                    phone=phone,
                    status="invalid_number",
                    reason="Phone number must be in E.164 format, for example +306900000000",
                )
            )
            continue

        try:
            template_definition = get_template_definition(template_type)
        except KeyError as exc:
            validation_failed_count += 1
            results.append(
                schemas.TemplateBatchResult(
                    external_id=external_id,
                    template_type=template_type,
                    phone=phone,
                    status="validation_failed",
                    reason=str(exc),
                )
            )
            continue

        missing_fields = missing_required_fields(template_type, item_data)

        if missing_fields:
            validation_failed_count += 1
            results.append(
                schemas.TemplateBatchResult(
                    external_id=external_id,
                    template_type=template_type,
                    phone=phone,
                    status="validation_failed",
                    reason=f"Missing required fields: {', '.join(missing_fields)}",
                )
            )
            continue

        body_variables = build_template_variables(template_type, item_data)

        try:
            whatsapp_result = send_meta_template_message(
                to_phone=phone,
                template_name=template_definition.meta_template_name,
                language_code=template_definition.language_code,
                body_variables=body_variables,
            )

            whatsapp_message_id = extract_whatsapp_message_id(whatsapp_result)

            sent_count += 1
            results.append(
                schemas.TemplateBatchResult(
                    external_id=external_id,
                    template_type=template_type,
                    phone=phone,
                    status="sent",
                    reason=None,
                    whatsapp_message_id=whatsapp_message_id,
                )
            )

        except Exception as exc:
            failed_count += 1
            results.append(
                schemas.TemplateBatchResult(
                    external_id=external_id,
                    template_type=template_type,
                    phone=phone,
                    status="failed",
                    reason=str(exc),
                )
            )

    return schemas.TemplateBatchResponse(
        batch_id=batch.batch_id,
        batch_label=batch.batch_label,
        total=len(batch.items),
        sent=sent_count,
        failed=failed_count,
        no_number=no_number_count,
        invalid_number=invalid_number_count,
        validation_failed=validation_failed_count,
        results=results,
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

                if db_message is None:
                    print(
                        f"⚠️ WHATSAPP STATUS FOR UNKNOWN MESSAGE: "
                        f"{whatsapp_message_id} -> {whatsapp_status}",
                        flush=True,
                    )
                    continue

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
                    f"✅ WHATSAPP STATUS UPDATED: "
                    f"message_id={db_message.id} "
                    f"wamid={whatsapp_message_id} "
                    f"status={whatsapp_status}",
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

        message_type = message.get("type", "unknown")

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
            emoji = reaction.get("emoji") or ""
            text = f"[Reaction: {emoji}]" if emoji else "[Reaction]"
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

    new_role = None

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

    if new_role is not None:
        db_user.role = new_role

    if user_update.disabled is not None:
        db_user.disabled = user_update.disabled

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
):
    query = db.query(models.Conversation)

    if not can_view_all_conversations(current_user):
        query = query.filter(
            or_(
                models.Conversation.assigned_to_user_id.is_(None),
                models.Conversation.assigned_to_user_id == current_user.id,
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

    if template_request.template_name != "cruise_pickup_reminder":
        raise HTTPException(
            status_code=400,
            detail="Only cruise_pickup_reminder is supported for now",
        )

    if len(template_request.variables) != 7:
        raise HTTPException(
            status_code=400,
            detail="cruise_pickup_reminder requires exactly 7 variables",
        )

    preview_content = template_request.preview_content.strip()

    if not preview_content:
        raise HTTPException(
            status_code=400,
            detail="Preview content is required",
        )

    whatsapp_result = send_whatsapp_template_message(
        to_phone=f"+{normalized_phone}",
        template_name=template_request.template_name,
        language_code=template_request.language_code,
        variables=template_request.variables,
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
        f"template={template_request.template_name} "
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

    return messages


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

    return db_message


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

    deleted_messages_count = (
        db.query(models.Message)
        .filter(models.Message.conversation_id == conversation_id)
        .delete()
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

    return db_message


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
