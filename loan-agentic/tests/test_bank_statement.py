from agents.bank_statement import run_bank_statement
from app.config import load_config_dir
from app.json_utils import load_json


def test_bank_statement_metrics_from_sample():
    config = load_config_dir("configs")
    sample = load_json("data/bank_statement_samples.json")[0]["transactions"]

    result = run_bank_statement(sample, config, {})
    output = result["output"]

    assert result["status"] in {"ok", "insufficient_data"}
    assert output["avg_balance"] is not None
    assert output["salary_estimate"] == 58000
    assert output["suspicious"]["flagged_txns_count"] >= 1
    assert output["suspicious"]["suspicious_ratio"] > 0
