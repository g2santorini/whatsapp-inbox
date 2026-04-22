import os
from datetime import datetime, timedelta
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import models, schemas
from .database import Base, engine, get_db

load_dotenv()

app = FastAPI(title="WhatsApp Inbox")

Base.metadata.create_all(bind=engine)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


SECRET_KEY = get_required_env("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def get_user(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()


def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()


def get_conversation(db: Session, conversation_id: int, user_id: int):
    return (
        db.query(models.Conversation)
        .filter(
            models.Conversation.id == conversation_id,
            models.Conversation.user_id == user_id,
        )
        .first()
    )


def touch_conversation(conversation: models.Conversation):
    conversation.updated_at = datetime.utcnow()


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
    current_user: Annotated[models.User, Depends(get_current_user)]
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


@app.post("/users/", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    user: schemas.UserCreate,
    db: Annotated[Session, Depends(get_db)],
):
    existing_user = get_user(db, user.username)
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    existing_email = get_user_by_email(db, user.email)
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = get_password_hash(user.password)

    db_user = models.User(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        hashed_password=hashed_password,
        disabled=False,
    )

    db.add(db_user)
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
    current_user: Annotated[models.User, Depends(get_current_active_user)]
):
    return current_user


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
    db_conversation = models.Conversation(
        contact_name=conversation.contact_name,
        contact_phone=conversation.contact_phone,
        user_id=current_user.id,
    )

    db.add(db_conversation)
    db.commit()
    db.refresh(db_conversation)

    return db_conversation


@app.get("/conversations/", response_model=list[schemas.ConversationOut])
def get_my_conversations(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversations = (
        db.query(models.Conversation)
        .filter(models.Conversation.user_id == current_user.id)
        .order_by(models.Conversation.updated_at.desc())
        .all()
    )

    return conversations


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
    conversation = get_conversation(db, conversation_id, current_user.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db_message = models.Message(
        content=message.content,
        direction="outbound",
        is_read=True,
        user_id=current_user.id,
        conversation_id=conversation_id,
    )

    db.add(db_message)

    conversation.assigned_to_user_id = current_user.id
    conversation.status = "taken"
    touch_conversation(conversation)

    db.commit()
    db.refresh(db_message)

    print(f"[ASSIGN_ON_SEND] conversation_id={conversation_id} assigned_to={current_user.id}")

    return db_message


@app.post("/conversations/{conversation_id}/take/")
def take_conversation(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id, current_user.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation.assigned_to_user_id = current_user.id
    conversation.status = "taken"
    touch_conversation(conversation)

    db.commit()

    print(f"[TAKE] conversation_id={conversation_id} assigned_to={current_user.id}")

    return {
        "status": "ok",
        "conversation_id": conversation_id,
        "assigned_to_user_id": current_user.id,
        "conversation_status": conversation.status,
    }


@app.post("/conversations/{conversation_id}/release/")
def release_conversation(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id, current_user.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation.assigned_to_user_id = None
    conversation.status = "open"
    touch_conversation(conversation)

    db.commit()

    print(f"[RELEASE] conversation_id={conversation_id} released_by={current_user.id}")

    return {
        "status": "ok",
        "conversation_id": conversation_id,
        "assigned_to_user_id": None,
        "conversation_status": conversation.status,
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
    conversation = get_conversation(db, conversation_id, current_user.id)
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

    conversation.assigned_to_user_id = None
    conversation.status = "open"
    touch_conversation(conversation)

    db.commit()
    db.refresh(db_message)

    print(
        f"[SIMULATE_INBOUND] conversation_id={conversation_id} "
        f"user_id={current_user.id} reset_to_open=True content={message.content!r}"
    )

    return db_message


@app.post("/conversations/{conversation_id}/mark-as-read/")
def mark_conversation_as_read(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id, current_user.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    unread_messages = (
        db.query(models.Message)
        .filter(
            models.Message.user_id == current_user.id,
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

    db.commit()

    print(
        f"[MARK_AS_READ] conversation_id={conversation_id} "
        f"user_id={current_user.id} updated_count={updated_count}"
    )

    return {"status": "ok", "updated_count": updated_count}


@app.get(
    "/conversations/{conversation_id}/messages/",
    response_model=list[schemas.MessageOut],
)
def get_conversation_messages(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_active_user)],
):
    conversation = get_conversation(db, conversation_id, current_user.id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        db.query(models.Message)
        .filter(
            models.Message.user_id == current_user.id,
            models.Message.conversation_id == conversation_id,
        )
        .order_by(models.Message.created_at.asc())
        .all()
    )

    return messages


@app.get("/")
def read_root():
    return {"status": "ok"}


@app.get("/test")
def read_test_page():
    return FileResponse("app/static/test.html")
