import os
import re

import requests


E164_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def is_valid_e164_phone(phone: str | None) -> bool:
    if phone is None:
        return False

    return bool(E164_PHONE_RE.match(phone.strip()))


def normalize_whatsapp_phone_for_meta(phone: str) -> str:
    return phone.strip().replace("+", "").replace(" ", "")


def send_whatsapp_template_message(
    to_phone: str,
    template_name: str,
    language_code: str,
    body_variables: list[str],
) -> dict:
    whatsapp_send_enabled = os.getenv("WHATSAPP_SEND_ENABLED", "true").lower() == "true"

    if not whatsapp_send_enabled:
        print("⚠️ WHATSAPP TEMPLATE SEND DISABLED - message not sent", flush=True)
        return {"status": "disabled"}

    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    api_version = os.getenv("WHATSAPP_API_VERSION", "v25.0")

    if not access_token:
        raise RuntimeError("Missing WHATSAPP_ACCESS_TOKEN")

    if not phone_number_id:
        raise RuntimeError("Missing WHATSAPP_PHONE_NUMBER_ID")

    normalized_phone = normalize_whatsapp_phone_for_meta(to_phone)

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": normalized_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language_code,
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": str(value),
                        }
                        for value in body_variables
                    ],
                }
            ],
        },
    }

    print(" SENDING WHATSAPP TEMPLATE MESSAGE:", flush=True)
    print("URL:", url, flush=True)
    print("To:", normalized_phone, flush=True)
    print("Template:", template_name, flush=True)
    print("Language:", language_code, flush=True)
    print("Variables:", body_variables, flush=True)

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
    except requests.RequestException as exc:
        raise RuntimeError(f"WhatsApp request failed: {exc}") from exc

    if response.status_code >= 400:
        print("❌ WHATSAPP TEMPLATE SEND ERROR:", flush=True)
        print("Status:", response.status_code, flush=True)
        print("Response:", response.text, flush=True)
        print("Payload:", payload, flush=True)

        raise RuntimeError(f"WhatsApp template send failed: {response.text}")

    result = response.json()

    print("✅ WHATSAPP TEMPLATE MESSAGE SENT:", flush=True)
    print(result, flush=True)

    return result