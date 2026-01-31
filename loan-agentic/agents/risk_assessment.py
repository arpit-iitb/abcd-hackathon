from __future__ import annotations

from typing import Any, Dict, List

from app.state import AgentResultBase, ErrorItem
from app.llm_runner import llm_enabled, run_llm_agent
from app.utils.masking import mask_sensitive


GRADE_ORDER = {"low": 0, "medium": 1, "high": 2}
REVERSE_GRADE = {0: "low", 1: "medium", 2: "high"}


def compute_risk_score(score: float, max_score: float) -> float:
    if max_score <= 0:
        return 1.0
    ratio = max(0.0, min(float(score) / float(max_score), 1.0))
    return 1.0 - ratio


def _grade_value(grade: str) -> int:
    return GRADE_ORDER.get(str(grade).lower(), 1)


def _clamp_grade(value: int) -> str:
    return REVERSE_GRADE.get(max(0, min(2, value)), "medium")


def run_risk_assessment(payload: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    thresholds = (config.get("thresholds") or {}).get("bank")
    if not thresholds:
        error = ErrorItem(
            code="missing_config",
            message="thresholds.bank not found in config",
            where="config.thresholds.bank",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name="risk_assessment",
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["Required config missing: thresholds.bank"],
            evidence=mask_sensitive({"payload": payload}),
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")

    bureau = payload.get("bureau", {}) if isinstance(payload, dict) else {}
    bank = payload.get("bank_statement", {}) if isinstance(payload, dict) else {}
    lead = payload.get("lead", {}) if isinstance(payload, dict) else {}

    bureau_grade = bureau.get("bureau_risk_grade")
    avg_balance = bank.get("avg_balance")
    requested_amount = lead.get("requested_amount")

    missing_data: List[str] = []
    if not bureau_grade:
        missing_data.append("bureau.bureau_risk_grade")
    if avg_balance is None:
        missing_data.append("bank_statement.avg_balance")
    if requested_amount is None:
        missing_data.append("lead.requested_amount")

    if missing_data:
        result = AgentResultBase(
            agent_name="risk_assessment",
            status="insufficient_data",
            errors=[],
            missing_data=missing_data,
            rationale_summary=[f"Missing data: {', '.join(missing_data)}"],
            evidence=mask_sensitive({"bureau": bureau, "bank_statement": bank, "lead": lead}),
            calculations={},
            confidence=0.4,
            output={},
        )
        return result.model_dump(mode="json")

    if llm_enabled(config, "risk_assessment"):
        return run_llm_agent("risk_assessment", mask_sensitive(payload), config, prompts)

    suspicious_grade = None
    suspicious = bank.get("suspicious")
    if isinstance(suspicious, dict):
        suspicious_grade = suspicious.get("suspicious_grade")

    requested_amount_value = float(requested_amount)
    avg_balance_value = float(avg_balance)
    medium_mult = float(thresholds.get("request_to_balance_multiplier_medium", 5.0))
    high_mult = float(thresholds.get("request_to_balance_multiplier_high", 10.0))

    baseline_value = _grade_value(str(bureau_grade))
    risk_value = baseline_value
    risk_factors: List[str] = [f"baseline_from_bureau={bureau_grade}"]

    if str(suspicious_grade).lower() == "high":
        risk_value += 1
        risk_factors.append("high_suspicious_spend")

    if avg_balance_value > 0:
        if requested_amount_value > high_mult * avg_balance_value:
            risk_value = max(risk_value, 2)
            risk_factors.append(f"requested_amount_gt_{high_mult}x_avg_balance")
        elif requested_amount_value > medium_mult * avg_balance_value:
            risk_value = min(2, risk_value + 1)
            risk_factors.append(f"requested_amount_gt_{medium_mult}x_avg_balance")

    final_grade = _clamp_grade(risk_value)

    calculations = {
        "baseline_grade": bureau_grade,
        "baseline_value": baseline_value,
        "requested_amount": requested_amount_value,
        "avg_balance": avg_balance_value,
        "medium_multiplier": medium_mult,
        "high_multiplier": high_mult,
        "suspicious_grade": suspicious_grade,
        "final_value": risk_value,
    }

    result = AgentResultBase(
        agent_name="risk_assessment",
        status="ok",
        errors=[],
        missing_data=[],
        rationale_summary=risk_factors,
        evidence=mask_sensitive({"bureau": bureau, "bank_statement": bank, "lead": lead}),
        calculations=calculations,
        confidence=0.7,
        output={"final_risk_grade": final_grade, "risk_factors": risk_factors, "calculations": calculations},
    )
    return result.model_dump(mode="json")
