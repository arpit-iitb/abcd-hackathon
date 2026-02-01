from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from uuid import uuid4

import streamlit as st

from agents.lead_sourcing import run_lead_sourcing
from app.checkpoint_utils import get_sqlite_checkpointer
from app.config import load_config_dir
from app.graph import build_graph, set_runtime_logger
from app.json_utils import load_json
from app.logging_setup import setup_logger
from app.openai_client import has_api_key
from app.prompt_loader import load_prompts
from app.reporting import compute_case_id, write_run_artifacts
from app.state import LoanApplicationInput
from app.utils.image_utils import load_image_base64
from app.utils.data_fetch import build_application_payload_with_fallback


st.set_page_config(page_title="ABCD Demo", layout="wide")


def inject_theme() -> None:
    st.markdown(
        """
<style>
  .stApp {
    background: #f4f9ff;
    color: #0d223d;
  }
  header {visibility: hidden;}
  section[data-testid="stSidebar"] {display:none;}
  .block-container {padding-top: 0rem;}
  .demo-nav {
    background: #0e4a7b;
    color: #ffffff;
    padding: 18px 36px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid rgba(255,255,255,0.08);
  }
  .demo-nav .brand {
    font-weight: 700;
    letter-spacing: 0.6px;
    font-size: 18px;
  }
  .demo-nav .links span {
    margin: 0 14px;
    font-size: 14px;
    opacity: 0.9;
  }
  .demo-nav a {
    color: #e7f1ff;
    text-decoration: none;
    margin: 0 12px;
    font-size: 14px;
    font-weight: 500;
  }
  .demo-hero {
    background: linear-gradient(90deg, #dff0ff 0%, #ecf7ff 45%, #f4f9ff 100%);
    padding: 40px 60px;
    border-radius: 0 0 24px 24px;
    display: flex;
    gap: 36px;
    align-items: center;
  }
  .hero-title {
    font-size: 40px;
    font-weight: 700;
    color: #0d223d;
    margin-bottom: 12px;
  }
  .hero-sub {
    font-size: 16px;
    color: #3c5670;
    max-width: 520px;
  }
  .cta-btn {
    background: #ef6c24;
    color: white;
    padding: 12px 22px;
    border-radius: 10px;
    font-weight: 600;
    display: inline-block;
    margin-top: 18px;
  }
  .stButton > button {
    background: #ef6c24;
    color: #ffffff !important;
    border: none;
    border-radius: 10px;
    padding: 10px 18px;
    font-weight: 600;
  }
  .stButton > button:hover {
    background: #e05f1c;
    color: #ffffff !important;
  }
  .stProgress > div > div > div > div {
    background-color: #1b6fb7;
  }
  .stAlert {
    color: #0d223d;
  }
  .section-title, h3, h4, h5, h6 {
    color: #0d223d;
  }
  /* Tabs header visibility */
  [data-testid="stTabs"] button {
    color: #0d223d !important;
  }
  [data-testid="stTabs"] [data-baseweb="tab"] span {
    color: #0d223d !important;
  }
  [data-testid="stTabs"] [aria-selected="true"] {
    color: #0d223d !important;
    font-weight: 700;
  }
  [data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: transparent;
  }
  .status-pill {
    color: #0d223d;
  }
  .brand-title {
    font-size: 40px;
    font-weight: 700;
    text-align: center;
    margin: 12px 0 2px 0;
    color: #0d223d;
    letter-spacing: 1px;
  }
  .brand-sub {
    font-size: 18px;
    text-align: center;
    color: #39536c;
    margin-bottom: 28px;
  }
  .lead-card {
    background: white;
    border-radius: 16px;
    padding: 16px;
    min-height: 160px;
    box-shadow: 0 12px 30px rgba(20, 20, 50, 0.08);
    display: flex;
    align-items: center;
    justify-content: space-between;
    border: 1px solid rgba(30,30,60,0.06);
  }
  .lead-name {
    font-size: 20px;
    font-weight: 600;
    color: #1f1f33;
    margin-bottom: 6px;
  }
  .lead-meta {
    font-size: 13px;
    color: #4b4b68;
    margin-bottom: 4px;
  }
  .lead-photo img {
    width: 88px;
    height: 110px;
    border-radius: 12px;
    object-fit: cover;
    border: 1px solid rgba(20,20,40,0.08);
  }
  .section-title {
    font-size: 20px;
    font-weight: 600;
    color: #0d223d;
    margin: 10px 0;
  }
  .status-pill {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    margin-left: 8px;
  }
  .pill-ok { background: #dff7ea; color: #0f6d3b; }
  .pill-warn { background: #fff0cc; color: #7a4a00; }
  .pill-err { background: #ffd9d9; color: #8c1b1b; }
  .metric-card {
    background: white;
    border-radius: 16px;
    padding: 16px;
    box-shadow: 0 10px 25px rgba(20, 20, 50, 0.06);
    min-height: 120px;
  }
  .summary-card {
    border-radius: 16px;
    padding: 16px;
    box-shadow: 0 10px 25px rgba(20, 20, 50, 0.06);
    min-height: 110px;
    margin-bottom: 12px;
  }
  .summary-ok { background: #e8fff1; border: 1px solid #bfead2; }
  .summary-warn { background: #fff4cc; border: 1px solid #f1d48a; }
  .summary-risk { background: #ffe7cc; border: 1px solid #f5c18a; }
  .summary-danger { background: #ffd6d6; border: 1px solid #f1a7a7; }
  [data-testid="stExpander"] summary {
    background: #111827 !important;
    color: #ffffff !important;
  }
  [data-testid="stExpander"] summary span {
    color: #ffffff !important;
  }
  .flow-container {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    margin: 12px 0 18px 0;
  }
  .flow-node {
    padding: 6px 12px;
    border-radius: 999px;
    background: #ffffff;
    border: 1px solid #d7e3f1;
    font-size: 12px;
    font-weight: 600;
    color: #39536c;
    white-space: nowrap;
  }
  .flow-node.done {
    background: #e8fff1;
    border-color: #bfead2;
    color: #0f6d3b;
  }
  .flow-node.active {
    background: #e6f0ff;
    border-color: #b3c7ff;
    color: #1a3d7c;
  }
  .flow-connector {
    position: relative;
    width: 56px;
    height: 6px;
    background: #cfd8e3;
    border-radius: 999px;
    overflow: hidden;
  }
  .flow-connector::after {
    content: "";
    position: absolute;
    right: -6px;
    top: -3px;
    border-top: 6px solid transparent;
    border-bottom: 6px solid transparent;
    border-left: 6px solid #cfd8e3;
  }
  .flow-connector .flow-fill {
    position: absolute;
    left: 0;
    top: 0;
    height: 100%;
    width: 0;
    background: #22c55e;
    border-radius: 999px;
    animation: flowFill 1.6s ease-in-out infinite;
    display: none;
  }
  .flow-connector.active .flow-fill {
    display: block;
  }
  .flow-connector.active::after {
    border-left-color: #22c55e;
  }
  .selected-lead {
    background: #d1f7e3;
    color: #0f5132;
    border: 1px solid #a7e3c8;
    padding: 12px 16px;
    border-radius: 12px;
    font-weight: 600;
  }
  @keyframes flowFill {
    0% { width: 0; }
    50% { width: 100%; }
    100% { width: 0; }
  }
</style>
""",
        unsafe_allow_html=True,
    )


