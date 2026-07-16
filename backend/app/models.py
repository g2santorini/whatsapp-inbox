from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="operator", nullable=False)
    disabled = Column(Boolean, default=False, nullable=False)
    can_view_reports = Column(Boolean, default=False, nullable=False)


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