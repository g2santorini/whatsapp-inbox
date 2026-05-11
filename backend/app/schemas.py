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
    can_view_reports: bool

    class Config:
        orm_mode = True


class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    disabled: Optional[bool] = None
    can_view_reports: Optional[bool] = None


class UserPasswordReset(BaseModel):
    password: str = Field(..., min_length=6)


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

    user_id: int
    author_name: Optional[str] = None
    author_username: Optional[str] = None
    author_role: Optional[str] = None

    message_type: Optional[str] = "text"
    media_id: Optional[str] = None
    media_mime_type: Optional[str] = None
    media_filename: Optional[str] = None

    whatsapp_message_id: Optional[str] = None
    whatsapp_status: Optional[str] = None
    whatsapp_status_updated_at: Optional[datetime] = None

    reaction_emoji: Optional[str] = None
    reaction_updated_at: Optional[datetime] = None

    created_at: datetime


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

    customer_service_expires_at: Optional[datetime] = None
    customer_service_window_open: bool = False
    customer_service_time_left_seconds: Optional[int] = None
    last_message_direction: Optional[str] = None

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
    duplicate: int = 0
    results: list[TemplateBatchResult]


# =====================
# TEMPLATE BATCH REPORTING
# =====================


class TemplateBatchReportItemOut(BaseModel):
    id: int

    batch_id: str

    external_id: Optional[str] = None
    reservation_number: Optional[str] = None

    guest_name: Optional[str] = None
    phone: Optional[str] = None

    option_code: Optional[str] = None
    operation_date: Optional[str] = None
    tour_name: Optional[str] = None

    template_type: str

    status: str
    reason: Optional[str] = None

    whatsapp_message_id: Optional[str] = None
    whatsapp_status: Optional[str] = None
    whatsapp_status_updated_at: Optional[datetime] = None

    conversation_id: Optional[int] = None
    message_id: Optional[int] = None

    duplicate_key: Optional[str] = None
    content_hash: Optional[str] = None

    created_at: datetime

    class Config:
        orm_mode = True


class TemplateBatchReportSummaryOut(BaseModel):
    id: int

    batch_id: str
    batch_label: Optional[str] = None

    source: Optional[str] = None
    event: Optional[str] = None

    option_code: Optional[str] = None
    operation_date: Optional[str] = None
    tour_name: Optional[str] = None

    total: int
    sent: int
    failed: int
    no_number: int
    invalid_number: int
    validation_failed: int
    duplicate: int

    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class TemplateBatchReportDetailOut(TemplateBatchReportSummaryOut):
    items: list[TemplateBatchReportItemOut] = Field(default_factory=list)


# =====================
# TEMPLATE REPORT ITEMS - FLAT OPERATIONS REPORT
# =====================


class TemplateReportSummaryOut(BaseModel):
    total: int = 0

    sent: int = 0
    delivered: int = 0
    read: int = 0
    failed: int = 0

    problems: int = 0
    missing_phone: int = 0
    invalid_phone: int = 0
    missing_details: int = 0

    duplicates: int = 0
    waiting_status: int = 0


class TemplateReportItemOut(BaseModel):
    id: int

    batch_id: str
    batch_label: Optional[str] = None

    operation_date: Optional[str] = None
    option_code: Optional[str] = None
    tour_name: Optional[str] = None

    reservation_number: Optional[str] = None
    external_id: Optional[str] = None

    guest_name: Optional[str] = None
    phone: Optional[str] = None

    template_type: str
    template_label: str

    status: str
    status_label: str

    whatsapp_status: Optional[str] = None
    whatsapp_status_label: str

    result_label: str
    problem_label: Optional[str] = None
    reason: Optional[str] = None

    whatsapp_message_id: Optional[str] = None

    conversation_id: Optional[int] = None
    message_id: Optional[int] = None

    sent_at: Optional[datetime] = None
    whatsapp_status_updated_at: Optional[datetime] = None


class TemplateReportItemsResponse(BaseModel):
    summary: TemplateReportSummaryOut
    items: list[TemplateReportItemOut] = Field(default_factory=list)