def load_samples(path: str) -> List[Dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, list):
        return payload
    return [payload]


def image_b64_from_path(path: str) -> str:
    try:
        return load_image_base64(path)
    except Exception:
        return ""


def get_selfie_b64(lead_id: str, id_docs_samples: List[Dict[str, Any]]) -> str:
    for doc in id_docs_samples:
        if doc.get("lead_id") == lead_id:
            path = doc.get("selfie_image_file") or (doc.get("selfie_doc") or {}).get("image_path")
            return image_b64_from_path(path)
    return ""


def build_company_map(payslip_samples: List[Dict[str, Any]]) -> Dict[str, str]:
    mapping = {}
    for sample in payslip_samples:
        parsed = (sample.get("payslip_doc") or {}).get("parsed_json") or {}
        name = parsed.get("employer_name") or parsed.get("employer") or "Unknown"
        mapping[sample.get("lead_id")] = name
    return mapping


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
    if agent_name == "web_search":
        return output.get("summary") or "web_search_complete"
    if agent_name == "fraud":
        return f"fraud_grade={output.get('fraud_grade')}"
    if agent_name == "risk_assessment":
        return f"risk={output.get('final_risk_grade')}"
    if agent_name == "approval":
        return f"decision={output.get('decision')}, sanctioned={output.get('sanctioned_amount')}"
    return ""


