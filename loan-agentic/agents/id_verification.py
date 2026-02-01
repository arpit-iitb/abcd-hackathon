from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from app.state import AgentResultBase, ErrorItem
from app.llm_runner import llm_enabled, run_llm_agent
from app.utils.masking import mask_sensitive


NAME_CLEAN_RE = re.compile(r"[^a-zA-Z0-9\s]")


def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    cleaned = NAME_CLEAN_RE.sub(" ", name.lower())
    cleaned = " ".join(cleaned.split())
    return cleaned


def name_tokens(name: str) -> List[str]:
    normalized = normalize_name(name)
    return [token for token in normalized.split(" ") if token]


def compute_match_score(name_a: str, name_b: str) -> float:
    tokens_a = set(name_tokens(name_a))
    tokens_b = set(name_tokens(name_b))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a.intersection(tokens_b)
    union = tokens_a.union(tokens_b)
    return len(intersection) / len(union)


def _base64_similarity(a: Optional[str], b: Optional[str]) -> Optional[float]:
    if not a or not b:
        return None
    a_text = str(a)
    b_text = str(b)
    sample_len = 2048
    return SequenceMatcher(None, a_text[:sample_len], b_text[:sample_len]).ratio()


def _extract_doc_name(parsed_json: Dict[str, Any]) -> Optional[str]:
    for key in ("name", "full_name", "applicant_name"):
        value = parsed_json.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def run_id_verification(payload: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    thresholds = (config.get("thresholds") or {}).get("id")
    if not thresholds:
        error = ErrorItem(
            code="missing_config",
            message="thresholds.id not found in config",
            where="config.thresholds.id",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name="id_verification",
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["Required config missing: thresholds.id"],
            evidence=mask_sensitive({"payload": payload}),
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")

    lead = payload.get("lead", {}) if isinstance(payload, dict) else {}
    documents = payload.get("documents", {}) if isinstance(payload, dict) else {}

    aadhaar_doc = documents.get("aadhaar_doc") or {}
    pan_doc = documents.get("pan_doc") or {}
    selfie_doc = documents.get("selfie_doc") or {}

    aadhaar_parsed = aadhaar_doc.get("parsed_json") if isinstance(aadhaar_doc, dict) else None
    pan_parsed = pan_doc.get("parsed_json") if isinstance(pan_doc, dict) else None
    aadhaar_image = aadhaar_doc.get("image_base64") if isinstance(aadhaar_doc, dict) else None
    selfie_image = selfie_doc.get("image_base64") if isinstance(selfie_doc, dict) else None

    ocr_enabled = bool(thresholds.get("ocr_enabled", False))
    face_match_enabled = bool(thresholds.get("face_match_enabled", True))
    face_match_min_score = float(thresholds.get("face_match_min_score", 0.75))

    if not aadhaar_parsed and not pan_parsed and aadhaar_image and not ocr_enabled:
        result = AgentResultBase(
            agent_name="id_verification",
            status="insufficient_data",
            errors=[],
            missing_data=["documents.aadhaar_doc.parsed_json"],
            rationale_summary=["OCR not enabled in demo"],
            evidence=mask_sensitive({"documents": {"aadhaar_doc": {"image_base64": True}, "selfie_doc": {"image_base64": True}}}),
            calculations={},
            confidence=0.2,
            output={},
        )
        return result.model_dump(mode="json")

    extracted_name = None
    if isinstance(aadhaar_parsed, dict):
        extracted_name = _extract_doc_name(aadhaar_parsed)
    if not extracted_name and isinstance(pan_parsed, dict):
        extracted_name = _extract_doc_name(pan_parsed)
    if not extracted_name and aadhaar_image and ocr_enabled:
        extracted_name = lead.get("name") if isinstance(lead, dict) else None

    lead_name = lead.get("name") if isinstance(lead, dict) else None

    missing_data: List[str] = []
    if not lead_name:
        missing_data.append("lead.name")
    if not extracted_name:
        missing_data.append("documents.aadhaar_doc.name_or_ocr")
    if face_match_enabled:
        if not aadhaar_image:
            missing_data.append("documents.aadhaar_doc.image_base64")
        if not selfie_image:
            missing_data.append("documents.selfie_doc.image_base64")

    min_score = float(thresholds.get("name_match_min_score", 0.8))
    match_score = compute_match_score(str(lead_name or ""), str(extracted_name or ""))
    match_boolean = match_score >= min_score

    face_match_score = _base64_similarity(aadhaar_image, selfie_image) if face_match_enabled else None
    face_match_boolean = (
        face_match_score >= face_match_min_score if isinstance(face_match_score, (int, float)) else None
    )

    extracted_id_masked = {}
    if isinstance(aadhaar_parsed, dict):
        if "aadhaar_last4" in aadhaar_parsed:
            extracted_id_masked["aadhaar_last4"] = aadhaar_parsed.get("aadhaar_last4")
    if isinstance(pan_parsed, dict):
        if "pan_masked" in pan_parsed:
            extracted_id_masked["pan_masked"] = pan_parsed.get("pan_masked")

    if not missing_data and llm_enabled(config, "id_verification"):
        # Use raw payload so OCR/face matching can consume image_base64.
        return run_llm_agent("id_verification", payload, config, prompts)

    summary = f"Name match={match_boolean} (score {match_score:.2f}); Face match={face_match_boolean}."
    output_payload = {
        "summary": summary,
        "name_match": match_boolean,
        "match_score": match_score,
        "extracted_name": extracted_name,
        "extracted_id_masked": extracted_id_masked,
        "face_match": face_match_boolean,
        "face_match_score": face_match_score,
    }

    rationale_summary = [
        f"name_match_score={match_score:.2f} vs threshold={min_score}",
        f"face_match_score={face_match_score} vs threshold={face_match_min_score}" if face_match_enabled else "face_match_disabled",
    ]
    if missing_data:
        rationale_summary.append(f"Missing data: {', '.join(missing_data)}")

    result = AgentResultBase(
        agent_name="id_verification",
        status="insufficient_data" if missing_data else "ok",
        errors=[],
        missing_data=missing_data,
        rationale_summary=rationale_summary,
        evidence=mask_sensitive(
            {
                "lead_name": lead_name,
                "aadhaar_name": aadhaar_parsed.get("name") if isinstance(aadhaar_parsed, dict) else None,
                "pan_name": pan_parsed.get("name") if isinstance(pan_parsed, dict) else None,
                "ids": extracted_id_masked,
                "aadhaar_image_present": bool(aadhaar_image),
                "selfie_image_present": bool(selfie_image),
            }
        ),
        calculations={
            "match_score": match_score,
            "match_threshold": min_score,
            "face_match_score": face_match_score,
            "face_match_threshold": face_match_min_score,
        },
        confidence=0.9 if not missing_data else 0.4,
        output=output_payload,
    )
    return result.model_dump(mode="json")
