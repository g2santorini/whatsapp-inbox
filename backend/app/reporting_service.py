from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import models, schemas


ALLOWED_TEMPLATE_ITEM_STATUSES = {
    "sent",
    "failed",
    "no_number",
    "invalid_number",
    "validation_failed",
    "duplicate",
}

ALLOWED_WHATSAPP_STATUSES = {
    "sent",
    "delivered",
    "read",
    "failed",
}


def normalize_filter_value(value: str | None) -> str | None:
    if not value:
        return None

    normalized_value = value.strip().lower()

    if not normalized_value:
        return None

    return normalized_value


def normalize_template_item_status(status_value: str | None) -> str | None:
    normalized_status = normalize_filter_value(status_value)

    if normalized_status is None:
        return None

    if normalized_status not in ALLOWED_TEMPLATE_ITEM_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid status filter. Allowed values: "
                "sent, failed, no_number, invalid_number, validation_failed, duplicate"
            ),
        )

    return normalized_status


def normalize_whatsapp_status(whatsapp_status: str | None) -> str | None:
    normalized_status = normalize_filter_value(whatsapp_status)

    if normalized_status is None:
        return None

    if normalized_status not in ALLOWED_WHATSAPP_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid whatsapp_status filter. Allowed values: "
                "sent, delivered, read, failed"
            ),
        )

    return normalized_status


def get_template_label(template_type: str) -> str:
    labels = {
        "pickup_reminder_hotel": "Pickup reminder - hotel",
        "pickup_reminder_hotel_missing_details": "Pickup reminder - hotel + missing details",
        "pickup_reminder_meeting_point": "Pickup reminder - meeting point",
        "pickup_reminder_meeting_point_missing_details": "Pickup reminder - meeting point + missing details",
        "missing_hotel_details": "Missing hotel details request",
        "cruise_pickup_reminder": "Pickup reminder - legacy",
        "post_call_followup_request": "Post-call follow-up request",
    }

    if template_type in labels:
        return labels[template_type]

    return template_type.replace("_", " ").title()


def get_status_label(status_value: str) -> str:
    labels = {
        "sent": "Sent",
        "failed": "Failed",
        "no_number": "Not sent - missing phone",
        "invalid_number": "Not sent - invalid phone",
        "validation_failed": "Not sent - missing details",
        "duplicate": "Blocked duplicate",
    }

    return labels.get(status_value, status_value.replace("_", " ").title())


def get_whatsapp_status_label(whatsapp_status: str | None) -> str:
    if not whatsapp_status:
        return "-"

    labels = {
        "sent": "Sent, waiting for delivery/read",
        "delivered": "Delivered",
        "read": "Read",
        "failed": "WhatsApp failed",
    }

    return labels.get(whatsapp_status, whatsapp_status.replace("_", " ").title())


def get_problem_label(
    status_value: str,
    whatsapp_status: str | None,
) -> str | None:
    if status_value == "no_number":
        return "Missing phone number"

    if status_value == "invalid_number":
        return "Invalid phone number"

    if status_value == "validation_failed":
        return "Missing required details"

    if status_value == "failed":
        return "Send failed"

    if whatsapp_status == "failed":
        return "WhatsApp delivery failed"

    return None


def get_result_label(
    status_value: str,
    whatsapp_status: str | None,
) -> str:
    if status_value == "sent":
        if whatsapp_status == "read":
            return "Sent and read"

        if whatsapp_status == "delivered":
            return "Sent and delivered"

        if whatsapp_status == "failed":
            return "Sent, then failed by WhatsApp"

        return "Sent, waiting for delivery/read"

    if status_value == "duplicate":
        return "Blocked as duplicate"

    if status_value == "no_number":
        return "Not sent - missing phone"

    if status_value == "invalid_number":
        return "Not sent - invalid phone"

    if status_value == "validation_failed":
        return "Not sent - missing details"

    if status_value == "failed":
        return "Failed"

    return status_value.replace("_", " ").title()


def is_problem_item(
    status_value: str,
    whatsapp_status: str | None,
) -> bool:
    if status_value in {
        "failed",
        "no_number",
        "invalid_number",
        "validation_failed",
    }:
        return True

    if whatsapp_status == "failed":
        return True

    return False


