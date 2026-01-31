from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from app.logging_setup import log_event
from app.utils.masking import mask_sensitive


PromptMeta = Dict[str, Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_ms(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() * 1000.0


def run_agent_with_trace(
    agent_name: str,
    fn: Callable[..., Dict[str, Any]],
    state: Dict[str, Any],
    config: Dict[str, Any],
    prompt_loader: Optional[Any] = None,
    llm_client: Optional[Any] = None,
    input_snapshot: Optional[Dict[str, Any]] = None,
    prompt_meta: Optional[PromptMeta] = None,
    logger: Optional[Any] = None,
    case_id: Optional[str] = None,
) -> Dict[str, Any]:
    state.setdefault("traces", {})
    if logger is None:
        logger = state.get("logger")
    run_id = state.get("run_id")
    thread_id = state.get("thread_id")
    if case_id is None:
        case_id = state.get("case_id")

    started = datetime.now(timezone.utc)
    started_at = _now_iso()

    if logger and run_id and thread_id:
        log_event(logger, f"{agent_name} trace start", run_id, thread_id, "trace_start", case_id=case_id)

    safe_input = mask_sensitive(input_snapshot or {})
    output = fn(state, config, prompt_loader)

    ended = datetime.now(timezone.utc)
    ended_at = _now_iso()

    trace = {
        "agent_name": agent_name,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": _duration_ms(started, ended),
        "input_snapshot": safe_input,
        "output_snapshot": output if isinstance(output, dict) else {},
        "prompt_meta": prompt_meta or {},
        "tool_calls": [],
        "warnings": [],
    }

    state["traces"][agent_name] = trace

    if logger and run_id and thread_id:
        log_event(
            logger,
            f"{agent_name} trace end",
            run_id,
            thread_id,
            "trace_end",
            case_id=case_id,
            data={"duration_ms": trace["duration_ms"]},
        )

    return output
