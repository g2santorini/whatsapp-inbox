from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    display_name = Column(String, nullable=True)
    assignment_color = Column(String(7), nullable=True)
    assignment_text_color = Column(String(7), nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="operator", nullable=False)
    disabled = Column(Boolean, default=False, nullable=False)
    can_view_reports = Column(Boolean, default=False, nullable=False)
    auth_version = Column(Integer, default=1, nullable=False)
    must_change_password = Column(Boolean, default=False, nullable=False)


class LoginThrottle(Base):
    __tablename__ = "login_throttles"

    id = Column(Integer, primary_key=True, index=True)
    throttle_key = Column(String(64), unique=True, index=True, nullable=False)
    failed_attempts = Column(Integer, default=0, nullable=False)
    window_started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    last_failed_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)


class QuickReplyCategory(Base):
    __tablename__ = "quick_reply_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(60), unique=True, index=True, nullable=False)
    parent_id = Column(
        Integer,
        ForeignKey("quick_reply_categories.id"),
        nullable=True,
    )
    sort_order = Column(Integer, default=0, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class QuickReply(Base):
    __tablename__ = "quick_replies"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), index=True, nullable=False)
    shortcut = Column(String(40), unique=True, index=True, nullable=True)
    content = Column(Text, nullable=False)
    scope = Column(String(16), default="personal", nullable=False, index=True)
    category_id = Column(
        Integer,
        ForeignKey("quick_reply_categories.id"),
        nullable=True,
    )
    sort_order = Column(Integer, default=0, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class QuickReplyFavorite(Base):
    __tablename__ = "quick_reply_favorites"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "quick_reply_id",
            name="uq_quick_reply_favorite_user_reply",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    quick_reply_id = Column(
        Integer,
        ForeignKey("quick_replies.id"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    contact_name = Column(String, nullable=True)
    contact_phone = Column(String, index=True, nullable=False)

    status = Column(String, default="open", nullable=False)
    assigned_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    follow_up = Column(Boolean, default=False, nullable=False)

    unread_count = Column(Integer, default=0, nullable=False)
    last_message_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)

    direction = Column(String, nullable=False, default="outbound")
    is_read = Column(Boolean, default=False, nullable=False)

    message_type = Column(String, default="text", nullable=False)
    media_id = Column(String, index=True, nullable=True)
    media_mime_type = Column(String, nullable=True)
    media_filename = Column(String, nullable=True)

    whatsapp_message_id = Column(String, index=True, nullable=True)
    whatsapp_status = Column(String, nullable=True)
    whatsapp_status_updated_at = Column(DateTime, nullable=True)

    reaction_emoji = Column(String, nullable=True)
    reaction_updated_at = Column(DateTime, nullable=True)
    inbound_reaction_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)


class TemplateBatch(Base):
    __tablename__ = "template_batches"

    id = Column(Integer, primary_key=True, index=True)

    batch_id = Column(String, unique=True, index=True, nullable=False)
    batch_label = Column(String, nullable=True)

    source = Column(String, nullable=True)
    event = Column(String, nullable=True)

    option_code = Column(String, index=True, nullable=True)
    operation_date = Column(String, index=True, nullable=True)
    tour_name = Column(String, nullable=True)

    total = Column(Integer, default=0, nullable=False)
    sent = Column(Integer, default=0, nullable=False)
    failed = Column(Integer, default=0, nullable=False)
    no_number = Column(Integer, default=0, nullable=False)
    invalid_number = Column(Integer, default=0, nullable=False)
    validation_failed = Column(Integer, default=0, nullable=False)
    duplicate = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TemplateBatchItem(Base):
    __tablename__ = "template_batch_items"

    id = Column(Integer, primary_key=True, index=True)

    batch_db_id = Column(Integer, ForeignKey("template_batches.id"), nullable=False)
    batch_id = Column(String, index=True, nullable=False)

    external_id = Column(String, index=True, nullable=True)
    reservation_number = Column(String, index=True, nullable=True)

    guest_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)

    option_code = Column(String, index=True, nullable=True)
    operation_date = Column(String, index=True, nullable=True)
    tour_name = Column(String, nullable=True)

    template_type = Column(String, index=True, nullable=False)

    status = Column(String, index=True, nullable=False)
    reason = Column(Text, nullable=True)

    whatsapp_message_id = Column(String, index=True, nullable=True)
    whatsapp_status = Column(String, nullable=True)
    whatsapp_status_updated_at = Column(DateTime, nullable=True)

    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)

    duplicate_key = Column(String, index=True, nullable=True)
    content_hash = Column(String, index=True, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