def render_flow_html(agent_order: List[str], results: Dict[str, Any]) -> str:
    completed = len([agent for agent in agent_order if agent in results])
    active_connector = completed - 1 if 0 < completed < len(agent_order) else None
    current_index = completed if completed < len(agent_order) else len(agent_order) - 1

    parts = ["<div class='flow-container'>"]
    for idx, agent in enumerate(agent_order):
        status_class = ""
        if idx < completed:
            status_class = "done"
        elif idx == current_index and completed < len(agent_order):
            status_class = "active"
        label = agent.replace("_", " ").title()
        parts.append(f"<div class='flow-node {status_class}'>{label}</div>")
        if idx < len(agent_order) - 1:
            connector_class = "flow-connector"
            if active_connector == idx:
                connector_class += " active"
            parts.append(f"<div class='{connector_class}'><span class='flow-fill'></span></div>")
    parts.append("</div>")
    return "".join(parts)


def render_lead_card(lead: Dict[str, Any], company: str, image_b64: str) -> None:
    amount = lead.get("requested_amount")
    amount_text = f"INR {amount:,.0f}" if isinstance(amount, (int, float)) else "INR -"
    tier = lead.get("tier", "-")
    photo_html = (
        f'<img src="data:image/jpeg;base64,{image_b64}" />' if image_b64 else '<div style="width:88px;height:110px;border-radius:12px;border:1px dashed #c9c9dc;"></div>'
    )
    st.markdown(
        f"""
<div class="lead-card">
  <div>
    <div class="lead-name">{lead.get("name","Unknown")}</div>
    <div class="lead-meta">Requested: {amount_text}</div>
    <div class="lead-meta">City Tier: {tier}</div>
    <div class="lead-meta">Company: {company}</div>
  </div>
  <div class="lead-photo">{photo_html}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def build_application_payload(sample_id: str, sample_dir: str, config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    payload, fallbacks = build_application_payload_with_fallback(sample_dir, sample_id, config)
    return payload, fallbacks


def summarize_status(status: str) -> str:
    if status == "ok":
        return "pill-ok"
    if status == "insufficient_data":
        return "pill-warn"
    return "pill-err"


def live_run(graph, state: Dict[str, Any], thread_id: str, log_container) -> Dict[str, Any]:
    progress = st.progress(0.0)
    status_placeholder = st.empty()
    flow_placeholder = st.empty()
    log_placeholder = log_container.empty()
    log_messages: List[str] = []
    final_state = None
    agent_order = [
        "lead_sourcing",
        "bureau",
        "bank_statement",
        "id_verification",
        "payslip",
        "fraud",
        "risk_assessment",
        "approval",
    ]

    for step_state in graph.stream(state, config={"configurable": {"thread_id": thread_id}}, stream_mode="values"):
        final_state = step_state
        results = step_state.get("results", {}) if isinstance(step_state, dict) else {}
        completed = len([agent for agent in agent_order if agent in results])
        progress.progress(min(1.0, completed / len(agent_order)))

        with status_placeholder.container():
            flow_placeholder.markdown(render_flow_html(agent_order, results), unsafe_allow_html=True)
            for agent in agent_order:
                result = results.get(agent)
                if not result:
                    st.write(f"⏳ {agent}: pending")
                    continue
                status = result.get("status")
                pill = summarize_status(status)
                st.markdown(f"<span class='status-pill {pill}'>{status}</span> {agent}", unsafe_allow_html=True)

        if results:
            latest_agent = [agent for agent in agent_order if agent in results][-1]
            latest_result = results.get(latest_agent, {})
            summary = summarize_agent_output(latest_agent, latest_result)
            log_messages.append(f"{latest_agent}: {summary}")
            log_html = "<br>".join(log_messages[-12:])
            log_placeholder.markdown(
                f"<div class='metric-card' style='max-height:320px; overflow:auto;'><strong>Live Agent Feed</strong><br>{log_html}</div>",
                unsafe_allow_html=True,
            )

    return final_state or {}


inject_theme()

if not has_api_key():
    st.warning("OPENAI_API_KEY is missing. Copy .env.example to .env and set your key.")

config_dir = "configs"
prompt_dir = "prompts"
sample_dir = "data"

if "page" not in st.session_state:
    st.session_state.page = "landing"

if "config_override" not in st.session_state:
    try:
        st.session_state.config_override = load_config_dir(config_dir)
    except Exception as exc:
        st.session_state.config_override = {}
        st.sidebar.error(f"Config load error: {exc}")

try:
    lead_samples = load_samples(f"{sample_dir}/lead_samples.json")
    id_docs_samples = load_samples(f"{sample_dir}/id_docs_samples.json")
    payslip_samples = load_samples(f"{sample_dir}/payslip_samples.json")
except Exception as exc:
    st.error(f"Failed to load samples: {exc}")
    st.stop()

company_map = build_company_map(payslip_samples)

st.markdown(
    """
<div class="demo-nav">
  <div class="brand">ABCD - AnyBody Can Disburse</div>
  <div class="links">
    <a href="#lead-sourcing">Lead Sourcing</a>
    <a href="#sales-agent">Sales Agent</a>
    <a href="#agent-outputs">Agent Outputs</a>
    <a href="#agent-trace">Detailed Traces</a>
    <a href="#final-decision">Final Decision</a>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

if st.session_state.page == "landing":
    st.markdown(
        """
<div class="demo-hero">
  <div>
    <div class="hero-title">Instant Personal Loan Online</div>
    <div class="hero-sub">
      ABCD powers a multi-agent lending workflow to source high-quality leads, verify identities,
      and accelerate approvals for real-world disbursements.
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.write("")
    if st.button("Run Lead Sourcing", use_container_width=True):
        with st.spinner("Loading the most optimal leads for you..."):
            time.sleep(0.8)
            lead_results = []
            config = st.session_state.config_override
            for lead in lead_samples:
                result = run_lead_sourcing(lead, config, {})
                lead_results.append({"lead": lead, "result": result})
            st.session_state.lead_results = lead_results
            st.session_state.page = "leads"
        if hasattr(st, "rerun"):
            st.rerun()
        else:
            st.experimental_rerun()

if st.session_state.page == "leads":
    st.markdown("<div id='lead-sourcing'></div>", unsafe_allow_html=True)
    st.markdown("<div class='brand-title'>ABCD</div>", unsafe_allow_html=True)
    st.markdown("<div class='brand-sub'>AnyBody Can Disburse</div>", unsafe_allow_html=True)

    lead_results = st.session_state.get("lead_results", [])
    selected = [item for item in lead_results if item["result"]["output"].get("selected")]
    rejected = [item for item in lead_results if not item["result"]["output"].get("selected")]

    st.markdown("<div class='section-title'>Selected Leads</div>", unsafe_allow_html=True)
    if not selected:
        st.info("No leads selected.")
    else:
        for i in range(0, len(selected), 3):
            row = selected[i : i + 3]
            cols = st.columns(3)
            for col, item in zip(cols, row):
                with col:
                    lead = item["lead"]
                    photo_b64 = get_selfie_b64(lead.get("lead_id"), id_docs_samples)
                    render_lead_card(lead, company_map.get(lead.get("lead_id"), "Unknown"), photo_b64)
                    if st.button("Select", key=f"select_{lead.get('lead_id')}"):
                        st.session_state.selected_lead_id = lead.get("lead_id")

    st.markdown("<div class='section-title'>Rejected Leads</div>", unsafe_allow_html=True)
    if not rejected:
        st.info("No rejected leads.")
    else:
        for i in range(0, len(rejected), 3):
            row = rejected[i : i + 3]
            cols = st.columns(3)
            for col, item in zip(cols, row):
                with col:
                    lead = item["lead"]
                    photo_b64 = get_selfie_b64(lead.get("lead_id"), id_docs_samples)
                    render_lead_card(lead, company_map.get(lead.get("lead_id"), "Unknown"), photo_b64)

    st.markdown("<div id='sales-agent'></div>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Sales Agent</div>", unsafe_allow_html=True)
    selected_lead_id = st.session_state.get("selected_lead_id")
    if not selected_lead_id:
        st.info("Select a lead to run the Sales Agent.")
    else:
        st.markdown(f"<div class='selected-lead'>Selected lead: {selected_lead_id}</div>", unsafe_allow_html=True)
        if st.button("Run Sales Agent", key="run_sales_agent"):
            run_id = str(uuid4())
            thread_id = selected_lead_id
            config = st.session_state.config_override
            prompts = load_prompts(prompt_dir)
            application_payload, fallbacks = build_application_payload(selected_lead_id, sample_dir, config)
            application = LoanApplicationInput.model_validate(application_payload)
            case_id = compute_case_id(application_payload)
            logger = setup_logger(run_id=run_id, thread_id=thread_id, case_id=case_id)
            checkpoint_path = Path(__file__).resolve().parent / "runs" / "checkpoints.db"
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpointer = get_sqlite_checkpointer(checkpoint_path, logger=logger)

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
                "run_meta": {"fallbacks": fallbacks or []},
            }

            run_cols = st.columns([2, 1])
            with run_cols[1]:
                st.markdown("<div id='live-feed'></div>", unsafe_allow_html=True)
                feed_container = st.container()
            with run_cols[0]:
                final_state = live_run(graph, state, thread_id, feed_container)
            write_run_artifacts(final_state, case_id, run_id, thread_id)

            approval = final_state.get("results", {}).get("approval", {}) if isinstance(final_state, dict) else {}
            decision = approval.get("output", {}).get("decision")
            sanctioned = approval.get("output", {}).get("sanctioned_amount")
            roi = approval.get("output", {}).get("roi")

            tabs = st.tabs(["Final Decision", "Agent Outputs", "Detailed Traces"])
            with tabs[0]:
                st.markdown("<div id='final-decision'></div>", unsafe_allow_html=True)
                st.markdown("<div class='section-title'>Decision</div>", unsafe_allow_html=True)
                metric_cols = st.columns(3)
                metric_cols[0].markdown(f"<div class='metric-card'><strong>Decision</strong><br>{decision}</div>", unsafe_allow_html=True)
                metric_cols[1].markdown(f"<div class='metric-card'><strong>Sanctioned</strong><br>{sanctioned}</div>", unsafe_allow_html=True)
                metric_cols[2].markdown(f"<div class='metric-card'><strong>ROI</strong><br>{roi}</div>", unsafe_allow_html=True)

            with tabs[1]:
                st.markdown("<div id='agent-outputs'></div>", unsafe_allow_html=True)
                st.markdown("<div class='section-title'>Agent Outputs</div>", unsafe_allow_html=True)
                results = final_state.get("results", {}) if isinstance(final_state, dict) else {}
                fraud_output = (results.get("fraud") or {}).get("output", {}) if isinstance(results, dict) else {}
                web_search_output = fraud_output.get("web_search", {}) if isinstance(fraud_output, dict) else {}
                web_summary = web_search_output.get("summary")
                web_sources = web_search_output.get("sources") or []
                if web_summary:
                    sources_html = ""
                    if isinstance(web_sources, list) and web_sources:
                        links = []
                        for source in web_sources[:3]:
                            if not isinstance(source, dict):
                                continue
                            title = source.get("title") or source.get("url") or "source"
                            url = source.get("url")
                            if url:
                                links.append(f"<li><a href='{url}' target='_blank'>{title}</a></li>")
                        if links:
                            sources_html = "<ul>" + "".join(links) + "</ul>"
                    st.markdown(
                        f"<div class='summary-card summary-ok'><strong>Web Search Summary</strong><br>{web_summary}{sources_html}</div>",
                        unsafe_allow_html=True,
                    )

                traces = final_state.get("traces", {}) if isinstance(final_state, dict) else {}
                keep_agents = {"fraud", "risk_assessment", "id_verification", "approval"}
                filtered = {k: v for k, v in traces.items() if k in keep_agents}
                if not filtered:
                    st.info("No agent outputs recorded for this run.")
                else:
                    for agent_name, trace in filtered.items():
                        output_snapshot = trace.get("output_snapshot", {}) if isinstance(trace, dict) else {}
                        output_only = output_snapshot.get("output", {})
                        summary = output_only.get("summary")
                        fraud_grade = output_only.get("fraud_grade")
                        decision = output_only.get("decision")
                        final_risk = output_only.get("final_risk_grade")
                        card_class = "summary-ok"
                        if decision == "human_review_required":
                            card_class = "summary-warn"
                        if fraud_grade == "suspicious":
                            card_class = "summary-danger"
                        if fraud_grade == "fraudulent":
                            card_class = "summary-danger"
                        if final_risk == "high":
                            card_class = "summary-risk"
                        with st.expander(agent_name.replace("_", " ").title()):
                            if summary:
                                st.markdown(
                                    f"<div class='summary-card {card_class}'><strong>Summary</strong><br>{summary}</div>",
                                    unsafe_allow_html=True,
                                )

            with tabs[2]:
                st.markdown("<div id='agent-trace'></div>", unsafe_allow_html=True)
                st.markdown("<div class='section-title'>Detailed Traces</div>", unsafe_allow_html=True)
                fallbacks = final_state.get("run_meta", {}).get("fallbacks", []) if isinstance(final_state, dict) else []
                if fallbacks:
                    st.warning("Fallbacks used:\n" + "\n".join(f"- {item}" for item in fallbacks))
                traces = final_state.get("traces", {}) if isinstance(final_state, dict) else {}
                if not traces:
                    st.info("No traces recorded yet.")
                else:
                    for agent_name, trace in traces.items():
                        with st.expander(agent_name.replace("_", " ").title()):
                            output_snapshot = trace.get("output_snapshot", {}) if isinstance(trace, dict) else {}
                            st.write(f"Status: {output_snapshot.get('status')}")
                            st.write(f"Duration (ms): {trace.get('duration_ms')}")
                            st.subheader("Input Snapshot")
                            st.json(trace.get("input_snapshot", {}))
                            st.subheader("Output")
                            st.json(output_snapshot)
                            st.subheader("Rationale Summary")
                            for item in output_snapshot.get("rationale_summary", []):
                                st.markdown(f"- {item}")
                            st.subheader("Evidence")
                            st.json(output_snapshot.get("evidence", {}))
                            st.subheader("Calculations")
                            st.json(output_snapshot.get("calculations", {}))
                            st.subheader("Missing Data")
                            st.json(output_snapshot.get("missing_data", []))
                            st.subheader("Confidence")
                            st.write(output_snapshot.get("confidence"))
                            st.subheader("Prompt Meta")
                            st.json(trace.get("prompt_meta", {}))
                            st.subheader("Tool Calls")
                            st.json(trace.get("tool_calls", []))
