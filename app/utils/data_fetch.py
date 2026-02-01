from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from app.json_utils import load_json
from app.utils.masking import mask_aadhaar, mask_pan
from app.utils.image_utils import load_image_base64


DEFAULT_API_ENDPOINTS = {
    "lead_sourcing": "https://asterisk0007.pythonanywhere.com/lead-sourcing",
    "bureau": "https://asterisk0007.pythonanywhere.com/bureau",
    "bank_statement": "https://asterisk0007.pythonanywhere.com/bank-statement",
}


def _post_json(url: str, payload: Dict[str, Any], timeout_sec: int = 8) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def _load_image_base64_from_url(url: str, timeout_sec: int = 8, max_dim: int = 512, quality: int = 60) -> str:
    if not url:
        return ""
    with urllib.request.urlopen(url, timeout=timeout_sec) as resp:
        data = resp.read()
    with Image.open(BytesIO(data)) as img:
        img = img.convert("RGB")
        img.thumbnail((max_dim, max_dim))
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")


def _api_config(config: Dict[str, Any]) -> Tuple[bool, Dict[str, str], int]:
    api_cfg = config.get("api", {}) if isinstance(config, dict) else {}
    enabled = bool(api_cfg.get("enabled", False))
    endpoints = api_cfg.get("endpoints") or DEFAULT_API_ENDPOINTS
    timeout_sec = int(api_cfg.get("timeout_sec", 8))
    return enabled, endpoints, timeout_sec


def _select_sample(payload: Any, sample_id: Optional[str]) -> Dict[str, Any]:
    if isinstance(payload, list):
        if sample_id is None and payload:
            return payload[0]
        for item in payload:
            if item.get("lead_id") == sample_id:
                return item
        return payload[0] if payload else {}
    return payload or {}


def _normalize_city(city: str) -> str:
    return city.strip().lower()


def _tier_from_city(config: Dict[str, Any], city: str) -> Optional[str]:
    policy = config.get("policy", {}) if isinstance(config, dict) else {}
    mapping = policy.get("city_tier_map") if isinstance(policy, dict) else None
    if not isinstance(mapping, dict):
        return None
    return mapping.get(_normalize_city(city))


def _merge_lead(
    local_lead: Dict[str, Any],
    api_lead: Dict[str, Any],
    config: Dict[str, Any],
    fallbacks: List[str],
) -> Tuple[Dict[str, Any], Optional[str], Optional[str], Optional[str]]:
    lead = dict(local_lead or {})
    applicant = api_lead.get("applicant") or {}
    if applicant.get("name"):
        lead["name"] = applicant.get("name")
    city = applicant.get("city")
    if city:
        lead["city"] = city
        tier_from_city = _tier_from_city(config, str(city))
        if tier_from_city:
            lead["tier"] = tier_from_city
        elif lead.get("tier"):
            fallbacks.append("City tier mapping missing; used local tier.")
    if applicant.get("loan_requested_amount"):
        lead["requested_amount"] = applicant.get("loan_requested_amount")
    if applicant.get("pan_no"):
        lead["pan_masked"] = mask_pan(str(applicant.get("pan_no")))
    if applicant.get("aadhar_no"):
        lead["aadhaar_last4"] = mask_aadhaar(str(applicant.get("aadhar_no")))[-4:]

    account_number = applicant.get("account_number")
    pan_no = applicant.get("pan_no")
    employer = applicant.get("employer")
    return lead, account_number, pan_no, employer


