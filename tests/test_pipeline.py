import json
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from app.core.config_loader import load_yaml
from app.graph import build_graph


def test_pipeline_runs():
    config = load_yaml("configs/thresholds.yaml")
    prompts = load_yaml("prompts/agents.yaml")
    payload = json.loads(Path("data/sample_application.json").read_text(encoding="utf-8"))

    checkpointer = SqliteSaver.from_conn_string(f"sqlite:///{Path('data/checkpoints.db').resolve().as_posix()}")
    app = build_graph(config, prompts, checkpointer)

    initial_state = {
        "run_id": str(uuid4()),
        "thread_id": str(uuid4()),
        "input": payload,
        "outputs": {},
        "errors": [],
    }

    final_state = app.invoke(initial_state, config={"configurable": {"thread_id": initial_state["thread_id"]}})
    outputs = final_state.get("outputs", {})
    assert "approval" in outputs
    assert outputs["approval"]["status"] in {"ok", "insufficient_data"}
