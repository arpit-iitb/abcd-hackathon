from app.config import load_config_dir
from app.graph import build_graph, set_runtime_logger
from app.json_utils import load_json
from app.state import LoanApplicationInput
from app.logging_setup import setup_logger
from app.checkpoint_utils import get_sqlite_checkpointer


def test_graph_smoke():
    config = load_config_dir("configs")
    prompts = {}
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
    checkpointer = get_sqlite_checkpointer("runs/test_checkpoints.db")
    logger = setup_logger(run_id="test", thread_id="thread-test", case_id="case-test")
    set_runtime_logger(logger)
    graph = build_graph(checkpointer)
    state = {
        "run_id": "test",
        "thread_id": "thread-test",
        "case_id": "case-test",
        "input": application.model_dump(),
        "config": config,
        "prompts": prompts,
        "results": {},
        "traces": {},
    }
    result = graph.invoke(state, config={"configurable": {"thread_id": "thread-test"}})
    approval = result.get("results", {}).get("approval", {})
    assert "decision" in approval.get("output", {})
    traces = result.get("traces", {})
    assert len(traces) == 8
