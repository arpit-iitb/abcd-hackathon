from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
    raise RuntimeError(
        "Missing Sqlite checkpoint dependency. Install with "
        "`pip install langgraph-checkpoint-sqlite` or update requirements.txt."
    ) from exc
from langgraph.graph import END, StateGraph

from agents.approval import run_approval
from agents.bank_statement import run_bank_statement
from agents.bureau import run_bureau
from agents.fraud import run_fraud
from agents.id_verification import run_id_verification
from agents.lead_sourcing import run_lead_sourcing
from agents.payslip import run_payslip
from agents.risk_assessment import run_risk_assessment
from app.logging_setup import log_event
from app.llm_runner import resolve_model_config
from app.utils.masking import mask_sensitive
from app.utils.trace_runner import run_agent_with_trace


class LoanGraphState(dict):
    pass


_LOGGER = None


def set_runtime_logger(logger):
    global _LOGGER
    _LOGGER = logger


def _get_logger():
    return _LOGGER


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_node_start(logger, run_id: str, thread_id: str, case_id: str, node_name: str, data: Dict[str, Any]):
    log_event(logger, f"{node_name} start", run_id, thread_id, "node_start", case_id=case_id, data=data)


def _log_node_end(logger, run_id: str, thread_id: str, case_id: str, node_name: str, data: Dict[str, Any]):
    log_event(logger, f"{node_name} end", run_id, thread_id, "node_end", case_id=case_id, data=data)


def _ensure_results(state: Dict[str, Any]) -> Dict[str, Any]:
    state.setdefault("results", {})
    state.setdefault("sales_orchestrator", {"steps": [], "timings": {}})
    state.setdefault("traces", {})
    state.pop("logger", None)
    return state


def _prompt_meta(state: Dict[str, Any], prompt_file: str) -> Dict[str, Any]:
    config = state.get("config", {})
    model_cfg = resolve_model_config(config, prompt_file.replace(".yaml", ""))
    return {
        "prompt_file": prompt_file,
        "prompt_version": "v1",
        "model": model_cfg.get("model", "unknown"),
        "temperature": model_cfg.get("temperature", "unknown"),
    }


def lead_sourcing_node(state: Dict[str, Any]) -> Dict[str, Any]:
    state = _ensure_results(state)
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    case_id = state.get("case_id", "")
    logger = _get_logger()
    input_data = state["input"]

    _log_node_start(logger, run_id, thread_id, case_id, "lead_sourcing", {"lead_id": input_data.get("lead", {}).get("lead_id")})

    def _runner(_, config, __):
        return run_lead_sourcing(input_data.get("lead", {}), config, state.get("prompts", {}))

    result = run_agent_with_trace(
        "lead_sourcing",
        _runner,
        state,
        state.get("config", {}),
        state.get("prompts", {}),
        input_snapshot=input_data.get("lead", {}),
        prompt_meta=_prompt_meta(state, "lead_sourcing.yaml"),
        logger=logger,
        case_id=case_id,
    )
    state["results"]["lead_sourcing"] = result
    _log_node_end(logger, run_id, thread_id, case_id, "lead_sourcing", {"status": result.get("status")})

    state["sales_orchestrator"]["steps"].append("lead_sourcing")
    state["sales_orchestrator"]["timings"]["lead_sourcing"] = _timestamp()
    return state


def bureau_node(state: Dict[str, Any]) -> Dict[str, Any]:
    state = _ensure_results(state)
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    case_id = state.get("case_id", "")
    logger = _get_logger()

    _log_node_start(logger, run_id, thread_id, case_id, "bureau", {})

    def _runner(_, config, __):
        return run_bureau(state.get("input", {}).get("bureau_report", {}), config, state.get("prompts", {}))

    result = run_agent_with_trace(
        "bureau",
        _runner,
        state,
        state.get("config", {}),
        state.get("prompts", {}),
        input_snapshot=state.get("input", {}).get("bureau_report", {}),
        prompt_meta=_prompt_meta(state, "bureau.yaml"),
        logger=logger,
        case_id=case_id,
    )
    state["results"]["bureau"] = result
    _log_node_end(logger, run_id, thread_id, case_id, "bureau", {"status": result.get("status")})

    state["sales_orchestrator"]["steps"].append("bureau")
    state["sales_orchestrator"]["timings"]["bureau"] = _timestamp()
    return state


