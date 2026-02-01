import argparse
from typing import Any, Dict
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import ValidationError

from app.config import load_config_dir
from app.graph import build_graph, set_runtime_logger
from app.json_utils import dump_json, load_json, validation_error_to_dict
from app.logging_setup import log_event, setup_logger
from app.prompt_loader import load_prompts, render_prompt
from app.state import LoanApplicationInput
from app.utils.masking import mask_sensitive
from app.checkpoint_utils import get_sqlite_checkpointer
from app.reporting import compute_case_id, write_run_artifacts
from app.utils.data_fetch import build_application_payload_with_fallback


def parse_error(exc: ValidationError, run_id: str):
    return {
        "status": "error",
        "run_id": run_id,
        "errors": validation_error_to_dict(exc),
    }


def _build_application_payload(sample_dir: str, sample_id: str | None, config: Dict[str, Any]):
    return build_application_payload_with_fallback(sample_dir, sample_id, config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Loan agentic pipeline")
    parser.add_argument("--config-dir", default="configs")
    parser.add_argument("--prompt-dir", default="prompts")
    parser.add_argument("--sample-dir", default="data")
    parser.add_argument("--sample_id", default=None)
    parser.add_argument("--preview-prompt", default=None, help="Agent name to render prompt and exit")
    parser.add_argument("--dump-state", action="store_true")
    parser.add_argument("--checkpoint-db", default="runs/checkpoints.db")
    args = parser.parse_args()

    load_dotenv()
    run_id = str(uuid4())
    thread_id = args.sample_id or str(uuid4())

    try:
        config = load_config_dir(args.config_dir)
        prompts = load_prompts(args.prompt_dir)
        application_payload, fallbacks = _build_application_payload(args.sample_dir, args.sample_id, config)
    except Exception as exc:
        print(dump_json({"status": "error", "run_id": run_id, "message": f"load_error: {exc}"}))
        return 1

    case_id = compute_case_id(application_payload)
    logger = setup_logger(run_id=run_id, thread_id=thread_id, case_id=case_id)

    if args.preview_prompt:
        masked_input = mask_sensitive(application_payload)
        system_prompt, user_prompt = render_prompt(
            prompts,
            args.preview_prompt,
            input_json=dump_json(masked_input),
            config_json=dump_json(config),
        )
        print("SYSTEM PROMPT:\n" + system_prompt)
        print("\nUSER PROMPT:\n" + user_prompt)
        return 0

    try:
        application = LoanApplicationInput.model_validate(application_payload)
    except ValidationError as exc:
        print(dump_json(parse_error(exc, run_id)))
        return 1

    base_dir = Path(__file__).resolve().parent.parent
    checkpoint_path = Path(args.checkpoint_db)
    if not checkpoint_path.is_absolute():
        checkpoint_path = base_dir / checkpoint_path
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpointer = get_sqlite_checkpointer(checkpoint_path, logger=logger)

    graph = build_graph(checkpointer)

    set_runtime_logger(logger)
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

    log_event(logger, "pipeline start", run_id, thread_id, "pipeline_start", case_id=case_id)
    result_state = graph.invoke(state, config={"configurable": {"thread_id": thread_id}})

    approval = result_state.get("results", {}).get("approval", {})
    decision = approval.get("output", {}).get("decision") if isinstance(approval, dict) else None

    response = {
        "run_id": run_id,
        "thread_id": thread_id,
        "case_id": case_id,
        "decision": decision,
        "approval": approval,
    }

    print(dump_json(response))

    write_run_artifacts(result_state, case_id, run_id, thread_id)

    if decision == "human_review_required":
        review_packet = result_state.get("review_packet", {})
        case_id = review_packet.get("case_id") or thread_id
        review_path = Path("runs") / f"{case_id}_{run_id}_HUMAN_REVIEW.json"
        review_payload = {
            "decision": decision,
            "review_packet": review_packet,
        }
        review_path.write_text(dump_json(review_payload), encoding="utf-8")
        print(dump_json({"human_review_required": True, "review_file": str(review_path)}))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
