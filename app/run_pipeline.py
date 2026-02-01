import argparse
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
from app.utils.image_utils import load_image_base64


def parse_error(exc: ValidationError, run_id: str):
    return {
        "status": "error",
        "run_id": run_id,
        "errors": validation_error_to_dict(exc),
    }


def _build_application_payload(sample_dir: str, sample_id: str = None):
    lead_payload = load_json(f"{sample_dir}/lead_samples.json")
    bureau_payload = load_json(f"{sample_dir}/bureau_samples.json")
    bank_payload = load_json(f"{sample_dir}/bank_statement_samples.json")
    id_docs_payload = load_json(f"{sample_dir}/id_docs_samples.json")
    payslip_payload = load_json(f"{sample_dir}/payslip_samples.json")

    def select_sample(payload):
        if not isinstance(payload, list):
            return payload
        if sample_id is None:
            return payload[0]
        for item in payload:
            if item.get("lead_id") == sample_id:
                return item
        return payload[0]

    lead_sample = select_sample(lead_payload)
    bureau_sample = select_sample(bureau_payload)
    bank_sample = select_sample(bank_payload)
    id_docs_sample = select_sample(id_docs_payload)
    payslip_sample = select_sample(payslip_payload)

    aadhaar_path = id_docs_sample.get("aadhaar_image_file") or (id_docs_sample.get("aadhaar_doc") or {}).get("image_path")
    selfie_path = id_docs_sample.get("selfie_image_file") or (id_docs_sample.get("selfie_doc") or {}).get("image_path")
    aadhaar_base64 = load_image_base64(aadhaar_path)
    selfie_base64 = load_image_base64(selfie_path)
    aadhaar_doc = {"image_base64": aadhaar_base64} if aadhaar_base64 else id_docs_sample.get("aadhaar_doc")
    selfie_doc = {"image_base64": selfie_base64} if selfie_base64 else id_docs_sample.get("selfie_doc")

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
        application_payload = _build_application_payload(args.sample_dir, args.sample_id)
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