def bank_statement_node(state: Dict[str, Any]) -> Dict[str, Any]:
    state = _ensure_results(state)
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    case_id = state.get("case_id", "")
    logger = _get_logger()

    _log_node_start(logger, run_id, thread_id, case_id, "bank_statement", {})
    txns = state.get("input", {}).get("bank_statement", [])

    def _runner(_, config, __):
        return run_bank_statement(txns, config, state.get("prompts", {}))

    result = run_agent_with_trace(
        "bank_statement",
        _runner,
        state,
        state.get("config", {}),
        state.get("prompts", {}),
        input_snapshot={"transactions": txns[:10]},
        prompt_meta=_prompt_meta(state, "bank_statement.yaml"),
        logger=logger,
        case_id=case_id,
    )
    state["results"]["bank_statement"] = result
    _log_node_end(logger, run_id, thread_id, case_id, "bank_statement", {"status": result.get("status")})

    state["sales_orchestrator"]["steps"].append("bank_statement")
    state["sales_orchestrator"]["timings"]["bank_statement"] = _timestamp()
    return state


def id_verification_node(state: Dict[str, Any]) -> Dict[str, Any]:
    state = _ensure_results(state)
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    case_id = state.get("case_id", "")
    logger = _get_logger()

    _log_node_start(logger, run_id, thread_id, case_id, "id_verification", {})
    payload = {
        "lead": state.get("input", {}).get("lead", {}),
        "documents": state.get("input", {}).get("documents", {}),
    }

    def _runner(_, config, __):
        return run_id_verification(payload, config, state.get("prompts", {}))

    result = run_agent_with_trace(
        "id_verification",
        _runner,
        state,
        state.get("config", {}),
        state.get("prompts", {}),
        input_snapshot=payload,
        prompt_meta=_prompt_meta(state, "id_verification.yaml"),
        logger=logger,
        case_id=case_id,
    )
    state["results"]["id_verification"] = result
    _log_node_end(logger, run_id, thread_id, case_id, "id_verification", {"status": result.get("status")})

    state["sales_orchestrator"]["steps"].append("id_verification")
    state["sales_orchestrator"]["timings"]["id_verification"] = _timestamp()
    return state


def payslip_node(state: Dict[str, Any]) -> Dict[str, Any]:
    state = _ensure_results(state)
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    case_id = state.get("case_id", "")
    logger = _get_logger()

    _log_node_start(logger, run_id, thread_id, case_id, "payslip", {})
    payload = {"documents": state.get("input", {}).get("documents", {})}

    def _runner(_, config, __):
        return run_payslip(payload, config, state.get("prompts", {}))

    result = run_agent_with_trace(
        "payslip",
        _runner,
        state,
        state.get("config", {}),
        state.get("prompts", {}),
        input_snapshot=payload,
        prompt_meta=_prompt_meta(state, "payslip.yaml"),
        logger=logger,
        case_id=case_id,
    )
    state["results"]["payslip"] = result
    _log_node_end(logger, run_id, thread_id, case_id, "payslip", {"status": result.get("status")})

    state["sales_orchestrator"]["steps"].append("payslip")
    state["sales_orchestrator"]["timings"]["payslip"] = _timestamp()
    return state


