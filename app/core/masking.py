import re
from typing import Any, Dict, List

PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)
AADHAAR_PATTERN = re.compile(r"\b[0-9]{12}\b")


def mask_pan(value: str) -> str:
    if not value:
        return value
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value)
    if len(cleaned) < 4:
        return "****"
    return f"XXXXXX{cleaned[-4:]}"


def mask_aadhaar(value: str) -> str:
    if not value:
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        return "********"
    return f"********{digits[-4:]}"


def mask_in_text(text: str) -> str:
    if not isinstance(text, str):
        return text
    text = PAN_PATTERN.sub(lambda m: mask_pan(m.group(0)), text)
    text = AADHAAR_PATTERN.sub(lambda m: mask_aadhaar(m.group(0)), text)
    return text


def mask_sensitive(obj: Any) -> Any:
    if isinstance(obj, dict):
        masked: Dict[str, Any] = {}
        for key, value in obj.items():
            key_lower = str(key).lower()
            if "pan" in key_lower and isinstance(value, str):
                masked[key] = mask_pan(value)
            elif "aadhaar" in key_lower and isinstance(value, str):
                masked[key] = mask_aadhaar(value)
            else:
                masked[key] = mask_sensitive(value)
        return masked
    if isinstance(obj, list):
        return [mask_sensitive(item) for item in obj]
    if isinstance(obj, str):
        return mask_in_text(obj)
    return obj
