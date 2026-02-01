from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.state import AgentResultBase, ErrorItem
from app.utils.masking import mask_sensitive
from app.llm_runner import llm_enabled, run_llm_agent
from agents.web_search import run_web_search_agent


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
    lead = payload.get("lead", {}) if isinstance(payload, dict) else {}
    employer = payslip_output.get("employer") or payslip_output.get("employer_name") or ""

    bank_salary = bank_output.get("salary_estimate")
    payslip_income = payslip_output.get("monthly_income_estimate")
    name_match = id_output.get("name_match")
    face_match_label = id_output.get("face_match")

    web_search_result = {}
    web_cfg = config.get("web_search") or {}
    if face_match_label == "Not Sure" and bool(web_cfg.get("enabled", False)):
        web_payload = {"lead": lead, "employer": employer}
        web_search_result = run_web_search_agent(web_payload, config, prompts)
    elif bool(web_cfg.get("enabled", False)):
        web_search_result = {
            "agent_name": "web_search",
            "status": "ok",
            "errors": [],
            "missing_data": [],
            "rationale_summary": ["Web search not triggered (face match confident)."],
            "evidence": {},
            "calculations": {},
            "confidence": 0.3,
            "output": {
                "summary": "Web search not triggered (face match confident).",
                "applicant_profile": "Not searched.",
                "employer_profile": "Not searched.",
                "confidence_applicant": "low",
                "confidence_employer": "low",
                "sources": [],
            },
        }
    web_output = _get_output(web_search_result)

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
            evidence=mask_sensitive(
                {
                    "bank_statement": bank_output,
                    "payslip": payslip_output,
                    "id_verification": id_output,
                    "bureau": bureau_output,
                    "web_search": web_output,
                }
            ),
            calculations={},
            confidence=0.4,
            output={"web_search": web_output} if web_output else {},
        )
        return result.model_dump(mode="json")

    if llm_enabled(config, "fraud"):
        llm_payload = dict(payload)
        llm_payload["web_search"] = web_search_result
        llm_result = run_llm_agent("fraud", mask_sensitive(llm_payload), config, prompts)
        if isinstance(llm_result, dict) and llm_result.get("status") == "ok":
            output_block = llm_result.get("output", {})
            if isinstance(output_block, dict) and "web_search" not in output_block:
                output_block["web_search"] = web_output or {}
                llm_result["output"] = output_block
        return llm_result

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

    summary = f"Fraud grade: {fraud_grade}. Income mismatch ratio={diff_ratio:.2f}." if diff_ratio is not None else f"Fraud grade: {fraud_grade}."
    output_payload = {
        "summary": summary,
        "fraud_grade": fraud_grade,
        "signals": signals,
        "income_crosscheck": {
            "bank_salary": bank_salary,
            "payslip_income": payslip_income,
            "diff_ratio": diff_ratio,
        },
        "web_search": web_output or {"summary": "web_search_not_run"},
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
                "web_search_summary": web_output.get("summary") if isinstance(web_output, dict) else None,
                "web_search_confidence_applicant": web_output.get("confidence_applicant") if isinstance(web_output, dict) else None,
                "web_search_confidence_employer": web_output.get("confidence_employer") if isinstance(web_output, dict) else None,
            }
        ),
        calculations={"diff_ratio": diff_ratio, "tolerance": tolerance, "name_match_low_score": low_score},
        confidence=0.7,
        output=output_payload,
    )
    return result.model_dump(mode="json")
