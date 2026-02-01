from __future__ import annotations

from typing import Any, Dict, List

from app.state import AgentResultBase, ErrorItem
from app.llm_runner import llm_enabled, run_llm_agent
from app.utils.masking import mask_sensitive


def run_payslip(payload: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    payslip_cfg = (config.get("thresholds") or {}).get("payslip", {})
    ocr_enabled = bool(payslip_cfg.get("ocr_enabled", False))

    documents = payload.get("documents", {}) if isinstance(payload, dict) else {}
    payslip_doc = documents.get("payslip_doc") or {}
    parsed = payslip_doc.get("parsed_json") if isinstance(payslip_doc, dict) else None

    if not parsed:
        if payslip_doc.get("image_base64") and not ocr_enabled:
            result = AgentResultBase(
                agent_name="payslip",
                status="insufficient_data",
                errors=[],
                missing_data=["documents.payslip_doc.parsed_json"],
                rationale_summary=["OCR not enabled in demo"],
                evidence=mask_sensitive({"payslip_doc": payslip_doc}),
                calculations={},
                confidence=0.2,
                output={},
            )
            return result.model_dump(mode="json")
        if payslip_doc.get("image_base64") and ocr_enabled:
            error = ErrorItem(
                code="ocr_not_implemented",
                message="OCR enabled but not implemented in demo",
                where="documents.payslip_doc.image_base64",
                severity="fatal",
            )
            result = AgentResultBase(
                agent_name="payslip",
                status="error",
                errors=[error],
                missing_data=[],
                rationale_summary=["OCR enabled but not implemented"],
                evidence=mask_sensitive({"payslip_doc": payslip_doc}),
                calculations={},
                confidence=0.0,
                output={},
            )
            return result.model_dump(mode="json")
        missing = ["documents.payslip_doc.parsed_json"]
        result = AgentResultBase(
            agent_name="payslip",
            status="insufficient_data",
            errors=[],
            missing_data=missing,
            rationale_summary=["Payslip parsed_json missing"],
            evidence=mask_sensitive({"payslip_doc": payslip_doc}),
            calculations={},
            confidence=0.3,
            output={},
        )
        return result.model_dump(mode="json")

    employer = parsed.get("employer") or parsed.get("employer_name")
    net_pay = parsed.get("net_pay") or parsed.get("net_salary")
    gross_pay = parsed.get("gross_pay") or parsed.get("gross_salary")
    pay_date = parsed.get("pay_date")

    monthly_income_estimate = None
    if isinstance(net_pay, (int, float)):
        monthly_income_estimate = float(net_pay)
    elif isinstance(gross_pay, (int, float)):
        monthly_income_estimate = float(gross_pay)

    missing_data: List[str] = []
    if monthly_income_estimate is None:
        missing_data.append("payslip.net_pay")

    output_payload = {
        "monthly_income_estimate": monthly_income_estimate,
        "pay_date": pay_date,
        "employer": employer,
    }

    rationale_summary = [
        "Parsed payslip_doc.parsed_json",
        f"monthly_income_estimate={monthly_income_estimate}",
    ]
    if missing_data:
        rationale_summary.append(f"Missing data: {', '.join(missing_data)}")

    result = AgentResultBase(
        agent_name="payslip",
        status="insufficient_data" if missing_data else "ok",
        errors=[],
        missing_data=missing_data,
        rationale_summary=rationale_summary,
        evidence=mask_sensitive({"payslip": parsed}),
        calculations={},
        confidence=0.9 if not missing_data else 0.4,
        output=output_payload,
    )
    rule_result = result.model_dump(mode="json")

    if not missing_data and llm_enabled(config, "payslip"):
        llm_result = run_llm_agent("payslip", mask_sensitive(payload), config, prompts)
        if isinstance(llm_result, dict) and llm_result.get("status") == "ok":
            return llm_result
        if isinstance(llm_result, dict) and llm_result.get("errors"):
            rule_result.setdefault("errors", []).append(
                {
                    "code": "llm_fallback",
                    "message": "LLM parse/validation failed; returning rule-based payslip result.",
                    "where": "payslip.llm",
                    "severity": "warning",
                }
            )
            rule_result["rationale_summary"] = list(rule_result.get("rationale_summary", [])) + [
                "LLM output invalid; used rule-based parsed_json."
            ]
    return rule_result