def fraud_node(state: Dict[str, Any]) -> Dict[str, Any]:
    state = _ensure_results(state)
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    case_id = state.get("case_id", "")
    logger = _get_logger()

    _log_node_start(logger, run_id, thread_id, case_id, "fraud", {})
    payload = {
        "bank_statement": state.get("results", {}).get("bank_statement", {}),
        "payslip": state.get("results", {}).get("payslip", {}),
        "id_verification": state.get("results", {}).get("id_verification", {}),
        "bureau": state.get("results", {}).get("bureau", {}),
    }

    def _runner(_, config, __):
        return run_fraud(payload, config, state.get("prompts", {}))

    result = run_agent_with_trace(
        "fraud",
        _runner,
        state,
        state.get("config", {}),
        state.get("prompts", {}),
        input_snapshot=payload,
        prompt_meta=_prompt_meta(state, "fraud.yaml"),
        logger=logger,
        case_id=case_id,
    )
    state["results"]["fraud"] = result
    _log_node_end(logger, run_id, thread_id, case_id, "fraud", {"status": result.get("status")})

    state["sales_orchestrator"]["steps"].append("fraud")
    state["sales_orchestrator"]["timings"]["fraud"] = _timestamp()
    return state


def risk_assessment_node(state: Dict[str, Any]) -> Dict[str, Any]:
    state = _ensure_results(state)
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    case_id = state.get("case_id", "")
    logger = _get_logger()

    _log_node_start(logger, run_id, thread_id, case_id, "risk_assessment", {})
    bank_output = state.get("results", {}).get("bank_statement", {}).get("output", {}) or {}
    lead_input = state.get("input", {}).get("lead", {}) or {}
    avg_balance = bank_output.get("avg_balance")
    requested_amount = lead_input.get("requested_amount")
    request_to_balance_multiplier = None
    if isinstance(avg_balance, (int, float)) and isinstance(requested_amount, (int, float)) and avg_balance > 0:
        request_to_balance_multiplier = float(requested_amount) / float(avg_balance)

    bank_payload = dict(bank_output)
    bank_payload["request_to_balance_multiplier"] = request_to_balance_multiplier

    payload = {
        "bureau": state.get("results", {}).get("bureau", {}).get("output", {}),
        "bank_statement": bank_payload,
        "lead": lead_input,
    }

    def _runner(_, config, __):
        return run_risk_assessment(payload, config, state.get("prompts", {}))

    result = run_agent_with_trace(
        "risk_assessment",
        _runner,
        state,
        state.get("config", {}),
        state.get("prompts", {}),
        input_snapshot=payload,
        prompt_meta=_prompt_meta(state, "risk_assessment.yaml"),
        logger=logger,
        case_id=case_id,
    )
    state["results"]["risk_assessment"] = result
    _log_node_end(logger, run_id, thread_id, case_id, "risk_assessment", {"status": result.get("status")})

    state["sales_orchestrator"]["steps"].append("risk_assessment")
    state["sales_orchestrator"]["timings"]["risk_assessment"] = _timestamp()
    return state


