from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.state import AgentResultBase, ErrorItem
from app.utils.masking import mask_sensitive
from app.llm_runner import llm_enabled, run_llm_agent


def _income_diff_ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    if a <= 0 or b <= 0:
        return None
    return abs(a - b) / max(a, b)


def _get_output(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    return result.get("output", {}) if isinstance(result.get("output"), dict) else {}


def run_fraud(payload: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    fraud_cfg = (config.get("thresholds") or {}).get("fraud")
    if not fraud_cfg:
        error = ErrorItem(
            code="missing_config",
            message="thresholds.fraud not found in config",
            where="config.thresholds.fraud",
            severity="fatal",
        )
        result = AgentResultBase(
            agent_name="fraud",
            status="error",
            errors=[error],
            missing_data=[],
            rationale_summary=["Required config missing: thresholds.fraud"],
            evidence=mask_sensitive({"payload": payload}),
            calculations={},
            confidence=0.0,
            output={},
        )
        return result.model_dump(mode="json")

    bank_result = payload.get("bank_statement") or {}
    payslip_result = payload.get("payslip") or {}
    id_result = payload.get("id_verification") or {}
    bureau_result = payload.get("bureau") or {}

    bank_output = _get_output(bank_result)
    payslip_output = _get_output(payslip_result)
    id_output = _get_output(id_result)
    bureau_output = _get_output(bureau_result)

    bank_salary = bank_output.get("salary_estimate")
    payslip_income = payslip_output.get("monthly_income_estimate")
    name_match = id_output.get("name_match")

    missing_data: List[str] = []
    if bank_salary is None:
        missing_data.append("bank_statement.salary_estimate")
    if payslip_income is None:
        missing_data.append("payslip.monthly_income_estimate")
    if name_match is None:
        missing_data.append("id_verification.name_match")
    if bureau_output.get("enquiry_summary") is None:
        missing_data.append("bureau.enquiry_summary")

    if missing_data:
        result = AgentResultBase(
            agent_name="fraud",
            status="insufficient_data",
            errors=[],
            missing_data=missing_data,
            rationale_summary=[f"Missing data: {', '.join(missing_data)}"],
            evidence=mask_sensitive({"bank_statement": bank_output, "payslip": payslip_output, "id_verification": id_output, "bureau": bureau_output}),
            calculations={},
            confidence=0.4,
            output={},
        )
        return result.model_dump(mode="json")

    if llm_enabled(config, "fraud"):
        return run_llm_agent("fraud", mask_sensitive(payload), config, prompts)

    tolerance = float(fraud_cfg.get("income_tolerance_ratio", 0.2))
    low_score = float(fraud_cfg.get("name_match_low_score", 0.5))
    diff_ratio = _income_diff_ratio(bank_salary, payslip_income)

    suspicious_grade = bank_output.get("suspicious", {}).get("suspicious_grade")
    desperate_flag = bureau_output.get("enquiry_summary", {}).get("desperate_flag")
    match_score = id_output.get("match_score")

    signals: List[Dict[str, Any]] = []
    fraud_grade = "good"

    if diff_ratio is not None and diff_ratio > tolerance:
        signals.append(
            {
                "signal_name": "income_mismatch",
                "severity": "medium",
                "evidence_fields": ["bank_statement.salary_estimate", "payslip.monthly_income_estimate"],
            }
        )
        fraud_grade = "suspicious"

    if name_match is False:
        severity = "medium"
        if isinstance(match_score, (int, float)) and match_score < low_score:
            severity = "high"
            fraud_grade = "fraudulent"
        signals.append(
            {"signal_name": "name_mismatch", "severity": severity, "evidence_fields": ["id_verification.name_match"]}
        )
        if fraud_grade != "fraudulent":
            fraud_grade = "suspicious"

    if desperate_flag:
        signals.append(
            {"signal_name": "high_enquiry_desperation", "severity": "medium", "evidence_fields": ["bureau.enquiry_summary"]}
        )
        if fraud_grade == "good":
            fraud_grade = "suspicious"

    if str(suspicious_grade).lower() == "high":
        signals.append(
            {
                "signal_name": "high_suspicious_spend",
                "severity": "medium",
                "evidence_fields": ["bank_statement.suspicious.suspicious_grade"],
            }
        )
        if fraud_grade == "good":
            fraud_grade = "suspicious"

    if diff_ratio is not None and diff_ratio > tolerance and desperate_flag and str(suspicious_grade).lower() == "high":
        fraud_grade = "fraudulent"

    output_payload = {
        "fraud_grade": fraud_grade,
        "signals": signals,
        "income_crosscheck": {
            "bank_salary": bank_salary,
            "payslip_income": payslip_income,
            "diff_ratio": diff_ratio,
        },
        "web_search": {"enabled": False, "queries": [], "results_summary": "web_search_skipped"},
    }

    rationale_summary = [f"fraud_grade={fraud_grade}"]
    if diff_ratio is not None:
        rationale_summary.append(f"income_diff_ratio={diff_ratio:.2f} (tolerance={tolerance})")

    result = AgentResultBase(
        agent_name="fraud",
        status="ok",
        errors=[],
        missing_data=[],
        rationale_summary=rationale_summary,
        evidence=mask_sensitive(
            {
                "bank_salary": bank_salary,
                "payslip_income": payslip_income,
                "name_match": name_match,
                "match_score": match_score,
            }
        ),
        calculations={"diff_ratio": diff_ratio, "tolerance": tolerance, "name_match_low_score": low_score},
        confidence=0.7,
        output=output_payload,
    )
    return result.model_dump(mode="json")
