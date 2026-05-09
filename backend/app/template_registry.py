from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TemplateDefinition:
    template_type: str
    meta_template_name: str
    language_code: str
    required_fields: tuple[str, ...]
    body_variable_order: tuple[str, ...]


TEMPLATE_REGISTRY: dict[str, TemplateDefinition] = {
    "missing_hotel_details": TemplateDefinition(
        template_type="missing_hotel_details",
        meta_template_name="missing_hotel_details",
        language_code="en",
        required_fields=(
            "external_id",
            "phone",
            "guest_name",
            "reservation_number",
        ),
        body_variable_order=(
            "guest_name",
            "reservation_number",
        ),
    ),

    "pickup_reminder_hotel": TemplateDefinition(
        template_type="pickup_reminder_hotel",
        meta_template_name="pickup_reminder_hotel",
        language_code="en",
        required_fields=(
            "external_id",
            "phone",
            "guest_name",
            "tour_name",
            "reservation_number",
            "cruise_date",
            "pickup_time",
            "pickup_point",
        ),
        body_variable_order=(
            "guest_name",
            "tour_name",
            "reservation_number",
            "cruise_date",
            "pickup_time",
            "pickup_point",
        ),
    ),

    "pickup_reminder_hotel_missing_details": TemplateDefinition(
        template_type="pickup_reminder_hotel_missing_details",
        meta_template_name="pickup_reminder_hotel_missing_details",
        language_code="en",
        required_fields=(
            "external_id",
            "phone",
            "guest_name",
            "tour_name",
            "reservation_number",
            "cruise_date",
            "pickup_time",
            "pickup_point",
            "passenger_info_link",
        ),
        body_variable_order=(
            "guest_name",
            "tour_name",
            "reservation_number",
            "cruise_date",
            "pickup_time",
            "pickup_point",
            "passenger_info_link",
        ),
    ),

    "pickup_reminder_meeting_point": TemplateDefinition(
        template_type="pickup_reminder_meeting_point",
        meta_template_name="pickup_reminder_meeting_point",
        language_code="en",
        required_fields=(
            "external_id",
            "phone",
            "guest_name",
            "tour_name",
            "reservation_number",
            "cruise_date",
            "pickup_time",
            "pickup_point",
            "google_maps",
        ),
        body_variable_order=(
            "guest_name",
            "tour_name",
            "reservation_number",
            "cruise_date",
            "pickup_time",
            "pickup_point",
            "google_maps",
        ),
    ),

    "pickup_reminder_meeting_point_missing_details": TemplateDefinition(
        template_type="pickup_reminder_meeting_point_missing_details",
        meta_template_name="pickup_reminder_meeting_point_missing_details",
        language_code="en",
        required_fields=(
            "external_id",
            "phone",
            "guest_name",
            "tour_name",
            "reservation_number",
            "cruise_date",
            "pickup_time",
            "pickup_point",
            "google_maps",
            "passenger_info_link",
        ),
        body_variable_order=(
            "guest_name",
            "tour_name",
            "reservation_number",
            "cruise_date",
            "pickup_time",
            "pickup_point",
            "google_maps",
            "passenger_info_link",
        ),
    ),

    # Old template. Keep for compatibility while we phase it out.
    "cruise_pickup_reminder": TemplateDefinition(
        template_type="cruise_pickup_reminder",
        meta_template_name="cruise_pickup_reminder",
        language_code="en",
        required_fields=(
            "external_id",
            "phone",
            "guest_name",
            "tour_name",
            "reservation_number",
            "cruise_date",
            "pickup_time",
            "pickup_point",
            "google_maps",
        ),
        body_variable_order=(
            "guest_name",
            "tour_name",
            "reservation_number",
            "cruise_date",
            "pickup_time",
            "pickup_point",
            "google_maps",
        ),
    ),

    # Manual Sendro template. Not expected from Giannis / CRM for now.
    "post_call_followup_request": TemplateDefinition(
        template_type="post_call_followup_request",
        meta_template_name="post_call_followup_request",
        language_code="en",
        required_fields=(
            "external_id",
            "phone",
            "guest_name",
        ),
        body_variable_order=(
            "guest_name",
        ),
    ),

    # Manual Sendro template for guests with no transfer, meeting directly at Amoudi port.
    "no_transfer_amoudi": TemplateDefinition(
        template_type="no_transfer_amoudi",
        meta_template_name="no_transfer_amoudi",
        language_code="en",
        required_fields=(
            "external_id",
            "phone",
            "guest_name",
            "reservation_number",
            "pickup_time",
            "cruise_date",
        ),
        body_variable_order=(
            "guest_name",
            "reservation_number",
            "pickup_time",
            "cruise_date",
        ),
    ),

    # Manual Sendro template for sailing cruise transfer driver delay notices.
    "driver_delay_sailing_cruise": TemplateDefinition(
        template_type="driver_delay_sailing_cruise",
        meta_template_name="driver_delay_sailing_cruise",
        language_code="en",
        required_fields=(
            "external_id",
            "phone",
            "guest_name",
            "delay_minutes",
        ),
        body_variable_order=(
            "guest_name",
            "delay_minutes",
        ),
    ),
}


def get_template_definition(template_type: str) -> TemplateDefinition:
    template = TEMPLATE_REGISTRY.get(template_type)

    if template is None:
        allowed = ", ".join(sorted(TEMPLATE_REGISTRY.keys()))
        raise KeyError(f"Unknown template_type '{template_type}'. Allowed: {allowed}")

    return template


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def missing_required_fields(template_type: str, item_data: dict[str, Any]) -> list[str]:
    template = get_template_definition(template_type)

    return [
        field_name
        for field_name in template.required_fields
        if _is_empty(item_data.get(field_name))
    ]


def build_template_variables(template_type: str, item_data: dict[str, Any]) -> list[str]:
    template = get_template_definition(template_type)

    return [
        str(item_data.get(field_name, "")).strip()
        for field_name in template.body_variable_order
    ]