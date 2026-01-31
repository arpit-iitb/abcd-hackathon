import argparse
import json
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from .core.config_loader import load_yaml
from .core.logging import get_logger, log_event
from .core.models import ApplicationInput, ErrorDetail
from .core.validation import validate_model
from .graph import build_graph


def error_response(run_id: str, thread_id: str, errors):
    return {
        "run_id": run_id,
        "thread_id": thread_id,
        "status": "error",
        "errors": [error.model_dump() if hasattr(error, "model_dump") else error for error in errors],
        "outputs": {},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to application JSON")
    parser.add_argument("--config", default=str(Path("configs") / "thresholds.yaml"))
    parser.add_argument("--prompts", default=str(Path("prompts") / "agents.yaml"))
    parser.add_argument("--checkpoint", default=str(Path("data") / "checkpoints.db"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--thread-id", default=None)
    args = parser.parse_args()

    run_id = args.run_id or str(uuid4())
    thread_id = args.thread_id or str(uuid4())

    logger = get_logger()

    try:
        config = load_yaml(args.config)
        prompts = load_yaml(args.prompts)
        input_data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except Exception as exc:
        error = ErrorDetail(code="load_error", message=str(exc), field="")
        print(json.dumps(error_response(run_id, thread_id, [error])))
        return 1

    parsed, errors = validate_model(ApplicationInput, input_data)
    if errors:
        print(json.dumps(error_response(run_id, thread_id, errors)))
        return 1

    checkpoint_path = Path(args.checkpoint).resolve().as_posix()
    checkpointer = SqliteSaver.from_conn_string(f"sqlite:///{checkpoint_path}")

    app = build_graph(config, prompts, checkpointer)
    initial_state = {
        "run_id": run_id,
        "thread_id": thread_id,
        "input": input_data,
        "outputs": {},
        "errors": [],
    }

    log_event(logger, "pipeline_start", "Pipeline invocation", run_id, thread_id, payload={"input_path": args.input})
    try:
        final_state = app.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})
    except Exception as exc:
        error = ErrorDetail(code="runtime_error", message=str(exc), field="")
        print(json.dumps(error_response(run_id, thread_id, [error])))
        return 1

    outputs = final_state.get("outputs", {})
    approval = outputs.get("approval", {})
    status = approval.get("decision", approval.get("status", "unknown"))

    response = {
        "run_id": run_id,
        "thread_id": thread_id,
        "status": status,
        "outputs": outputs,
    }
    print(json.dumps(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
