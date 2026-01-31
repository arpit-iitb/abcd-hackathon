from typing import Any, Dict, List

from .core.logging import get_logger, log_event
from .core.masking import mask_sensitive
from .core.metrics import compute_dti, compute_emi, compute_foir, normalized, weighted_score
from .core.models import (
    ApprovalOutput,
    FraudOutput,
    LeadInput,
    LeadSourcingOutput,
    RiskOutput,
    SalesAgentOutput,
)
from .core.validation import validate_model


logger = get_logger()


def _missing_fields(data: Dict[str, Any], required: List[str]) -> List[str]:
    missing = []
    for field in required:
        if field not in data or data[field] in (None, ""):
            missing.append(field)
    return missing


def _confidence(missing: List[str], required: List[str]) -> float:
    if not required:
        return 0.0
    return max(0.0, (len(required) - len(missing)) / len(required))


def lead_sourcing_agent(state: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    lead_data = state.get("input", {}).get("lead", {})

    parsed, errors = validate_model(LeadInput, lead_data)
    required = config.get("required_fields", {}).get("lead", [])
    missing = _missing_fields(lead_data, required)

    if errors:
        output = LeadSourcingOutput(
            agent="LeadSourcingAgent",
            status="error",
            rationale_summary=["Lead validation failed."],
            evidence=mask_sensitive({"lead": lead_data}),
            calculations=[],
            missing_data=missing,
            confidence=_confidence(missing, required),
            errors=errors,
        )
    elif missing:
        output = LeadSourcingOutput(
            agent="LeadSourcingAgent",
            status="insufficient_data",
            rationale_summary=[f"Missing lead fields: {', '.join(missing)}."],
            evidence=mask_sensitive({"lead": lead_data}),
            calculations=[],
            missing_data=missing,
            confidence=_confidence(missing, required),
            normalized_lead={},
        )
    else:
        normalized = {
            "full_name": f"{parsed.first_name} {parsed.last_name}",
            "requested_amount": parsed.requested_amount,
            "tenure_months": parsed.tenure_months,
        }
        output = LeadSourcingOutput(
            agent="LeadSourcingAgent",
            status="ok",
            rationale_summary=[
                f"lead.first_name={parsed.first_name} and lead.last_name={parsed.last_name}",
                f"lead.requested_amount={parsed.requested_amount} and lead.tenure_months={parsed.tenure_months}",
            ],
            evidence=mask_sensitive({"lead": lead_data}),
            calculations=["full_name = first_name + ' ' + last_name"],
            missing_data=[],
            confidence=_confidence([], required),
            normalized_lead=normalized,
        )

    state.setdefault("outputs", {})["lead_sourcing"] = output.model_dump()
    log_event(logger, "agent_output", "Lead sourcing completed", run_id, thread_id, "LeadSourcingAgent", output.model_dump())
    return state


def sales_agent(state: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    required_sections = ["lead", "id", "bureau", "bank", "payslip"]
    missing_sections = [section for section in required_sections if section not in state.get("input", {})]

    missing_fields = []
    all_required_fields = []
    for section in required_sections:
        required = config.get("required_fields", {}).get(section, [])
        data = state.get("input", {}).get(section, {})
        all_required_fields.extend([f"{section}.{field}" for field in required])
        missing_fields.extend([f"{section}.{field}" for field in _missing_fields(data, required)])

    if missing_sections or missing_fields:
        output = SalesAgentOutput(
            agent="SalesAgent",
            status="insufficient_data",
            rationale_summary=["Missing required sections or fields; stopping orchestration."],
            evidence=mask_sensitive({"missing_sections": missing_sections, "missing_fields": missing_fields}),
            calculations=[],
            missing_data=missing_fields or missing_sections,
            confidence=_confidence(missing_fields, all_required_fields),
            route="stop",
        )
    else:
        output = SalesAgentOutput(
            agent="SalesAgent",
            status="ok",
            rationale_summary=["All required sections present; proceeding to fraud and risk checks."],
            evidence=mask_sensitive({"sections": list(state.get("input", {}).keys())}),
            calculations=[],
            missing_data=[],
            confidence=1.0,
            route="proceed",
        )

    state.setdefault("outputs", {})["sales_agent"] = output.model_dump()
    log_event(logger, "agent_output", "SalesAgent decision completed", run_id, thread_id, "SalesAgent", output.model_dump())
    return state


def fraud_agent(state: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    lead_data = state.get("input", {}).get("lead", {})
    id_data = state.get("input", {}).get("id", {})

    required_id = config.get("required_fields", {}).get("id", [])
    required_lead = ["first_name", "last_name", "city"]
    required_id_extra = ["address"]
    missing = (
        [f"id.{field}" for field in _missing_fields(id_data, required_id)]
        + [f"id.{field}" for field in _missing_fields(id_data, required_id_extra)]
        + [f"lead.{field}" for field in _missing_fields(lead_data, required_lead)]
    )

    if missing:
        output = FraudOutput(
            agent="FraudAgent",
            status="insufficient_data",
            rationale_summary=[f"Missing fraud inputs: {', '.join(missing)}."],
            evidence=mask_sensitive({"id": id_data}),
            calculations=[],
            missing_data=missing,
            confidence=_confidence(missing, [f"id.{field}" for field in required_id + required_id_extra] + [f"lead.{field}" for field in required_lead]),
        )
    else:
        lead_name = f"{lead_data.get('first_name', '')} {lead_data.get('last_name', '')}".strip().lower()
        id_name = str(id_data.get("full_name", "")).lower()
        lead_tokens = set(lead_name.split()) if lead_name else set()
        id_tokens = set(id_name.split()) if id_name else set()
        union = lead_tokens.union(id_tokens)
        intersection = lead_tokens.intersection(id_tokens)
        name_similarity = len(intersection) / len(union) if union else 0.0
        name_mismatch = 1.0 - name_similarity

        city = str(lead_data.get("city", "")).lower()
        address = str(id_data.get("address", "")).lower()
        address_mismatch = 0.0 if city and city in address else 1.0

        fraud_score = (name_mismatch + address_mismatch) / 2.0

        output = FraudOutput(
            agent="FraudAgent",
            status="ok",
            rationale_summary=[
                f"name_mismatch={name_mismatch:.2f} from lead vs id name tokens",
                f"address_mismatch={address_mismatch:.2f} using lead.city vs id.address",
            ],
            evidence=mask_sensitive({"lead": lead_data, "id": id_data}),
            calculations=[
                "name_similarity = |intersection(tokens)| / |union(tokens)|",
                "fraud_score = (name_mismatch + address_mismatch) / 2",
            ],
            missing_data=[],
            confidence=_confidence([], [f"id.{field}" for field in required_id + required_id_extra] + [f"lead.{field}" for field in required_lead]),
            fraud_score=fraud_score,
            name_mismatch=name_mismatch,
            address_mismatch=address_mismatch,
        )

    state.setdefault("outputs", {})["fraud"] = output.model_dump()
    log_event(logger, "agent_output", "FraudAgent completed", run_id, thread_id, "FraudAgent", output.model_dump())
    return state


def risk_agent(state: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    lead_data = state.get("input", {}).get("lead", {})
    bureau_data = state.get("input", {}).get("bureau", {})
    bank_data = state.get("input", {}).get("bank", {})
    payslip_data = state.get("input", {}).get("payslip", {})

    missing = []
    required_fields = []
    for section in ["lead", "bureau", "bank", "payslip"]:
        required = config.get("required_fields", {}).get(section, [])
        data = state.get("input", {}).get(section, {})
        required_fields.extend([f"{section}.{field}" for field in required])
        missing.extend([f"{section}.{field}" for field in _missing_fields(data, required)])

    if missing:
        output = RiskOutput(
            agent="RiskAgent",
            status="insufficient_data",
            rationale_summary=[f"Missing risk inputs: {', '.join(missing)}."],
            evidence=mask_sensitive({"lead": lead_data, "bureau": bureau_data, "bank": bank_data, "payslip": payslip_data}),
            calculations=[],
            missing_data=missing,
            confidence=_confidence(missing, required_fields),
        )
    else:
        emi = compute_emi(
            float(lead_data.get("requested_amount", 0)),
            float(config.get("risk", {}).get("annual_interest_rate", 0)),
            int(lead_data.get("tenure_months", 0)),
        )
        dti = compute_dti(float(bank_data.get("monthly_obligations", 0)), float(bank_data.get("monthly_income", 0)))
        foir = compute_foir(float(bank_data.get("monthly_obligations", 0)), emi, float(bank_data.get("monthly_income", 0)))

        metrics = {
            "bureau_score": normalized(float(bureau_data.get("score", 0)), float(config.get("risk", {}).get("max_bureau_score", 1))),
            "income_stability": normalized(float(payslip_data.get("net_salary", 0)), float(config.get("risk", {}).get("min_salary", 1))),
            "bank_balance": normalized(float(bank_data.get("avg_monthly_balance", 0)), float(config.get("risk", {}).get("max_bank_balance", 1))),
            "employment_tenure": normalized(float(payslip_data.get("employment_tenure_months", 0)), float(config.get("risk", {}).get("max_employment_tenure_months", 1))),
        }
        min_bureau = float(config.get("risk", {}).get("min_bureau_score", 0))
        min_salary = float(config.get("risk", {}).get("min_salary", 0))
        max_dti = float(config.get("risk", {}).get("max_dti", 1))
        max_foir = float(config.get("risk", {}).get("max_foir", 1))
        approval_score = weighted_score(metrics, config.get("weights", {}))
        risk_score = max(0.0, 1.0 - approval_score)

        output = RiskOutput(
            agent="RiskAgent",
            status="ok",
            rationale_summary=[
                f"bureau.score={bureau_data.get('score')} normalized to {metrics['bureau_score']:.2f}",
                f"DTI={dti:.2f} and FOIR={foir:.2f}",
                f"bureau.score >= min_bureau_score ({min_bureau}): {float(bureau_data.get('score', 0)) >= min_bureau}",
                f"net_salary >= min_salary ({min_salary}): {float(payslip_data.get('net_salary', 0)) >= min_salary}",
                f"DTI <= max_dti ({max_dti}): {dti <= max_dti}",
                f"FOIR <= max_foir ({max_foir}): {foir <= max_foir}",
                f"approval_score={approval_score:.2f} from configured weights",
            ],
            evidence=mask_sensitive({"bureau": bureau_data, "bank": bank_data, "payslip": payslip_data}),
            calculations=[
                f"emi = EMI(principal={lead_data.get('requested_amount')}, annual_rate={config.get('risk', {}).get('annual_interest_rate')}, tenure_months={lead_data.get('tenure_months')})",
                "dti = monthly_obligations / monthly_income",
                "foir = (monthly_obligations + emi) / monthly_income",
                "approval_score = sum(metric * weight)",
                "risk_score = 1 - approval_score",
            ],
            missing_data=[],
            confidence=_confidence([], required_fields),
            dti=dti,
            foir=foir,
            approval_score=approval_score,
            risk_score=risk_score,
        )

    state.setdefault("outputs", {})["risk"] = output.model_dump()
    log_event(logger, "agent_output", "RiskAgent completed", run_id, thread_id, "RiskAgent", output.model_dump())
    return state


def approval_agent(state: Dict[str, Any], config: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    fraud_output = state.get("outputs", {}).get("fraud")
    risk_output = state.get("outputs", {}).get("risk")
    lead_data = state.get("input", {}).get("lead", {})

    missing = []
    if not fraud_output:
        missing.append("fraud_output")
    if not risk_output:
        missing.append("risk_output")

    if missing:
        output = ApprovalOutput(
            agent="ApprovalAgent",
            status="insufficient_data",
            rationale_summary=[f"Missing upstream outputs: {', '.join(missing)}."],
            evidence=mask_sensitive({"missing": missing}),
            calculations=[],
            missing_data=missing,
            confidence=_confidence(missing, ["fraud_output", "risk_output"]),
        )
    else:
        fraud_score = float(fraud_output.get("fraud_score", 1.0))
        risk_score = float(risk_output.get("risk_score", 1.0))
        approval_score = float(risk_output.get("approval_score", 0.0))
        decision = "decline"
        if (
            fraud_score <= float(config.get("fraud", {}).get("max_fraud_score", 0.0))
            and risk_score <= float(config.get("approval", {}).get("max_risk_score", 0.0))
            and approval_score >= float(config.get("approval", {}).get("min_approval_score", 1.0))
        ):
            decision = "approve"

        output = ApprovalOutput(
            agent="ApprovalAgent",
            status="ok" if decision != "insufficient_data" else "insufficient_data",
            rationale_summary=[
                f"fraud_score={fraud_score:.2f} vs max_fraud_score={config.get('fraud', {}).get('max_fraud_score')}",
                f"risk_score={risk_score:.2f} vs max_risk_score={config.get('approval', {}).get('max_risk_score')}",
                f"approval_score={approval_score:.2f} vs min_approval_score={config.get('approval', {}).get('min_approval_score')}",
            ],
            evidence=mask_sensitive({"fraud": fraud_output, "risk": risk_output}),
            calculations=["decision = approve if all thresholds are satisfied"],
            missing_data=[],
            confidence=1.0,
            decision=decision,
            approved_amount=float(lead_data.get("requested_amount")) if decision == "approve" else None,
        )

    state.setdefault("outputs", {})["approval"] = output.model_dump()
    log_event(logger, "agent_output", "ApprovalAgent completed", run_id, thread_id, "ApprovalAgent", output.model_dump())
    return state
