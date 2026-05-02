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
    "pickup_reminder_meeting_point": TemplateDefinition(
        template_type="pickup_reminder_meeting_point",
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
    "pickup_reminder_passenger_info": TemplateDefinition(
        template_type="pickup_reminder_passenger_info",
        meta_template_name="pickup_reminder_passenger_info",
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