from __future__ import annotations

import hashlib
import re
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.utils.masking import mask_sensitive


def _sanitize_case_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    return cleaned or "case"


def compute_case_id(input_payload: Dict[str, Any]) -> str:
    lead = input_payload.get("lead", {}) if isinstance(input_payload, dict) else {}
    for key in ("lead_id", "application_id"):
        value = lead.get(key) or input_payload.get(key)
        if value:
            return _sanitize_case_id(str(value))
    name = str(lead.get("name", ""))
    phone = str(lead.get("phone", ""))
    amount = str(lead.get("requested_amount", ""))
    raw = f"{name}|{phone}|{amount}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:12]
    return _sanitize_case_id(f"case_{digest}")


def _sanitize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = {key: value for key, value in state.items() if key not in {"logger"}}
    return mask_sensitive(sanitized)


def _close_logger_handlers(state: Dict[str, Any]) -> None:
    logger = state.get("logger")
    target = getattr(logger, "logger", logger)
    handlers = getattr(target, "handlers", [])
    for handler in handlers:
        try:
            handler.flush()
            handler.close()
        except Exception:
            continue


def write_run_artifacts(
    state: Dict[str, Any],
    case_id: str,
    run_id: str,
    thread_id: str,
    log_dir: str = "runs",
) -> Dict[str, Path]:
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).isoformat()
    _close_logger_handlers(state)
    masked_state = _sanitize_state(state)

    state_path = Path(log_dir) / f"{case_id}_{run_id}_STATE.json"
    decision_path = Path(log_dir) / f"{case_id}_{run_id}_DECISION.json"
    report_path = Path(log_dir) / f"{case_id}_{run_id}.txt"

    approval = masked_state.get("results", {}).get("approval", {})
    decision_output = approval.get("output", {}) if isinstance(approval, dict) else {}

    state_path.write_text(json.dumps(masked_state, ensure_ascii=True, indent=2), encoding="utf-8")
    decision_payload = {
        "case_id": case_id,
        "run_id": run_id,
        "thread_id": thread_id,
        "decision": decision_output,
    }
    decision_path.write_text(json.dumps(decision_payload, ensure_ascii=True, indent=2), encoding="utf-8")

    traces = masked_state.get("traces", {})
    model_info = "unknown"
    temperature = "unknown"
    if traces:
        first_trace = next(iter(traces.values()))
        prompt_meta = first_trace.get("prompt_meta", {}) if isinstance(first_trace, dict) else {}
        model_info = prompt_meta.get("model", "unknown")
        temperature = prompt_meta.get("temperature", "unknown")

    lines: List[str] = []
    lines.append("Loan Agentic Run Report")
    lines.append(f"run_id: {run_id}")
    lines.append(f"case_id: {case_id}")
    lines.append(f"thread_id: {thread_id}")
    lines.append(f"timestamp: {timestamp}")
    lines.append(f"model: {model_info}")
    lines.append(f"temperature: {temperature}")
    lines.append("")

    ordered_agents = [
        "lead_sourcing",
        "bureau",
        "bank_statement",
        "id_verification",
        "payslip",
        "fraud",
        "risk_assessment",
        "approval",
    ]

    for agent_name in ordered_agents:
        trace = traces.get(agent_name, {})
        output_snapshot = trace.get("output_snapshot", {}) if isinstance(trace, dict) else {}
        status = output_snapshot.get("status")
        errors = output_snapshot.get("errors", []) if isinstance(output_snapshot, dict) else []
        warnings = trace.get("warnings", []) if isinstance(trace, dict) else []
        lines.append(f"Agent: {agent_name}")
        lines.append(f"Duration (ms): {trace.get('duration_ms')}")
        lines.append(f"Status: {status}")
        lines.append("Input Snapshot:")
        lines.append(json.dumps(trace.get("input_snapshot", {}), ensure_ascii=True, indent=2))
        lines.append("Output:")
        lines.append(json.dumps(output_snapshot, ensure_ascii=True, indent=2))
        lines.append(f"Errors: {json.dumps(errors, ensure_ascii=True)}")
        lines.append(f"Warnings: {json.dumps(warnings, ensure_ascii=True)}")
        lines.append("")

    lines.append("Final Decision Summary")
    lines.append(json.dumps(decision_output, ensure_ascii=True, indent=2))

    report_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "state": state_path,
        "decision": decision_path,
        "report": report_path,
    }
