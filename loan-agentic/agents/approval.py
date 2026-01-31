from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.state import AgentResultBase, ErrorItem
from app.utils.masking import mask_sensitive
from app.llm_runner import llm_enabled, run_llm_agent


def _extract_output(section: Any) -> Dict[str, Any]:
    if isinstance(section, dict) and isinstance(section.get("output"), dict):
        return section.get("output") or {}
    return section if isinstance(section, dict) else {}


def _extract_status(section: Any) -> Optional[str]:
    if isinstance(section, dict):
        return section.get("status")
    return None


def run_approval(payload: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    policy = (config.get("policy") or {}).get("sanction_policy")
    roi_cfg = (config.get("roi") or {}).get("roi_by_risk")
    approval_cfg = (config.get("thresholds") or {}).get("approval", {})

    if not policy:
        error = ErrorItem(
            code="missing_config",
            message="policy.sanction_policy not found in config",
            where="config.policy.sanction_policy",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name="approval",
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["Required config missing: policy.sanction_policy"],
            evidence=mask_sensitive({"payload": payload}),
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")

    if not roi_cfg:
        error = ErrorItem(
            code="missing_config",
            message="roi.roi_by_risk not found in config",
            where="config.roi.roi_by_risk",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name="approval",
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["Required config missing: roi.roi_by_risk"],
            evidence=mask_sensitive({"payload": payload}),
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")

    lead = payload.get("lead", {}) if isinstance(payload, dict) else {}
    bank_section = payload.get("bank_statement", {}) if isinstance(payload, dict) else {}
    risk_section = payload.get("risk_assessment", {}) if isinstance(payload, dict) else {}
    fraud_section = payload.get("fraud", {}) if isinstance(payload, dict) else {}
    lead_sourcing = payload.get("lead_sourcing", {}) if isinstance(payload, dict) else {}

    bank = _extract_output(bank_section)
    risk = _extract_output(risk_section)
    fraud = _extract_output(fraud_section)
    risk_status = _extract_status(risk_section)
    fraud_status = _extract_status(fraud_section)

    missing_data: List[str] = []
    if lead.get("requested_amount") is None:
        missing_data.append("lead.requested_amount")
    if bank.get("avg_balance") is None:
        missing_data.append("bank_statement.avg_balance")
    if risk.get("final_risk_grade") is None:
        missing_data.append("risk_assessment.final_risk_grade")
    if fraud.get("fraud_grade") is None:
        missing_data.append("fraud.fraud_grade")
    if lead_sourcing.get("output", {}).get("selected") is None:
        missing_data.append("lead_sourcing.output.selected")
    if isinstance(risk_section, dict) and ("status" in risk_section or "agent_name" in risk_section):
        if risk_status is None:
            missing_data.append("risk_assessment.status")
    if isinstance(fraud_section, dict) and ("status" in fraud_section or "agent_name" in fraud_section):
        if fraud_status is None:
            missing_data.append("fraud.status")

    if missing_data:
        result = AgentResultBase(
            agent_name="approval",
            status="insufficient_data",
            errors=[],
            missing_data=missing_data,
            rationale_summary=[f"Missing data: {', '.join(missing_data)}"],
            evidence=mask_sensitive({"lead": lead, "bank_statement": bank, "risk_assessment": risk, "fraud": fraud, "lead_sourcing": lead_sourcing}),
            calculations={},
            confidence=0.4,
            output={},
        )
        return result.model_dump(mode="json")

    if llm_enabled(config, "approval"):
        return run_llm_agent("approval", mask_sensitive(payload), config, prompts)

    requested_amount = float(lead.get("requested_amount"))
    avg_balance = float(bank.get("avg_balance"))
    risk_grade = str(risk.get("final_risk_grade", "medium")).lower()
    fraud_grade = str(fraud.get("fraud_grade", "good")).lower()
    selected = bool(lead_sourcing.get("output", {}).get("selected", True))

    reasons: List[str] = []

    if not selected:
        reasons.append("lead_not_selected")
        decision_output = {
            "decision": "rejected",
            "sanctioned_amount": 0.0,
            "roi": None,
            "reasons": reasons,
        }
        result = AgentResultBase(
            agent_name="approval",
            status="ok",
            errors=[],
            missing_data=[],
            rationale_summary=["Lead rejected: not selected by policy"],
            evidence=mask_sensitive({"lead": lead, "lead_sourcing": lead_sourcing}),
            calculations={},
            confidence=0.9,
            output=decision_output,
        )
        return result.model_dump(mode="json")

    if fraud_grade == "fraudulent":
        reasons.append("fraudulent_grade")
        decision_output = {
            "decision": "rejected",
            "sanctioned_amount": 0.0,
            "roi": None,
            "reasons": reasons,
        }
        result = AgentResultBase(
            agent_name="approval",
            status="ok",
            errors=[],
            missing_data=[],
            rationale_summary=["Lead rejected: fraud_grade=fraudulent"],
            evidence=mask_sensitive({"fraud": fraud}),
            calculations={},
            confidence=0.9,
            output=decision_output,
        )
        return result.model_dump(mode="json")

    max_multiplier = float(policy.get("max_multiplier_of_avg_balance", 10.0))
    cap_amount = float(policy.get("cap_amount", requested_amount))
    min_amount = float(policy.get("min_amount", 0.0))

    max_loan_by_balance = max_multiplier * avg_balance
    sanctioned_amount = min(requested_amount, max_loan_by_balance, cap_amount)

    roi_map = roi_cfg or {}
    roi_value = roi_map.get(risk_grade) or roi_map.get("medium")

    calculations = {
        "requested_amount": requested_amount,
        "avg_balance": avg_balance,
        "max_multiplier_of_avg_balance": max_multiplier,
        "max_loan_by_balance": max_loan_by_balance,
        "cap_amount": cap_amount,
        "min_amount": min_amount,
    }

    decision = "approved"
    if sanctioned_amount < min_amount:
        reasons.append("sanction_below_min")
        sanctioned_amount = 0.0
        decision = "rejected"

    if risk_grade == "high" and fraud_grade == "suspicious":
        reasons.append("risk_high_and_fraud_suspicious")
        decision = "rejected"

    human_review_reasons: List[str] = []
    missing_critical: List[str] = []
    critical_fields = approval_cfg.get("critical_fields", [])
    if isinstance(critical_fields, list):
        for field in critical_fields:
            if field == "lead.requested_amount" and lead.get("requested_amount") is None:
                missing_critical.append(field)
            if field == "bank_statement.avg_balance" and bank.get("avg_balance") is None:
                missing_critical.append(field)
            if field == "risk_assessment.final_risk_grade" and risk.get("final_risk_grade") is None:
                missing_critical.append(field)
            if field == "fraud.fraud_grade" and fraud.get("fraud_grade") is None:
                missing_critical.append(field)

    if approval_cfg.get("human_review_if_missing_critical_fields") and missing_critical:
        human_review_reasons.append("missing_critical_fields")

    if approval_cfg.get("human_review_if_fraud_suspicious") and fraud_grade == "suspicious":
        human_review_reasons.append("fraud_suspicious")

    confidence = 0.8 if decision == "approved" else 0.7
    threshold = float(approval_cfg.get("human_review_confidence_threshold", 0.75))
    if decision == "approved" and confidence < threshold:
        human_review_reasons.append("low_confidence")

    base_decision = decision
    human_review = None
    if human_review_reasons:
        decision = "human_review_required"
        human_review = {
            "required": True,
            "reasons": human_review_reasons,
            "missing_info": missing_critical,
            "recommended_action": "approve" if base_decision == "approved" else "request_more_info",
            "recommended_terms": {"sanctioned_amount": sanctioned_amount, "roi": roi_value},
        }

    decision_output = {
        "decision": decision,
        "sanctioned_amount": sanctioned_amount,
        "roi": roi_value,
        "reasons": reasons,
        "human_review": human_review,
    }

    rationale_summary = [f"decision={decision}", f"sanctioned_amount={sanctioned_amount}", f"roi={roi_value}"]
    if human_review_reasons:
        rationale_summary.append(f"human_review_reasons={', '.join(human_review_reasons)}")

    result = AgentResultBase(
        agent_name="approval",
        status="ok",
        errors=[],
        missing_data=[],
        rationale_summary=rationale_summary,
        evidence=mask_sensitive({"lead": lead, "risk": risk, "fraud": fraud}),
        calculations=calculations,
        confidence=confidence,
        output=decision_output,
    )
    return result.model_dump(mode="json")
