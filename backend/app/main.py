import os
import requests
from datetime import datetime, timedelta
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import inspect, or_, text
from sqlalchemy.orm import Session

from . import models, schemas
from .database import Base, engine, get_db

load_dotenv()

app = FastAPI(title="WhatsApp Inbox")
APP_VERSION = "sendro-debug-2026-04-28-02"

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

VERIFY_TOKEN = "sendro_verify_token_123"

Base.metadata.create_all(bind=engine)

def ensure_follow_up_column():
    inspector = inspect(engine)

    try:
        columns = [
            column["name"]
            for column in inspector.get_columns("conversations")
        ]
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


ensure_follow_up_column()

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


def normalize_whatsapp_phone(phone: str) -> str:
    return phone.strip().replace("+", "").replace(" ", "")


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


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None

class FollowUpUpdate(BaseModel):
    follow_up: bool    

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

        if "messages" not in value:
            print("ℹ️ WHATSAPP WEBHOOK RECEIVED WITHOUT MESSAGE", flush=True)
            print(value, flush=True)
            return {"status": "ok"}

        message = value["messages"][0]
        contact = value["contacts"][0]

        text = message["text"]["body"]
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

    return conversations


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

    return db_conversation


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

    db_message = models.Message(
        content=message.content,
        direction="outbound",
        is_read=True,
        user_id=current_user.id,
        conversation_id=conversation_id,
    )

    db.add(db_message)

    conversation.unread_count = 0
    touch_conversation(conversation)

    db.commit()
    db.refresh(db_message)

    print(
        f"[SEND] conversation_id={conversation_id} "
        f"user_id={current_user.id} assigned_to={current_user.id} "
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
