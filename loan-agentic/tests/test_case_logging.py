from pathlib import Path

from app.checkpoint_utils import get_sqlite_checkpointer
from app.config import load_config_dir
from app.graph import build_graph, set_runtime_logger
from app.json_utils import load_json
from app.logging_setup import setup_logger
from app.reporting import write_run_artifacts
from app.state import LoanApplicationInput


def test_case_logging_files_created():
    config = load_config_dir("configs")
    payload = {
        "lead": load_json("data/lead_samples.json")[0],
        "bureau_report": load_json("data/bureau_samples.json")[0],
        "bank_statement": load_json("data/bank_statement_samples.json")[0]["transactions"],
        "documents": {
            "aadhaar_doc": load_json("data/id_docs_samples.json")[0]["aadhaar_doc"],
            "pan_doc": load_json("data/id_docs_samples.json")[0]["pan_doc"],
            "selfie_doc": load_json("data/id_docs_samples.json")[0]["selfie_doc"],
            "payslip_doc": load_json("data/payslip_samples.json")[0]["payslip_doc"],
        },
    }
    application = LoanApplicationInput.model_validate(payload)
    checkpointer = get_sqlite_checkpointer("runs/test_checkpoints_case.db")
    run_id = "run-test"
    thread_id = "thread-test"
    case_id = "case-test"
    logger = setup_logger(run_id=run_id, thread_id=thread_id, case_id=case_id)
    set_runtime_logger(logger)
    graph = build_graph(checkpointer)

    state = {
        "run_id": run_id,
        "thread_id": thread_id,
        "case_id": case_id,
        "input": application.model_dump(),
        "config": config,
        "prompts": {},
        "results": {},
        "traces": {},
    }

    result = graph.invoke(state, config={"configurable": {"thread_id": thread_id}})
    artifacts = write_run_artifacts(result, case_id, run_id, thread_id)

    assert artifacts["report"].exists()
    assert artifacts["decision"].exists()

    base_logger = logger.logger if hasattr(logger, "logger") else logger
    for handler in list(base_logger.handlers):
        handler.close()
        base_logger.removeHandler(handler)

    # Clean up created files
    Path(artifacts["report"]).unlink(missing_ok=True)
    Path(artifacts["decision"]).unlink(missing_ok=True)
    Path(artifacts["state"]).unlink(missing_ok=True)
