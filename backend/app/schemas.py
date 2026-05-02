from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# =====================
# USER
# =====================

class UserBase(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str
    role: Optional[str] = None


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
    follow_up: bool
    unread_count: int
    last_message_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

# =====================
# WEBHOOK TEMPLATE API
# =====================


class TemplateBatchItem(BaseModel):
    external_id: str
    template_type: str
    phone: Optional[str] = None

    guest_name: Optional[str] = None
    tour_name: Optional[str] = None
    reservation_number: Optional[str] = None
    cruise_date: Optional[str] = None
    pickup_time: Optional[str] = None
    pickup_point: Optional[str] = None

    google_maps: Optional[str] = None
    passenger_info_link: Optional[str] = None


class TemplateBatchRequest(BaseModel):
    batch_id: str
    batch_label: Optional[str] = None
    source: Optional[str] = None
    event: Optional[str] = None

    option_code: Optional[str] = None
    vessel_name: Optional[str] = None
    cruise_type: Optional[str] = None
    cruise_slot: Optional[str] = None
    operation_date: Optional[str] = None

    items: list[TemplateBatchItem] = Field(default_factory=list)


class TemplateBatchResult(BaseModel):
    external_id: str
    template_type: Optional[str] = None
    phone: Optional[str] = None

    status: str
    reason: Optional[str] = None
    whatsapp_message_id: Optional[str] = None


class TemplateBatchResponse(BaseModel):
    batch_id: str
    batch_label: Optional[str] = None
    total: int
    sent: int
    failed: int
    no_number: int
    invalid_number: int
    validation_failed: int
    results: list[TemplateBatchResult]        