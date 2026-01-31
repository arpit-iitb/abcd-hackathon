from typing import Any, Dict, List

from app.state import AgentResultBase, ErrorItem
from app.llm_runner import llm_enabled, run_llm_agent
from app.utils.masking import mask_sensitive


def _normalize(value: str) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def run_lead_sourcing(payload: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    lead_filter = (config.get("policy") or {}).get("lead_filter")
    if not lead_filter:
        error = ErrorItem(
            code="missing_config",
            message="policy.lead_filter not found in config",
            where="config.policy.lead_filter",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name="lead_sourcing",
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["Required config missing: policy.lead_filter"],
            evidence=mask_sensitive({"lead": payload}),
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")

    required_fields = ["city", "tier", "product_type", "requested_amount", "loan_purpose"]
    missing_fields = [field for field in required_fields if payload.get(field) in (None, "")]

    tier = _normalize(payload.get("tier", ""))
    city = _normalize(payload.get("city", ""))
    product_type = _normalize(payload.get("product_type", ""))
    requested_amount = payload.get("requested_amount")
    loan_purpose = _normalize(payload.get("loan_purpose", ""))

    allowed_tiers = [
        _normalize(value) for value in lead_filter.get("allowed_tiers", []) if isinstance(value, str)
    ]
    allowed_products = [
        _normalize(value) for value in lead_filter.get("allowed_product_types", []) if isinstance(value, str)
    ]
    allowed_purposes = [
        _normalize(value) for value in lead_filter.get("allowed_loan_purposes", []) if isinstance(value, str)
    ]
    max_requested_amount = lead_filter.get("max_requested_amount")

    calculations = {
        "tier_allowed": tier in allowed_tiers if tier else False,
        "product_type_allowed": product_type in allowed_products if product_type else False,
        "loan_purpose_allowed": loan_purpose in allowed_purposes if loan_purpose else False,
        "amount_within_limit": requested_amount <= max_requested_amount
        if isinstance(requested_amount, (int, float)) and isinstance(max_requested_amount, (int, float))
        else False,
    }

    if missing_fields:
        result = AgentResultBase(
            agent_name="lead_sourcing",
            status="insufficient_data",
            errors=[],
            missing_data=missing_fields,
            rationale_summary=[f"Missing required fields: {', '.join(missing_fields)}"],
            evidence=mask_sensitive(
                {
                    "tier": payload.get("tier"),
                    "city": payload.get("city"),
                    "product_type": payload.get("product_type"),
                    "requested_amount": payload.get("requested_amount"),
                    "loan_purpose": payload.get("loan_purpose"),
                    "aadhaar_last4": payload.get("aadhaar_last4"),
                    "pan_masked": payload.get("pan_masked"),
                }
            ),
            calculations=calculations,
            confidence=0.2,
            output={
                "selected": False,
                "rejection_reasons": ["missing_required_fields"],
                "normalized_lead": {
                    "tier_normalized": tier,
                    "city_normalized": city,
                    "product_type_normalized": product_type,
                    "loan_purpose_normalized": loan_purpose,
                },
            },
        )
        return result.model_dump(mode="json")

    if llm_enabled(config, "lead_sourcing"):
        return run_llm_agent("lead_sourcing", mask_sensitive(payload), config, prompts)

    rejection_reasons: List[str] = []
    if not calculations["tier_allowed"]:
        rejection_reasons.append("tier_not_allowed")
    if not calculations["product_type_allowed"]:
        rejection_reasons.append("product_type_not_allowed")
    if not calculations["loan_purpose_allowed"]:
        rejection_reasons.append("loan_purpose_not_allowed")
    if not calculations["amount_within_limit"]:
        rejection_reasons.append("requested_amount_exceeds_limit")

    selected = len(rejection_reasons) == 0
    rationale_summary = ["Lead passes policy filters."] if selected else [
        f"Rejected due to: {', '.join(rejection_reasons)}"
    ]

    result = AgentResultBase(
        agent_name="lead_sourcing",
        status="ok",
        errors=[],
        missing_data=[],
        rationale_summary=rationale_summary,
        evidence=mask_sensitive(
            {
                "tier": payload.get("tier"),
                "city": payload.get("city"),
                "product_type": payload.get("product_type"),
                "loan_purpose": payload.get("loan_purpose"),
                "requested_amount": payload.get("requested_amount"),
                "aadhaar_last4": payload.get("aadhaar_last4"),
                "pan_masked": payload.get("pan_masked"),
            }
        ),
        calculations=calculations,
        confidence=0.9,
        output={
            "selected": selected,
            "rejection_reasons": rejection_reasons,
            "normalized_lead": {
                "tier_normalized": tier,
                "city_normalized": city,
                "product_type_normalized": product_type,
                "loan_purpose_normalized": loan_purpose,
            },
        },
    )
    return result.model_dump(mode="json")
