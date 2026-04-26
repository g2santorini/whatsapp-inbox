from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# =====================
# USER
# =====================

class UserBase(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserOut(UserBase):
    id: int
    role: str
    disabled: bool

    class Config:
        orm_mode = True


class UserUpdate(BaseModel):
    role: Optional[str] = None
    disabled: Optional[bool] = None


# =====================
# MESSAGE
# =====================

class MessageBase(BaseModel):
    content: str


class MessageCreate(MessageBase):
    pass


class MessageOut(MessageBase):
    id: int
    direction: str
    is_read: bool
    created_at: datetime

    class Config:
        orm_mode = True


# =====================
# CONVERSATION
# =====================

class ConversationBase(BaseModel):
    contact_name: Optional[str] = None
    contact_phone: str


class ConversationCreate(ConversationBase):
    pass


class ConversationOut(ConversationBase):
    id: int
    status: str
    assigned_to_user_id: Optional[int]
    unread_count: int
    last_message_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True