def build_template_report_summary(
    items: list[models.TemplateBatchItem],
) -> schemas.TemplateReportSummaryOut:
    summary = schemas.TemplateReportSummaryOut(total=len(items))

    for item in items:
        status_value = item.status
        whatsapp_status = item.whatsapp_status

        if status_value == "sent":
            summary.sent += 1

        if whatsapp_status == "delivered":
            summary.delivered += 1

        if whatsapp_status == "read":
            summary.read += 1

        if status_value == "failed" or whatsapp_status == "failed":
            summary.failed += 1

        if status_value == "no_number":
            summary.missing_phone += 1

        if status_value == "invalid_number":
            summary.invalid_phone += 1

        if status_value == "validation_failed":
            summary.missing_details += 1

        if status_value == "duplicate":
            summary.duplicates += 1

        if status_value == "sent" and (
            whatsapp_status is None or whatsapp_status == "sent"
        ):
            summary.waiting_status += 1

        if is_problem_item(status_value, whatsapp_status):
            summary.problems += 1

    return summary


def build_template_report_item_out(
    item: models.TemplateBatchItem,
    batch_label: str | None,
) -> schemas.TemplateReportItemOut:
    status_value = item.status
    whatsapp_status = item.whatsapp_status

    return schemas.TemplateReportItemOut(
        id=item.id,

        batch_id=item.batch_id,
        batch_label=batch_label,

        operation_date=item.operation_date,
        option_code=item.option_code,
        tour_name=item.tour_name,

        reservation_number=item.reservation_number,
        external_id=item.external_id,

        guest_name=item.guest_name,
        phone=item.phone,

        template_type=item.template_type,
        template_label=get_template_label(item.template_type),

        status=status_value,
        status_label=get_status_label(status_value),

        whatsapp_status=whatsapp_status,
        whatsapp_status_label=get_whatsapp_status_label(whatsapp_status),

        result_label=get_result_label(status_value, whatsapp_status),
        problem_label=get_problem_label(status_value, whatsapp_status),
        reason=item.reason,

        whatsapp_message_id=item.whatsapp_message_id,

        conversation_id=item.conversation_id,
        message_id=item.message_id,

        sent_at=item.created_at,
        whatsapp_status_updated_at=item.whatsapp_status_updated_at,
    )


def get_template_report_items_data(
    db: Session,
    operation_date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    option_code: str | None = None,
    status_filter: str | None = None,
    whatsapp_status: str | None = None,
    problems_only: bool = False,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> schemas.TemplateReportItemsResponse:
    normalized_status = normalize_template_item_status(status_filter)
    normalized_whatsapp_status = normalize_whatsapp_status(whatsapp_status)

    query = (
        db.query(
            models.TemplateBatchItem,
            models.TemplateBatch.batch_label,
        )
        .outerjoin(
            models.TemplateBatch,
            models.TemplateBatch.batch_id == models.TemplateBatchItem.batch_id,
        )
    )

    if operation_date:
        query = query.filter(
            models.TemplateBatchItem.operation_date == operation_date.strip()
        )

    if date_from:
        query = query.filter(
            models.TemplateBatchItem.operation_date >= date_from.strip()
        )

    if date_to:
        query = query.filter(
            models.TemplateBatchItem.operation_date <= date_to.strip()
        )

    if option_code:
        query = query.filter(
            models.TemplateBatchItem.option_code == option_code.strip()
        )

    if normalized_status:
        query = query.filter(models.TemplateBatchItem.status == normalized_status)

    if normalized_whatsapp_status:
        query = query.filter(
            models.TemplateBatchItem.whatsapp_status == normalized_whatsapp_status
        )

    if problems_only:
        query = query.filter(
            or_(
                models.TemplateBatchItem.status.in_(
                    [
                        "failed",
                        "no_number",
                        "invalid_number",
                        "validation_failed",
                    ]
                ),
                models.TemplateBatchItem.whatsapp_status == "failed",
            )
        )

    search_query = q.strip() if q else ""

    if search_query:
        search_pattern = f"%{search_query}%"

        query = query.filter(
            or_(
                models.TemplateBatchItem.batch_id.ilike(search_pattern),
                models.TemplateBatch.batch_label.ilike(search_pattern),
                models.TemplateBatchItem.external_id.ilike(search_pattern),
                models.TemplateBatchItem.reservation_number.ilike(search_pattern),
                models.TemplateBatchItem.guest_name.ilike(search_pattern),
                models.TemplateBatchItem.phone.ilike(search_pattern),
                models.TemplateBatchItem.option_code.ilike(search_pattern),
                models.TemplateBatchItem.tour_name.ilike(search_pattern),
                models.TemplateBatchItem.template_type.ilike(search_pattern),
                models.TemplateBatchItem.reason.ilike(search_pattern),
            )
        )

    all_matching_rows = query.all()
    all_matching_items = [row[0] for row in all_matching_rows]
    summary = build_template_report_summary(all_matching_items)

    paged_rows = (
        query.order_by(models.TemplateBatchItem.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    report_items = [
        build_template_report_item_out(
            item=row[0],
            batch_label=row[1],
        )
        for row in paged_rows
    ]

    return schemas.TemplateReportItemsResponse(
        summary=summary,
        items=report_items,
    )