def _extract_pdf_text(data: bytes, max_chars: int = 8000) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("pypdf_not_available") from exc
    reader = PdfReader(BytesIO(data))
    texts: List[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text:
            texts.append(text)
        if sum(len(t) for t in texts) >= max_chars:
            break
    combined = "\n".join(texts)
    return combined[:max_chars]


def _load_pdf_text_from_url(url: str, timeout_sec: int = 8) -> str:
    if not url:
        return ""
    with urllib.request.urlopen(url, timeout=timeout_sec) as resp:
        data = resp.read()
    return _extract_pdf_text(data)


def build_lead_with_fallback(
    lead: Dict[str, Any], config: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[str], Dict[str, Any]]:
    fallbacks: List[str] = []
    assets: Dict[str, Any] = {"selfie_base64": "", "company": ""}
    if not isinstance(lead, dict):
        return lead, ["Invalid lead payload; used local lead JSON."], assets

    enabled, endpoints, timeout_sec = _api_config(config)
    if enabled and lead.get("lead_id"):
        try:
            api_lead = _post_json(
                endpoints["lead_sourcing"],
                {"lead_id": lead.get("lead_id")},
                timeout_sec=timeout_sec,
            )
            merged, _, _, employer = _merge_lead(lead, api_lead, config, fallbacks)
            docs = api_lead.get("documents") or {}
            selfie_url = docs.get("selfie_image")
            if employer:
                assets["company"] = employer
            elif lead.get("lead_id"):
                fallbacks.append("Employer missing in API response; used local company.")
            if selfie_url:
                try:
                    assets["selfie_base64"] = _load_image_base64_from_url(
                        selfie_url, timeout_sec=timeout_sec
                    )
                except Exception as exc:
                    fallbacks.append(f"Selfie image API failed ({exc}); used local image.")
            return merged, fallbacks, assets
        except Exception as exc:
            fallbacks.append(f"Lead API failed ({exc}); used local lead JSON.")
    return lead, fallbacks, assets


def build_application_payload_with_fallback(
    sample_dir: str,
    sample_id: Optional[str],
    config: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    lead_payload = load_json(f"{sample_dir}/lead_samples.json")
    bureau_payload = load_json(f"{sample_dir}/bureau_samples.json")
    bank_payload = load_json(f"{sample_dir}/bank_statement_samples.json")
    id_docs_payload = load_json(f"{sample_dir}/id_docs_samples.json")
    payslip_payload = load_json(f"{sample_dir}/payslip_samples.json")

    lead_sample = _select_sample(lead_payload, sample_id)
    bureau_sample = _select_sample(bureau_payload, sample_id)
    bank_sample = _select_sample(bank_payload, sample_id)
    id_docs_sample = _select_sample(id_docs_payload, sample_id)
    payslip_sample = _select_sample(payslip_payload, sample_id)

    fallbacks: List[str] = []
    account_number: Optional[str] = None
    pan_no: Optional[str] = None

    enabled, endpoints, timeout_sec = _api_config(config)

    lead = lead_sample
    api_documents: Dict[str, Any] = {}
    if enabled and lead_sample.get("lead_id"):
        try:
            api_lead = _post_json(
                endpoints["lead_sourcing"],
                {"lead_id": lead_sample.get("lead_id")},
                timeout_sec=timeout_sec,
            )
            lead, account_number, pan_no, _ = _merge_lead(lead_sample, api_lead, config, fallbacks)
            api_documents = api_lead.get("documents") or {}
        except Exception as exc:
            fallbacks.append(f"Lead API failed ({exc}); used local lead JSON.")

    bureau_report = {
        "raw": bureau_sample.get("raw", bureau_sample),
        "normalized": bureau_sample.get("normalized"),
    }
    if enabled and pan_no and lead.get("name"):
        try:
            bureau_api = _post_json(
                endpoints["bureau"],
                {"name": lead.get("name"), "pan": pan_no},
                timeout_sec=timeout_sec,
            )
            bureau_report = {
                "raw": bureau_api.get("raw", bureau_api),
                "normalized": bureau_api.get("normalized"),
            }
        except Exception as exc:
            fallbacks.append(f"Bureau API failed ({exc}); used local bureau JSON.")
    else:
        if enabled:
            fallbacks.append("Bureau API skipped (missing name/pan); used local bureau JSON.")

    bank_statement = bank_sample.get("transactions", bank_sample)
    if enabled and account_number:
        try:
            bank_api = _post_json(
                endpoints["bank_statement"],
                {"account_number": account_number},
                timeout_sec=timeout_sec,
            )
            bank_statement = bank_api.get("transactions", bank_api)
        except Exception as exc:
            fallbacks.append(f"Bank-statement API failed ({exc}); used local bank JSON.")
    else:
        if enabled:
            fallbacks.append("Bank-statement API skipped (missing account number); used local bank JSON.")

    aadhaar_path = id_docs_sample.get("aadhaar_image_file") or (id_docs_sample.get("aadhaar_doc") or {}).get("image_path")
    selfie_path = id_docs_sample.get("selfie_image_file") or (id_docs_sample.get("selfie_doc") or {}).get("image_path")

    aadhaar_base64 = ""
    selfie_base64 = ""
    aadhaar_url = api_documents.get("aadhar_image") or api_documents.get("aadhaar_image")
    selfie_url = api_documents.get("selfie_image")
    payslip_url = api_documents.get("payslip_pdf")

    if enabled and aadhaar_url:
        try:
            aadhaar_base64 = _load_image_base64_from_url(aadhaar_url, timeout_sec=timeout_sec)
        except Exception as exc:
            fallbacks.append(f"Aadhaar image API failed ({exc}); used local image.")
    elif enabled and api_documents:
        fallbacks.append("Aadhaar image missing in API response; used local image.")

    if enabled and selfie_url:
        try:
            selfie_base64 = _load_image_base64_from_url(selfie_url, timeout_sec=timeout_sec)
        except Exception as exc:
            fallbacks.append(f"Selfie image API failed ({exc}); used local image.")
    elif enabled and api_documents:
        fallbacks.append("Selfie image missing in API response; used local image.")

    if not aadhaar_base64:
        try:
            aadhaar_base64 = load_image_base64(aadhaar_path)
        except Exception as exc:
            fallbacks.append(f"Aadhaar local image failed ({exc}).")
            aadhaar_base64 = ""

    if not selfie_base64:
        try:
            selfie_base64 = load_image_base64(selfie_path)
        except Exception as exc:
            fallbacks.append(f"Selfie local image failed ({exc}).")
            selfie_base64 = ""

    aadhaar_doc = {"image_base64": aadhaar_base64} if aadhaar_base64 else id_docs_sample.get("aadhaar_doc")
    selfie_doc = {"image_base64": selfie_base64} if selfie_base64 else id_docs_sample.get("selfie_doc")

    payslip_doc = (payslip_sample.get("payslip_doc") or {}) if isinstance(payslip_sample, dict) else {}
    fallback_parsed = {}
    if isinstance(payslip_doc, dict):
        fallback_parsed = payslip_doc.get("parsed_json") or {}
    if enabled and payslip_url:
        try:
            payslip_text = _load_pdf_text_from_url(payslip_url, timeout_sec=timeout_sec)
            if payslip_text:
                payslip_doc = {
                    "parsed_json": {
                        "raw_text": payslip_text,
                        "source": "api_pdf",
                        "fallback_parsed": fallback_parsed,
                    }
                }
            else:
                fallbacks.append("Payslip PDF parsed empty; used local payslip JSON.")
        except Exception as exc:
            fallbacks.append(f"Payslip PDF API failed ({exc}); used local payslip JSON.")
    elif enabled and api_documents:
        fallbacks.append("Payslip PDF missing in API response; used local payslip JSON.")

    payload = {
        "lead": lead,
        "bureau_report": bureau_report,
        "bank_statement": bank_statement,
        "documents": {
            "aadhaar_doc": aadhaar_doc,
            "pan_doc": id_docs_sample.get("pan_doc"),
            "selfie_doc": selfie_doc,
            "payslip_doc": payslip_doc or {"parsed_json": payslip_sample},
        },
    }
    return payload, fallbacks
