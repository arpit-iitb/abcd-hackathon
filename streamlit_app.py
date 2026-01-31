import json
from pathlib import Path
from uuid import uuid4

import streamlit as st

from app.core.config_loader import load_yaml
from app.core.logging import get_logger, log_event
from app.core.models import ApplicationInput, ErrorDetail
from app.core.validation import validate_model
from app.graph import build_graph
from langgraph.checkpoint.sqlite import SqliteSaver


st.set_page_config(page_title="Agentic Loan Journey", layout="wide")

st.title("Agentic Loan Journey Demo")

config_path = st.sidebar.text_input("Config path", "configs/thresholds.yaml")
prompt_path = st.sidebar.text_input("Prompts path", "prompts/agents.yaml")
checkpoint_path = st.sidebar.text_input("Checkpoint DB", "data/checkpoints.db")

sample_files = sorted(Path("data").glob("*.json"))
selected = st.sidebar.selectbox("Sample input", [str(p) for p in sample_files], index=0 if sample_files else None)

input_json = "{}"
if selected:
    input_json = Path(selected).read_text(encoding="utf-8")

input_json = st.text_area("Application JSON", value=input_json, height=280)

if st.button("Run pipeline"):
    run_id = str(uuid4())
    thread_id = str(uuid4())
    logger = get_logger()

    try:
        config = load_yaml(config_path)
        prompts = load_yaml(prompt_path)
        payload = json.loads(input_json)
    except Exception as exc:
        st.error(f"Failed to load inputs: {exc}")
        st.stop()

    parsed, errors = validate_model(ApplicationInput, payload)
    if errors:
        st.error("Validation failed")
        st.json({"errors": [e.model_dump() for e in errors]})
        st.stop()

    checkpointer = SqliteSaver.from_conn_string(f"sqlite:///{Path(checkpoint_path).resolve().as_posix()}")
    app = build_graph(config, prompts, checkpointer)
    initial_state = {
        "run_id": run_id,
        "thread_id": thread_id,
        "input": payload,
        "outputs": {},
        "errors": [],
    }

    log_event(logger, "pipeline_start", "Streamlit pipeline invocation", run_id, thread_id, payload={"source": "streamlit"})

    try:
        final_state = app.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})
    except Exception as exc:
        error = ErrorDetail(code="runtime_error", message=str(exc), field="")
        st.error("Pipeline error")
        st.json({"error": error.model_dump()})
        st.stop()

    outputs = final_state.get("outputs", {})

    st.success("Pipeline complete")
    st.write(f"Run ID: {run_id}")
    st.write(f"Thread ID: {thread_id}")

    st.subheader("Outputs")
    st.json(outputs)

    for key, value in outputs.items():
        st.subheader(f"{key}")
        st.json(value)
