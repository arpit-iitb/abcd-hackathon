from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

import streamlit as st
import yaml
from app.checkpoint_utils import get_sqlite_checkpointer, list_checkpoints, load_final_state
from app.config import load_config_dir
from app.graph import build_graph, set_runtime_logger
from app.json_utils import dump_json, load_json
from app.logging_setup import setup_logger
from app.prompt_loader import load_prompts
from app.state import LoanApplicationInput
from agents.lead_sourcing import run_lead_sourcing
from app.reporting import compute_case_id, write_run_artifacts
from app.openai_client import has_api_key
from app.utils.image_utils import load_image_base64


st.set_page_config(page_title="Loan Agentic Pipeline", layout="wide")

st.title("Loan Agentic Pipeline")

if not has_api_key():
    st.warning("OPENAI_API_KEY is missing. Copy .env.example to .env and set your key.")

config_dir = st.sidebar.text_input("Config dir", "configs")
prompt_dir = st.sidebar.text_input("Prompt dir", "prompts")
sample_dir = st.sidebar.text_input("Sample dir", "data")


def load_samples(path: str) -> List[Dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, list):
        return payload
    return [payload]


def tail_lines(path: Path, limit: int = 20) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    return "\n".join(lines[-limit:])


def list_review_files() -> List[Path]:
    runs_dir = Path("runs")
    if not runs_dir.exists():
        return []
    return sorted(runs_dir.glob("*_HUMAN_REVIEW.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def parse_review_file(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_decision(case_id: str, run_id: str, decision_payload: Dict[str, Any]) -> None:
    runs_dir = Path("runs")
    runs_dir.mkdir(parents=True, exist_ok=True)
    decision_path = runs_dir / f"{case_id}_{run_id}_HUMAN_DECISION.json"
    final_path = runs_dir / f"{case_id}_{run_id}_FINAL.json"
    decision_path.write_text(dump_json(decision_payload), encoding="utf-8")
    final_path.write_text(dump_json(decision_payload.get("final_decision", decision_payload)), encoding="utf-8")


try:
    lead_samples = load_samples(f"{sample_dir}/lead_samples.json")
except Exception as exc:
    st.error(f"Failed to load lead samples: {exc}")
    st.stop()

sample_ids = [sample.get("lead_id", f"sample_{idx}") for idx, sample in enumerate(lead_samples)]
selected_sample = st.sidebar.selectbox("Sample applicant id", sample_ids)

AGENT_ORDER = [
    "lead_sourcing",
    "bureau",
    "bank_statement",
    "id_verification",
    "payslip",
    "fraud",
    "risk_assessment",
    "approval",
]


def summarize_agent_output(agent_name: str, result: Dict[str, Any]) -> str:
    output = result.get("output", {}) if isinstance(result, dict) else {}
    if agent_name == "lead_sourcing":
        return f"selected={output.get('selected')}"
    if agent_name == "bureau":
        return f"risk={output.get('bureau_risk_grade')}"
    if agent_name == "bank_statement":
        return f"avg_balance={output.get('avg_balance')}, salary={output.get('salary_estimate')}"
    if agent_name == "id_verification":
        return f"name_match={output.get('name_match')}, face_match={output.get('face_match')}"
    if agent_name == "payslip":
        return f"monthly_income={output.get('monthly_income_estimate')}"
    if agent_name == "fraud":
        return f"fraud_grade={output.get('fraud_grade')}"
    if agent_name == "risk_assessment":
        return f"risk={output.get('final_risk_grade')}"
    if agent_name == "approval":
        return f"decision={output.get('decision')}, sanctioned={output.get('sanctioned_amount')}"
    return ""

if "config_override" not in st.session_state:
    try:
        st.session_state.config_override = load_config_dir(config_dir)
    except Exception as exc:
        st.session_state.config_override = {}
        st.sidebar.error(f"Config load error: {exc}")

st.sidebar.markdown("### Config (editable)")
config_text = st.sidebar.text_area(
    "Config YAML",
    value=yaml.safe_dump(st.session_state.config_override, sort_keys=False),
    height=260,
)

config_col1, config_col2 = st.sidebar.columns(2)
if config_col1.button("Apply"):
    try:
        st.session_state.config_override = yaml.safe_load(config_text) or {}
        st.sidebar.success("Config applied")
    except Exception as exc:
        st.sidebar.error(f"Invalid YAML: {exc}")

if config_col2.button("Reload"):
    try:
        st.session_state.config_override = load_config_dir(config_dir)
        st.sidebar.success("Reloaded from disk")
    except Exception as exc:
        st.sidebar.error(f"Reload failed: {exc}")

lead_button = st.sidebar.button("Run Lead Sourcing")


def build_application_payload(sample_id: str) -> Dict[str, Any]:
    def pick_sample(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        for sample in samples:
            if sample.get("lead_id") == sample_id:
                return sample
        return samples[0]

    bureau_samples = load_samples(f"{sample_dir}/bureau_samples.json")
    bank_samples = load_samples(f"{sample_dir}/bank_statement_samples.json")
    id_docs_samples = load_samples(f"{sample_dir}/id_docs_samples.json")
    payslip_samples = load_samples(f"{sample_dir}/payslip_samples.json")

    lead_sample = pick_sample(lead_samples)
    bureau_sample = pick_sample(bureau_samples)
    bank_sample = pick_sample(bank_samples)
    id_docs_sample = pick_sample(id_docs_samples)
    payslip_sample = pick_sample(payslip_samples)

    aadhaar_base64 = ""
    selfie_base64 = ""
    aadhaar_path = id_docs_sample.get("aadhaar_image_file") or (id_docs_sample.get("aadhaar_doc") or {}).get("image_path")
    selfie_path = id_docs_sample.get("selfie_image_file") or (id_docs_sample.get("selfie_doc") or {}).get("image_path")
    try:
        aadhaar_base64 = load_image_base64(aadhaar_path)
    except Exception:
        aadhaar_base64 = ""
    try:
        selfie_base64 = load_image_base64(selfie_path)
    except Exception:
        selfie_base64 = ""

    aadhaar_doc = {"image_base64": aadhaar_base64} if aadhaar_base64 else id_docs_sample.get("aadhaar_doc")
    selfie_doc = {"image_base64": selfie_base64} if selfie_base64 else id_docs_sample.get("selfie_doc")
    if not aadhaar_doc:
        raise ValueError(f"Aadhaar image missing for lead {sample_id}")
    if not selfie_doc:
        raise ValueError(f"Selfie image missing for lead {sample_id}")

    return {
        "lead": lead_sample,
        "bureau_report": {
            "raw": bureau_sample.get("raw", bureau_sample),
            "normalized": bureau_sample.get("normalized"),
        },
        "bank_statement": bank_sample.get("transactions", bank_sample),
        "documents": {
            "aadhaar_doc": aadhaar_doc,
            "pan_doc": id_docs_sample.get("pan_doc"),
            "selfie_doc": selfie_doc,
            "payslip_doc": payslip_sample.get("payslip_doc") or {"parsed_json": payslip_sample},
        },
    }


if lead_button:
    try:
        config = st.session_state.config_override
        lead_results = []
        for lead in lead_samples:
            result = run_lead_sourcing(lead, config, {})
            lead_results.append({"lead": lead, "result": result})
        st.session_state.lead_results = lead_results
        st.session_state.filtered_leads = [
            item["lead"] for item in lead_results if item["result"]["output"].get("selected")
        ]
        st.session_state.refresh_token = str(uuid4())
    except Exception as exc:
        st.sidebar.error(f"Lead sourcing failed: {exc}")

    


input_tab, live_tab, trace_tab, decision_tab, review_tab, logs_tab, checkpoints_tab = st.tabs(
    ["Input JSON", "Sales Agent Live Run", "Agent Trace", "Final Decision", "Human Review Queue", "Logs", "Checkpoints"]
)

with input_tab:
    st.subheader("Lead Sourcing Results")
    lead_results = st.session_state.get("lead_results")
    if lead_results:
        for item in lead_results:
            lead = item["lead"]
            result = item["result"]
            status = "selected" if result["output"].get("selected") else "rejected"
            st.write(f"{lead.get('lead_id')} | {lead.get('name')} | {status}")
    else:
        st.info("Run Lead Sourcing to view filtered leads.")

    st.subheader("Select Lead for Sales Agent")
    filtered = st.session_state.get("filtered_leads") or []
    if filtered:
        lead_ids = [lead.get("lead_id") for lead in filtered]
        selected_lead_id = st.selectbox("Lead ID", lead_ids)
        st.session_state.selected_lead_id = selected_lead_id
        st.json(next(lead for lead in filtered if lead.get("lead_id") == selected_lead_id))
    else:
        st.info("No filtered leads yet. Run Lead Sourcing.")

    st.subheader("Input Payload (Last Run)")
    if "last_input" in st.session_state:
        st.json(st.session_state.last_input)

with live_tab:
    st.subheader("Sales Agent Live Run")
    selected_lead_id = st.session_state.get("selected_lead_id") or selected_sample
    st.write(f"Selected lead: {selected_lead_id}")

    run_sales = st.button("Run Sales Agent", key="run_sales_btn")
    if run_sales:
        run_id = str(uuid4())
        thread_id = selected_lead_id or str(uuid4())

        try:
            application_payload = build_application_payload(selected_lead_id or selected_sample)
            application = LoanApplicationInput.model_validate(application_payload)
            prompts = load_prompts(prompt_dir)
        except Exception as exc:
            st.error(f"Failed to prepare input: {exc}")
            st.stop()

        config = st.session_state.config_override
        case_id = compute_case_id(application_payload)
        logger = setup_logger(run_id=run_id, thread_id=thread_id, case_id=case_id)

        checkpoint_path = Path(__file__).resolve().parent / "runs" / "checkpoints.db"
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpointer = get_sqlite_checkpointer(checkpoint_path, logger=logger)
        if checkpointer.__class__.__name__ == "InMemorySaver":
            st.warning("SQLite checkpointing unavailable; using in-memory checkpoints for this run.")

        set_runtime_logger(logger)
        graph = build_graph(checkpointer)
        state = {
            "run_id": run_id,
            "thread_id": thread_id,
            "case_id": case_id,
            "input": application.model_dump(),
            "config": config,
            "prompts": prompts,
            "results": {},
            "traces": {},
        }

        progress = st.progress(0.0)
        status_placeholder = st.empty()
        log_placeholder = st.empty()
        final_state = None

        try:
            for step_state in graph.stream(state, config={"configurable": {"thread_id": thread_id}}, stream_mode="values"):
                final_state = step_state
                results = step_state.get("results", {}) if isinstance(step_state, dict) else {}
                completed = len([agent for agent in AGENT_ORDER if agent in results])
                progress.progress(min(1.0, completed / len(AGENT_ORDER)))

                with status_placeholder.container():
                    for agent in AGENT_ORDER:
                        result = results.get(agent)
                        if not result:
                            st.write(f"⏳ {agent}: pending")
                            continue
                        status = result.get("status")
                        icon = "✅" if status == "ok" else "⚠️" if status == "insufficient_data" else "❌"
                        summary = summarize_agent_output(agent, result)
                        st.write(f"{icon} {agent}: {status} | {summary}")

                log_path = Path("runs") / f"{case_id}_{run_id}.jsonl"
                if log_path.exists():
                    log_placeholder.code(tail_lines(log_path), language="json")
        except Exception as exc:
            st.error(f"Pipeline failed: {exc}")
            st.stop()

        if final_state:
            write_run_artifacts(final_state, case_id, run_id, thread_id)
            st.session_state.last_run_id = run_id
            st.session_state.last_thread_id = thread_id
            st.session_state.last_case_id = final_state.get("case_id") or case_id
            st.session_state.last_state = final_state
            st.session_state.last_input = application_payload
            st.session_state.last_prompts = prompts
            st.session_state.refresh_token = str(uuid4())
with trace_tab:
    state = st.session_state.get("last_state")
    if not state:
        st.info("Run the pipeline to view traces.")
    else:
        traces = state.get("traces", {})
        if not traces:
            st.warning("No traces recorded.")
        else:
            for agent_name, trace in traces.items():
                with st.expander(f"{agent_name}"):
                    st.write(f"Status: {trace.get('output_snapshot', {}).get('status')}")
                    st.write(f"Duration (ms): {trace.get('duration_ms')}")
                    st.subheader("Input Snapshot")
                    st.json(trace.get("input_snapshot", {}))
                    st.subheader("Output")
                    st.json(trace.get("output_snapshot", {}))
                    st.subheader("Rationale Summary")
                    for item in trace.get("output_snapshot", {}).get("rationale_summary", []):
                        st.markdown(f"- {item}")
                    st.subheader("Evidence")
                    st.json(trace.get("output_snapshot", {}).get("evidence", {}))
                    st.subheader("Calculations")
                    st.json(trace.get("output_snapshot", {}).get("calculations", {}))
                    st.subheader("Missing Data")
                    st.json(trace.get("output_snapshot", {}).get("missing_data", []))
                    st.subheader("Confidence")
                    st.write(trace.get("output_snapshot", {}).get("confidence"))
                    st.subheader("Prompt Meta")
                    st.json(trace.get("prompt_meta", {}))
                    st.subheader("Tool Calls")
                    st.json(trace.get("tool_calls", []))

with decision_tab:
    state = st.session_state.get("last_state")
    if not state:
        st.info("Run the pipeline to view final decision.")
    else:
        approval = state.get("results", {}).get("approval", {})
        st.json(approval)
        if state.get("review_packet"):
            st.subheader("Review Packet")
            st.json(state.get("review_packet"))

with review_tab:
    review_files = list_review_files()
    if not review_files:
        st.info("No human review cases found.")
    else:
        table_rows = []
        for path in review_files:
            payload = parse_review_file(path)
            review_packet = payload.get("review_packet", {})
            case_id = review_packet.get("case_id") or "unknown"
            run_id = review_packet.get("run_id") or "unknown"
            reasons = ", ".join(review_packet.get("reasons", []) or review_packet.get("missing_data", []))
            created_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
            table_rows.append({
                "case_id": case_id,
                "run_id": run_id,
                "created_at": created_at,
                "reasons": reasons,
                "file": str(path),
            })

        st.dataframe(table_rows, use_container_width=True, hide_index=True)

        selection = st.selectbox("Select case", table_rows, format_func=lambda row: f"{row['case_id']} | {row['run_id']}")
        if selection:
            payload = parse_review_file(Path(selection["file"]))
            st.subheader("Review Packet")
            st.json(payload.get("review_packet", {}))
            st.subheader("Agent Outputs")
            review_packet = payload.get("review_packet", {})
            state_path = Path("runs") / f"{review_packet.get('case_id')}_{review_packet.get('run_id')}_STATE.json"
            if state_path.exists():
                try:
                    full_state = json.loads(state_path.read_text(encoding="utf-8"))
                    st.json(full_state.get("results", {}))
                except Exception:
                    st.json(review_packet.get("agent_statuses", {}))
            else:
                st.json(review_packet.get("agent_statuses", {}))

            st.markdown("### Human Decision")
            decision = st.selectbox("Decision", ["approve", "reject", "request_more_info"], key="human_decision")
            override_amount = st.number_input("Override sanctioned_amount", min_value=0.0, value=0.0, step=1000.0)
            override_roi = st.number_input("Override roi", min_value=0.0, value=0.0, step=0.01)
            notes = st.text_area("Notes")

            if st.button("Save decision"):
                case_id = selection["case_id"]
                run_id = selection["run_id"]
                recommended_terms = review_packet.get("recommended_terms") or {}
                final_terms = {
                    "sanctioned_amount": override_amount if override_amount > 0 else recommended_terms.get("sanctioned_amount"),
                    "roi": override_roi if override_roi > 0 else recommended_terms.get("roi"),
                }
                final_decision = {
                    "decision": "approved" if decision == "approve" else "rejected" if decision == "reject" else "human_review_required",
                    "sanctioned_amount": final_terms.get("sanctioned_amount"),
                    "roi": final_terms.get("roi"),
                    "reasons": review_packet.get("reasons", []),
                    "notes": notes,
                }
                decision_payload = {
                    "case_id": case_id,
                    "run_id": run_id,
                    "human_decision": decision,
                    "final_decision": final_decision,
                    "notes": notes,
                    "timestamp": datetime.now().isoformat(),
                }
                save_decision(case_id, run_id, decision_payload)
                st.success("Decision saved.")
                st.session_state.refresh_token = str(uuid4())

with logs_tab:
    run_id = st.session_state.get("last_run_id")
    case_id = st.session_state.get("last_case_id")
    if not run_id or not case_id:
        st.info("Run the pipeline to view logs.")
    else:
        log_path = Path("runs") / f"{case_id}_{run_id}.jsonl"
        if log_path.exists():
            if st.button("Refresh logs"):
                st.experimental_rerun()
            st.code(log_path.read_text(encoding="utf-8"), language="json")
        else:
            st.warning("Log file not found yet.")

with checkpoints_tab:
    thread_id = st.session_state.get("last_thread_id")
    if not thread_id:
        st.info("Run the pipeline to view checkpoints.")
    else:
        checkpoint_path = Path(__file__).resolve().parent / "runs" / "checkpoints.db"
        if not checkpoint_path.exists():
            st.warning("Checkpoint DB not found yet.")
        else:
            checkpointer = get_sqlite_checkpointer(checkpoint_path)
            checkpoints = list_checkpoints(checkpointer, thread_id)
            if not checkpoints:
                st.info("No checkpoints for this thread.")
            else:
                indices = list(range(len(checkpoints)))
                idx = st.selectbox("Checkpoint", indices)
                checkpoint = checkpoints[idx]
                state = getattr(checkpoint, "state", None)
                if state is None and isinstance(checkpoint, dict):
                    state = checkpoint.get("state")
                st.json(state or {})

                if st.button("Load final state"):
                    final_state = load_final_state(checkpointer, thread_id)
                    st.json(final_state)
