import re
from typing import Any, Dict

PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)
AADHAAR_PATTERN = re.compile(r"\b[0-9]{12}\b")
EMAIL_PATTERN = re.compile(r"\b([A-Z0-9._%+-]+)@([A-Z0-9.-]+\.[A-Z]{2,})\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"\b(?:\+?\d[\d\-\s]{7,}\d)\b")


def mask_pan(value: str) -> str:
    if not value:
        return value
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value)
    if len(cleaned) < 4:
        return "XXXX"
    return f"XXXXXX{cleaned[-4:]}"


def mask_aadhaar(value: str) -> str:
    if not value:
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        return "********"
    return f"********{digits[-4:]}"


def mask_phone(value: str) -> str:
    if not value:
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        return "****"
    return f"{'*' * max(0, len(digits) - 4)}{digits[-4:]}"


def mask_email(value: str) -> str:
    if not value:
        return value
    parts = value.split("@")
    if len(parts) != 2:
        return "***"
    local, domain = parts
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def mask_sensitive(obj: Any) -> Any:
    if isinstance(obj, dict):
        masked: Dict[str, Any] = {}
        for key, value in obj.items():
            key_lower = str(key).lower()
            if "pan" in key_lower and isinstance(value, str):
                masked[key] = mask_pan(value)
            elif "aadhaar" in key_lower and isinstance(value, str):
                masked[key] = mask_aadhaar(value)
            elif "image_base64" in key_lower or "selfie" in key_lower or "photo" in key_lower:
                masked[key] = "<redacted_image_base64>"
            elif "image_path" in key_lower or "image_file" in key_lower:
                masked[key] = "<redacted_image_path>"
            elif "phone" in key_lower and isinstance(value, str):
                masked[key] = mask_phone(value)
            elif "email" in key_lower and isinstance(value, str):
                masked[key] = mask_email(value)
            else:
                masked[key] = mask_sensitive(value)
        return masked
    if isinstance(obj, list):
        return [mask_sensitive(item) for item in obj]
    if isinstance(obj, str):
        obj = PAN_PATTERN.sub(lambda m: mask_pan(m.group(0)), obj)
        obj = AADHAAR_PATTERN.sub(lambda m: mask_aadhaar(m.group(0)), obj)
        obj = EMAIL_PATTERN.sub(lambda m: mask_email(m.group(0)), obj)
        obj = PHONE_PATTERN.sub(lambda m: mask_phone(m.group(0)), obj)
        return obj
    return obj