def approval_node(state: Dict[str, Any]) -> Dict[str, Any]:
    state = _ensure_results(state)
    run_id = state["run_id"]
    thread_id = state["thread_id"]
    case_id = state.get("case_id", "")
    logger = _get_logger()

    _log_node_start(logger, run_id, thread_id, case_id, "approval", {})
    payload = {
        "lead": state.get("input", {}).get("lead", {}),
        "bank_statement": state.get("results", {}).get("bank_statement", {}),
        "risk_assessment": state.get("results", {}).get("risk_assessment", {}),
        "fraud": state.get("results", {}).get("fraud", {}),
        "lead_sourcing": state.get("results", {}).get("lead_sourcing", {}),
        "bureau": state.get("results", {}).get("bureau", {}),
        "id_verification": state.get("results", {}).get("id_verification", {}),
        "payslip": state.get("results", {}).get("payslip", {}),
    }

    def _runner(_, config, __):
        return run_approval(payload, config, state.get("prompts", {}))

    result = run_agent_with_trace(
        "approval",
        _runner,
        state,
        state.get("config", {}),
        state.get("prompts", {}),
        input_snapshot=payload,
        prompt_meta=_prompt_meta(state, "approval.yaml"),
        logger=logger,
        case_id=case_id,
    )
    state["results"]["approval"] = result
    _log_node_end(logger, run_id, thread_id, case_id, "approval", {"status": result.get("status")})

    state["sales_orchestrator"]["steps"].append("approval")
    state["sales_orchestrator"]["timings"]["approval"] = _timestamp()

    state["results"]["sales_orchestrator"] = {
        "steps": state["sales_orchestrator"].get("steps", []),
        "timings": state["sales_orchestrator"].get("timings", {}),
    }

    lead = state.get("input", {}).get("lead", {})
    lead_summary = mask_sensitive(
        {
            "lead_id": lead.get("lead_id"),
            "name": lead.get("name"),
            "city": lead.get("city"),
            "tier": lead.get("tier"),
            "requested_amount": lead.get("requested_amount"),
            "product_type": lead.get("product_type"),
            "aadhaar_last4": lead.get("aadhaar_last4"),
            "pan_masked": lead.get("pan_masked"),
        }
    )

    bank_output = state.get("results", {}).get("bank_statement", {}).get("output", {})
    bureau_output = state.get("results", {}).get("bureau", {}).get("output", {})
    fraud_output = state.get("results", {}).get("fraud", {}).get("output", {})
    risk_output = state.get("results", {}).get("risk_assessment", {}).get("output", {})

    key_metrics = {
        "avg_balance": bank_output.get("avg_balance"),
        "salary_estimate": bank_output.get("salary_estimate"),
        "dpd_counts": bureau_output.get("repayment_summary", {}).get("bad_dpd_count"),
        "enquiries": bureau_output.get("enquiry_summary", {}).get("enquiry_count"),
        "suspicious_ratio": bank_output.get("suspicious", {}).get("suspicious_ratio"),
    }

    agent_statuses = {
        agent: data.get("status")
        for agent, data in state.get("results", {}).items()
        if isinstance(data, dict)
    }

    top_risks = risk_output.get("risk_factors", []) if isinstance(risk_output, dict) else []
    signals = fraud_output.get("signals", []) if isinstance(fraud_output, dict) else []
    top_fraud_signals = [signal.get("signal_name") for signal in signals if isinstance(signal, dict)]

    approval_output = result.get("output", {}) if isinstance(result, dict) else {}
    reasons = approval_output.get("reasons", [])
    missing_data = result.get("missing_data", []) if isinstance(result, dict) else []
    human_review = approval_output.get("human_review") if isinstance(approval_output, dict) else None
    recommended_terms = human_review.get("recommended_terms") if isinstance(human_review, dict) else None

    case_id = lead.get("lead_id") or thread_id
    state["review_packet"] = {
        "case_id": case_id,
        "run_id": run_id,
        "lead_summary": lead_summary,
        "key_metrics": key_metrics,
        "agent_statuses": agent_statuses,
        "top_risks": top_risks,
        "top_fraud_signals": top_fraud_signals,
        "recommended_terms": recommended_terms,
        "reasons": reasons,
        "missing_data": missing_data,
        "links_to_logs_files": [f"runs/{case_id}_{run_id}.txt", f"runs/{case_id}_{run_id}.jsonl"],
    }

    state["decision"] = approval_output
    return state


def build_graph(checkpointer: SqliteSaver):
    graph = StateGraph(LoanGraphState)

    graph.add_node("lead_sourcing", lead_sourcing_node)
    graph.add_node("bureau", bureau_node)
    graph.add_node("bank_statement", bank_statement_node)
    graph.add_node("id_verification", id_verification_node)
    graph.add_node("payslip", payslip_node)
    graph.add_node("fraud", fraud_node)
    graph.add_node("risk_assessment", risk_assessment_node)
    graph.add_node("approval", approval_node)

    graph.set_entry_point("lead_sourcing")
    graph.add_edge("lead_sourcing", "bureau")
    graph.add_edge("bureau", "bank_statement")
    graph.add_edge("bank_statement", "id_verification")
    graph.add_edge("id_verification", "payslip")
    graph.add_edge("payslip", "fraud")
    graph.add_edge("fraud", "risk_assessment")
    graph.add_edge("risk_assessment", "approval")
    graph.add_edge("approval", END)

    return graph.compile(checkpointer=checkpointer)
